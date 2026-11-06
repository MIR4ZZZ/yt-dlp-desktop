mod core;
mod queue;

use core::{DownloadSpec, analysis_args, download_args};
use serde_json::{Value, json};
use std::{path::PathBuf, process::{Command, Stdio}, sync::{Arc, Mutex, atomic::{AtomicU64, Ordering}}, time::{Duration, Instant}};
use std::os::windows::process::CommandExt;

#[derive(Default)]
struct State { analysis: Mutex<Option<(u64, std::process::Child)>>, generation: AtomicU64 }

pub(crate) fn engine() -> Result<PathBuf, String> {
    if let Some(path) = std::env::var_os("YTDLP_DESKTOP_ENGINE") { return Ok(path.into()) }
    Ok(std::env::current_exe().map_err(|e| e.to_string())?.parent().ok_or("App directory missing")?.join("engine").join("yt-dlp.exe"))
}

pub(crate) fn tools() -> Result<PathBuf, String> {
    if let Some(path) = std::env::var_os("YTDLP_DESKTOP_TOOLS") { return Ok(path.into()) }
    Ok(std::env::current_exe().map_err(|e| e.to_string())?.parent().ok_or("App directory missing")?.join("tools"))
}

fn data_file(name: &str) -> PathBuf {
    std::env::var_os("LOCALAPPDATA").map(PathBuf::from).unwrap_or_else(std::env::temp_dir).join("yt-dlp-ui").join(name)
}

pub(crate) fn read_data(name: &str, default: Value) -> Value {
    let path = data_file(name);
    match std::fs::read_to_string(&path) {
        Ok(text) => match serde_json::from_str(&text) {
            Ok(value) => value,
            Err(_) => { backup_bad_data(&path, None); default }
        },
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => default,
        Err(_) => default,
    }
}

fn backup_bad_data(path: &std::path::Path, parsed: Option<&Value>) {
    let Some(parent) = path.parent() else { return };
    let name = path.file_stem().and_then(|name| name.to_str()).unwrap_or("data");
    let stamp = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_nanos();
    let backup = parent.join(format!("{name}.corrupt-{stamp}.bak"));
    // Invalid JSON cannot be reliably redacted; retain a marker without private data.
    let safe = parsed.map(|value| if name == "settings" { clean_settings(value.clone()) } else { clean_history(value.clone()) });
    let bytes = safe.and_then(|value| serde_json::to_vec_pretty(&value).ok()).unwrap_or_else(|| b"Invalid JSON omitted for privacy".to_vec());
    if std::fs::write(backup, bytes).is_ok() { let _ = std::fs::remove_file(path); }
}

fn default_settings() -> Value {
    let videos = std::env::var_os("USERPROFILE").map(PathBuf::from).unwrap_or_default().join("Videos");
    json!({"schema_version":2,"download_dir":videos.to_string_lossy(),"open_folder_on_done":true,
        "mode":"video","video_quality":"Best","video_container":"Auto","audio_format":"mp3",
        "subtitle_mode":"None","subtitle_languages":"en","automatic_subtitles":false,
        "embed_metadata":true,"embed_thumbnail":false,"overwrite":"Skip existing","retries":10,"rate_limit_kbps":null})
}

fn clean_settings(raw: Value) -> Value {
    let defaults = default_settings();
    let Some(raw) = raw.as_object() else { return defaults };
    let mut clean = defaults.as_object().unwrap().clone();
    for (key, value) in raw {
        if !clean.contains_key(key) { continue }
        let valid = match key.as_str() {
            "schema_version" => value.as_u64().is_some_and(|v| v == 1 || v == 2),
            "download_dir" | "subtitle_languages" => value.as_str().is_some_and(|s| s.len() <= 4096),
            "mode" => matches!(value.as_str(), Some("video" | "audio")),
            "video_quality" => matches!(value.as_str(), Some("Best" | "2160p" | "1440p" | "1080p" | "720p" | "480p")),
            "video_container" => matches!(value.as_str(), Some("Auto" | "MP4" | "MKV")),
            "audio_format" => matches!(value.as_str(), Some("mp3" | "m4a" | "opus" | "flac" | "wav")),
            "subtitle_mode" => matches!(value.as_str(), Some("None" | "Embed" | "Separate file")),
            "overwrite" => matches!(value.as_str(), Some("Skip existing" | "Overwrite")),
            "open_folder_on_done" | "automatic_subtitles" | "embed_metadata" | "embed_thumbnail" => value.is_boolean(),
            "retries" => value.as_u64().is_some_and(|v| v <= 100),
            "rate_limit_kbps" => value.is_null() || value.as_u64().is_some_and(|v| v <= 100_000_000),
            _ => false,
        };
        if !valid { return defaults }
        if key != "schema_version" { clean.insert(key.clone(), value.clone()); }
    }
    Value::Object(clean)
}

fn clean_history(raw: Value) -> Value {
    let Some(items) = raw.get("items").and_then(Value::as_array) else { return json!({"schema_version":2,"items":[]}) };
    let items: Vec<Value> = items.iter().take(100).filter_map(|item| {
        let obj = item.as_object()?;
        let original = obj.get("url").and_then(Value::as_str).unwrap_or("");
        let url = core::safe_history_url(original);
        let title = obj.get("title").and_then(Value::as_str).unwrap_or("Completed download");
        let title = if url.is_empty() && (title == original || core::valid_url(title).is_ok()) { "Completed download" } else { title };
        let mut spec = serde_json::from_value::<DownloadSpec>(obj.get("spec")?.clone()).ok()
            .and_then(|spec| serde_json::to_value(spec).ok())?;
        let fields = spec.as_object_mut()?;
        fields.insert("url".into(), json!(url));
        for key in ["proxy", "cookie_source", "cookie_file", "browser", "extra_args"] { fields.remove(key); }
        Some(json!({"url":url,"title":title,"output_dir":obj.get("output_dir").and_then(Value::as_str).unwrap_or(""),
            "completed_at":obj.get("completed_at").and_then(Value::as_str).unwrap_or(""),"spec":spec}))
    }).collect();
    json!({"schema_version":2,"items":items})
}

fn valid_settings(raw: &Value) -> bool {
    raw.is_object() && clean_settings(raw.clone()) == {
        let mut expected = default_settings();
        if let (Some(dst), Some(src)) = (expected.as_object_mut(), raw.as_object()) {
            for (key, value) in src { if dst.contains_key(key) && key != "schema_version" { dst.insert(key.clone(), value.clone()); } }
        }
        expected
    }
}

#[tauri::command]
fn bootstrap(queue: tauri::State<'_, Arc<queue::Queue>>) -> Value {
    let raw_settings = read_data("settings.json", default_settings());
    if !valid_settings(&raw_settings) { backup_bad_data(&data_file("settings.json"), Some(&raw_settings)); }
    let settings = clean_settings(raw_settings);
    let raw_history = read_data("history.json", json!({"schema_version":2,"items":[]}));
    if !raw_history.get("items").is_some_and(Value::is_array) { backup_bad_data(&data_file("history.json"), Some(&raw_history)); }
    let history = clean_history(raw_history);
    let _ = write_data("settings.json", &settings);
    let _ = write_data("history.json", &history);
    json!({"settings": settings,
        "history": history.get("items").cloned().unwrap_or(json!([])),
        "jobs": queue.jobs.lock().unwrap().clone()})
}

pub(crate) fn write_data(name: &str, value: &Value) -> Result<(), String> {
    let path = data_file(name);
    std::fs::create_dir_all(path.parent().ok_or("Data directory missing")?).map_err(|e| e.to_string())?;
    let tmp = path.with_extension("json.tmp");
    std::fs::write(&tmp, serde_json::to_vec_pretty(value).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
    std::fs::rename(tmp, path).map_err(|e| e.to_string())
}

#[tauri::command]
fn command_preview(spec: DownloadSpec) -> Result<Vec<String>, String> { download_args(&spec, &tools()?) }

#[tauri::command]
fn save_settings(settings: Value) -> Result<(), String> {
    if !valid_settings(&settings) { return Err("Invalid settings".into()) }
    write_data("settings.json", &clean_settings(settings))
}

#[tauri::command]
fn add_job(app: tauri::AppHandle, queue: tauri::State<'_, Arc<queue::Queue>>, spec: DownloadSpec, start_now: bool) -> Result<(), String> {
    queue.inner().add(app, spec, start_now)
}

#[tauri::command]
fn queue_action(app: tauri::AppHandle, queue: tauri::State<'_, Arc<queue::Queue>>, action: String, id: Option<String>) -> Result<(), String> {
    queue.inner().action(app, &action, id.as_deref())
}

#[tauri::command]
fn clear_history() -> Result<(), String> {
    write_data("history.json", &json!({"schema_version":2,"items":[]}))
}

#[tauri::command]
fn open_folder(path: String) -> Result<(), String> {
    if !std::path::Path::new(&path).is_dir() { return Err("Folder no longer exists.".into()) }
    Command::new("explorer.exe").arg(path).spawn().map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
async fn analyze(state: tauri::State<'_, Arc<State>>, spec: DownloadSpec) -> Result<Value, String> {
    let state = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        let generation = state.generation.fetch_add(1, Ordering::SeqCst) + 1;
        if let Some((_, mut old)) = state.analysis.lock().unwrap().take() { queue::force_tree(&mut old); }
        let mut child = Command::new(engine()?).args(analysis_args(&spec)?).stdout(Stdio::piped()).stderr(Stdio::piped())
            .creation_flags(0x08000000).spawn().map_err(|e| e.to_string())?;
        let mut stdout = child.stdout.take().ok_or("Analysis output unavailable")?;
        let mut stderr = child.stderr.take().ok_or("Analysis log unavailable")?;
        let output_reader = std::thread::spawn(move || { let mut text = String::new(); use std::io::Read; let _ = stdout.read_to_string(&mut text); text });
        let error_reader = std::thread::spawn(move || { let mut text = String::new(); use std::io::Read; let _ = stderr.read_to_string(&mut text); text });
        {
            let mut held = state.analysis.lock().unwrap();
            if state.generation.load(Ordering::SeqCst) != generation { queue::force_tree(&mut child); return Err("Analysis canceled".into()) }
            *held = Some((generation, child));
        }
        let started = Instant::now();
        loop {
            let mut held = state.analysis.lock().unwrap();
            let Some((current, child)) = held.as_mut() else { return Err("Analysis canceled".into()) };
            if *current != generation { return Err("Analysis canceled".into()) }
            if let Some(status) = child.try_wait().map_err(|e| e.to_string())? {
                held.take(); drop(held);
                let text = output_reader.join().unwrap_or_default();
                let error = error_reader.join().unwrap_or_default();
                if !status.success() { return Err(error.lines().last().unwrap_or("Analysis unavailable. You can download with defaults.").into()) }
                return serde_json::from_str(&text).map_err(|_| "Analysis unavailable. You can download with defaults.".into());
            }
            if started.elapsed() >= Duration::from_secs(45) {
                queue::force_tree(child); *held = None;
                return Err("Analysis timed out. You can download with defaults.".into());
            }
            drop(held); std::thread::sleep(Duration::from_millis(100));
        }
    }).await.map_err(|e| e.to_string())?
}

#[tauri::command]
fn cancel_analysis(state: tauri::State<'_, Arc<State>>) {
    state.generation.fetch_add(1, Ordering::SeqCst);
    if let Some((_, mut child)) = state.analysis.lock().unwrap().take() { queue::force_tree(&mut child); }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(Arc::new(State::default()))
        .manage(Arc::new(queue::Queue::default()))
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![bootstrap, save_settings, command_preview, analyze, cancel_analysis, add_job, queue_action, clear_history, open_folder])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn invalid_settings_recover_to_defaults() {
        let mut settings = default_settings();
        settings["retries"] = json!("many");
        assert!(!valid_settings(&settings));
        assert_eq!(clean_settings(settings), default_settings());
    }
    #[test]
    fn legacy_proxy_and_sensitive_link_are_erased() {
        let settings = json!({"schema_version":1,"proxy":"http://name:pass@server:8080"});
        assert!(valid_settings(&settings));
        assert!(clean_settings(settings).get("proxy").is_none());
        let history = clean_history(json!({"items":[{"url":"https://example.com/v?token=secret","proxy":"secret","spec":{"url":"https://example.com/v?token=secret","cookie_file":"C:\\secret.txt"}}]}));
        assert_eq!(history["items"][0]["url"], "");
        assert_eq!(history["items"][0]["spec"]["url"], "");
        assert!(history["items"][0].get("proxy").is_none());
        assert!(history["items"][0]["spec"].get("cookie_file").is_none());
    }
}
