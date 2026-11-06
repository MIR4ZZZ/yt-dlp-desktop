use crate::{core::{self, DownloadSpec}, engine, tools, read_data, write_data};
use serde::Serialize;
use serde_json::{Value, json};
use std::{io::{BufRead, BufReader}, os::windows::process::CommandExt, path::PathBuf,
    process::{Child, Command, Stdio}, sync::{Arc, Mutex, atomic::{AtomicBool, Ordering}}, thread, time::Duration};
use tauri::Emitter;

#[derive(Clone, Serialize)]
pub struct Job {
    pub id: String,
    pub spec: DownloadSpec,
    pub status: String,
    pub percent: f64,
    pub speed: String,
    pub eta: String,
    pub log: Vec<String>,
}

#[derive(Default)]
pub struct Queue {
    pub jobs: Mutex<Vec<Job>>,
    child: Mutex<Option<(String, Child)>>,
    running: AtomicBool,
    paused: AtomicBool,
}

fn emit(app: &tauri::AppHandle, queue: &Arc<Queue>) {
    if let Ok(jobs) = queue.jobs.lock() { let _ = app.emit("queue-updated", jobs.clone()); }
}

fn same_running_child(held: &mut Option<(String, Child)>, id: &str, pid: u32) -> bool {
    held.as_mut().is_some_and(|(active_id, child)|
        active_id == id && child.id() == pid && child.try_wait().ok().flatten().is_none())
}

impl Queue {
    pub fn add(self: &Arc<Self>, app: tauri::AppHandle, spec: DownloadSpec, start_now: bool) -> Result<(), String> {
        core::download_args(&spec, &tools()?)?;
        self.jobs.lock().unwrap().push(Job { id: uuid::Uuid::new_v4().to_string(), spec,
            status: "Queued".into(), percent: 0.0, speed: String::new(), eta: String::new(), log: Vec::new() });
        emit(&app, self);
        if start_now { self.paused.store(false, Ordering::SeqCst); self.start(app); }
        Ok(())
    }

    pub fn action(self: &Arc<Self>, app: tauri::AppHandle, action: &str, id: Option<&str>) -> Result<(), String> {
        match action {
            "pause" => self.paused.store(true, Ordering::SeqCst),
            "resume" => { self.paused.store(false, Ordering::SeqCst); self.start(app.clone()); },
            "stop" => {
                let mut held = self.child.lock().unwrap();
                if let Some((active_id, child)) = held.as_mut() {
                    if id.is_none_or(|id| id == active_id) {
                        let pid = child.id();
                        let stopped_id = active_id.clone();
                        let system = std::env::var_os("SystemRoot").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("C:\\Windows"));
                        let _ = Command::new(system.join("System32").join("taskkill.exe"))
                            .args(["/PID", &pid.to_string(), "/T"]).creation_flags(0x08000000).status();
                        if let Some(job) = self.jobs.lock().unwrap().iter_mut().find(|job| job.id == *active_id) { job.status = "Stopped".into(); }
                        drop(held);
                        let queue = self.clone();
                        thread::spawn(move || {
                            thread::sleep(Duration::from_secs(2));
                            let mut held = queue.child.lock().unwrap();
                            if same_running_child(&mut held, &stopped_id, pid) {
                                let _ = Command::new(system.join("System32").join("taskkill.exe"))
                                    .args(["/PID", &pid.to_string(), "/T", "/F"]).creation_flags(0x08000000).status();
                                let _ = held.as_mut().unwrap().1.kill();
                            }
                        });
                    }
                }
            }
            "remove" => {
                let id = id.ok_or("Select a job")?;
                self.jobs.lock().unwrap().retain(|job| job.id != id || job.status == "Downloading");
            }
            "retry" => {
                let id = id.ok_or("Select a job")?;
                if let Some(job) = self.jobs.lock().unwrap().iter_mut().find(|job| job.id == id && job.status == "Failed") {
                    job.status = "Queued".into(); job.percent = 0.0; job.log.clear();
                }
            }
            "up" | "down" => {
                let id = id.ok_or("Select a job")?;
                let mut jobs = self.jobs.lock().unwrap();
                if let Some(index) = jobs.iter().position(|job| job.id == id && job.status == "Queued") {
                    let other = if action == "up" { index.checked_sub(1) } else { Some(index + 1) };
                    if let Some(other) = other.filter(|other| *other < jobs.len() && jobs[*other].status == "Queued") { jobs.swap(index, other); }
                }
            }
            _ => return Err("Unknown queue action".into()),
        }
        emit(&app, self);
        Ok(())
    }

    fn start(self: &Arc<Self>, app: tauri::AppHandle) {
        if self.running.swap(true, Ordering::SeqCst) { return }
        let queue = self.clone();
        thread::spawn(move || {
            loop {
                if queue.paused.load(Ordering::SeqCst) { break }
                let next = {
                    let mut jobs = queue.jobs.lock().unwrap();
                    jobs.iter_mut().find(|job| job.status == "Queued").map(|job| {
                        job.status = "Downloading".into(); (job.id.clone(), job.spec.clone())
                    })
                };
                let Some((id, spec)) = next else { break };
                emit(&app, &queue);
                let result = queue.run(&app, &id, &spec);
                let success = result.is_ok();
                let completed = {
                    let mut jobs = queue.jobs.lock().unwrap();
                    if let Some(job) = jobs.iter_mut().find(|job| job.id == id) {
                        if job.status != "Stopped" {
                            job.status = if success { "Completed" } else { "Failed" }.into();
                            if let Err(message) = result { job.log.push(message); }
                            success
                        } else {
                            false
                        }
                    } else { false }
                };
                if completed { save_success(&spec); }
                if completed { let _ = app.emit("history-updated", crate::clean_history(read_data("history.json", json!({"schema_version":2,"items":[]}))).get("items").cloned().unwrap_or(json!([]))); }
                emit(&app, &queue);
            }
            queue.running.store(false, Ordering::SeqCst);
            if !queue.paused.load(Ordering::SeqCst) && queue.jobs.lock().unwrap().iter().any(|job| job.status == "Queued") { queue.start(app); }
        });
    }

    fn run(self: &Arc<Self>, app: &tauri::AppHandle, id: &str, spec: &DownloadSpec) -> Result<(), String> {
        let mut child = Command::new(engine()?).args(core::download_args(spec, &tools()?)?)
            .stdout(Stdio::piped()).stderr(Stdio::piped()).creation_flags(0x08000000)
            .spawn().map_err(|e| e.to_string())?;
        let stdout = child.stdout.take().ok_or("No download output")?;
        let stderr = child.stderr.take().ok_or("No download log")?;
        *self.child.lock().unwrap() = Some((id.into(), child));
        let queue = self.clone(); let app1 = app.clone(); let id1 = id.to_string();
        let out = thread::spawn(move || for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if let Some(data) = core::progress(&line) {
                let mut jobs = queue.jobs.lock().unwrap();
                if let Some(job) = jobs.iter_mut().find(|job| job.id == id1) {
                    job.percent = data.get("_percent_str").and_then(Value::as_str).unwrap_or("0").trim().trim_end_matches('%').trim().parse().unwrap_or(0.0);
                    job.speed = data.get("_speed_str").and_then(Value::as_str).unwrap_or("").into();
                    job.eta = data.get("_eta_str").and_then(Value::as_str).unwrap_or("").into();
                }
                drop(jobs); emit(&app1, &queue);
            } else if !line.starts_with(core::PREFIX) {
                let mut jobs = queue.jobs.lock().unwrap();
                if let Some(job) = jobs.iter_mut().find(|job| job.id == id1) {
                    job.log.push(line);
                    if job.log.len() > 200 { job.log.remove(0); }
                }
                drop(jobs); emit(&app1, &queue);
            }
        });
        let queue = self.clone(); let app2 = app.clone(); let id2 = id.to_string();
        let err = thread::spawn(move || for line in BufReader::new(stderr).lines().map_while(Result::ok) {
            let mut jobs = queue.jobs.lock().unwrap();
            if let Some(job) = jobs.iter_mut().find(|job| job.id == id2) {
                job.log.push(line);
                if job.log.len() > 200 { job.log.remove(0); }
            }
            drop(jobs); emit(&app2, &queue);
        });
        let status = loop {
            let mut held = self.child.lock().unwrap();
            let Some((_, child)) = held.as_mut() else { return Err("Download stopped".into()) };
            if let Some(status) = child.try_wait().map_err(|e| e.to_string())? { break status }
            drop(held); thread::sleep(Duration::from_millis(120));
        };
        *self.child.lock().unwrap() = None;
        let _ = out.join(); let _ = err.join();
        if status.success() { Ok(()) } else { Err(format!("yt-dlp exited with {status}")) }
    }
}

fn save_success(spec: &DownloadSpec) {
    let mut history = read_data("history.json", json!({"schema_version":2,"items":[]}));
    let items = history.get_mut("items").and_then(Value::as_array_mut);
    let Some(items) = items else { return };
    let safe_url = core::safe_history_url(&spec.url);
    let mut safe_spec = serde_json::to_value(spec).unwrap_or(json!({}));
    if let Some(fields) = safe_spec.as_object_mut() {
        fields.insert("url".into(), json!(safe_url));
        for key in ["cookie_source", "cookie_file", "browser", "proxy", "extra_args"] { fields.remove(key); }
    }
    items.insert(0, json!({"url": safe_url, "title": if safe_url.is_empty() { "Completed download" } else { &spec.title },
        "output_dir": spec.output_dir, "spec": safe_spec, "completed_at": format!("{}Z", chrono::Utc::now().format("%Y-%m-%dT%H:%M:%S"))}));
    items.truncate(100);
    let _ = write_data("history.json", &history);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn delayed_stop_cannot_match_the_next_job() {
        let child = Command::new("powershell.exe").args(["-NoProfile", "-Command", "Start-Sleep -Seconds 10"])
            .creation_flags(0x08000000).spawn().unwrap();
        let pid = child.id();
        let mut held = Some(("next-job".into(), child));
        assert!(!same_running_child(&mut held, "stopped-job", pid));
        assert!(!same_running_child(&mut held, "next-job", pid + 1));
        assert!(same_running_child(&mut held, "next-job", pid));
        let child = &mut held.as_mut().unwrap().1;
        child.kill().unwrap();
        child.wait().unwrap();
        assert!(!same_running_child(&mut held, "next-job", pid));
    }
}
