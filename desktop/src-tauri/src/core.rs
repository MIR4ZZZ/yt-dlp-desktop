use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::Path;
use url::Url;

pub const PREFIX: &str = "__YTDLP_PROGRESS__";

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct DownloadSpec {
    pub url: String,
    pub output_dir: String,
    pub title: String,
    pub mode: String,
    pub video_quality: String,
    pub video_container: String,
    pub audio_format: String,
    pub subtitle_mode: String,
    pub subtitle_languages: String,
    pub automatic_subtitles: bool,
    pub embed_metadata: bool,
    pub embed_thumbnail: bool,
    pub playlist_mode: String,
    pub playlist_start: Option<u32>,
    pub playlist_end: Option<u32>,
    pub overwrite: String,
    pub cookie_source: String,
    pub browser: String,
    pub cookie_file: String,
    pub proxy: String,
    pub rate_limit_kbps: Option<u32>,
    pub retries: u32,
    pub extra_args: Vec<String>,
}

impl Default for DownloadSpec {
    fn default() -> Self {
        Self {
            url: String::new(), output_dir: String::new(), title: String::new(),
            mode: "video".into(), video_quality: "Best".into(), video_container: "Auto".into(),
            audio_format: "mp3".into(), subtitle_mode: "None".into(), subtitle_languages: "en".into(),
            automatic_subtitles: false, embed_metadata: true, embed_thumbnail: false,
            playlist_mode: "Single video".into(), playlist_start: None, playlist_end: None,
            overwrite: "Skip existing".into(), cookie_source: "None".into(), browser: "chrome".into(),
            cookie_file: String::new(), proxy: String::new(), rate_limit_kbps: None,
            retries: 10, extra_args: Vec::new(),
        }
    }
}

pub fn valid_url(value: &str) -> Result<String, String> {
    let value = value.trim();
    let parsed = Url::parse(value).map_err(|_| "Enter a complete http:// or https:// link.")?;
    if !matches!(parsed.scheme(), "http" | "https") || parsed.host_str().is_none() {
        return Err("Enter a complete http:// or https:// link.".into());
    }
    if !parsed.username().is_empty() || parsed.password().is_some() {
        return Err("Remove the username or password from the link before continuing.".into());
    }
    Ok(value.into())
}

pub fn safe_history_url(value: &str) -> String {
    let Ok(url) = valid_url(value) else { return String::new() };
    let Ok(mut parsed) = Url::parse(&url) else { return String::new() };
    if parsed.query_pairs().any(|(key, _)| {
        let key = key.to_ascii_lowercase();
        ["token", "auth", "key", "sig", "secret", "pass", "session", "cookie", "credential", "code"]
            .iter().any(|part| key.contains(part))
    }) { return String::new() }
    parsed.set_fragment(None);
    parsed.to_string()
}

fn access_args(spec: &DownloadSpec) -> Vec<String> {
    match spec.cookie_source.as_str() {
        "Browser" => vec!["--cookies-from-browser".into(), spec.browser.clone()],
        "Cookie file" => vec!["--cookies".into(), spec.cookie_file.clone()],
        _ => Vec::new(),
    }
}

pub fn analysis_args(spec: &DownloadSpec) -> Result<Vec<String>, String> {
    let mut args: Vec<String> = ["--dump-single-json", "--flat-playlist", "--skip-download", "--encoding", "utf-8", "--socket-timeout", "10", "--retries", "1", "--no-warnings", "--no-colors", "--remote-components", "ejs:github"]
        .iter().map(|s| (*s).into()).collect();
    args.extend(access_args(spec));
    if !spec.proxy.is_empty() { args.extend(["--proxy".into(), spec.proxy.clone()]); }
    args.extend(["--".into(), valid_url(&spec.url)?]);
    Ok(args)
}

pub fn download_args(spec: &DownloadSpec, ffmpeg_dir: &Path) -> Result<Vec<String>, String> {
    let url = valid_url(&spec.url)?;
    if spec.output_dir.trim().is_empty() { return Err("Choose a download folder.".into()) }
    if !Path::new(&spec.output_dir).is_dir() { return Err("Choose an existing download folder.".into()) }
    if !["video", "audio"].contains(&spec.mode.as_str()) { return Err("Choose Video or Audio.".into()) }
    if !["Full playlist", "Single video", "Playlist range"].contains(&spec.playlist_mode.as_str()) { return Err("Choose a playlist option.".into()) }
    if !["None", "Browser", "Cookie file"].contains(&spec.cookie_source.as_str()) { return Err("Choose a valid access option.".into()) }
    if spec.cookie_source == "Browser" && !["chrome", "firefox", "edge", "brave", "opera"].contains(&spec.browser.as_str()) { return Err("Choose a supported browser.".into()) }
    if spec.cookie_source == "Cookie file" && !Path::new(&spec.cookie_file).is_file() { return Err("Choose an existing cookie file.".into()) }
    if spec.playlist_mode == "Playlist range" && (spec.playlist_start.unwrap_or(0) == 0 || spec.playlist_end.unwrap_or(0) < spec.playlist_start.unwrap_or(0)) {
        return Err("Enter a valid playlist range.".into());
    }
    let mut args = vec!["--newline".into(), "--no-colors".into(), "--encoding".into(), "utf-8".into(), "--remote-components".into(), "ejs:github".into(),
        "--progress-template".into(), format!("download:{PREFIX}%(progress)j"),
        "--paths".into(), spec.output_dir.clone(), "--output".into(),
        if spec.mode == "audio" { "%(title)s [%(id)s] (audio).%(ext)s" } else { "%(title)s [%(id)s].%(ext)s" }.into(),
        "--retries".into(), spec.retries.to_string()];
    if !spec.proxy.is_empty() { args.extend(["--proxy".into(), spec.proxy.clone()]); }
    if let Some(rate) = spec.rate_limit_kbps { if rate > 0 { args.extend(["--limit-rate".into(), format!("{rate}K")]); } }
    args.extend(access_args(spec));
    args.extend(["--ffmpeg-location".into(), ffmpeg_dir.display().to_string()]);
    args.push(if spec.overwrite == "Overwrite" { "--force-overwrites" } else { "--no-overwrites" }.into());
    match spec.playlist_mode.as_str() {
        "Full playlist" => args.push("--yes-playlist".into()),
        "Playlist range" => {
            args.push("--yes-playlist".into());
            args.extend(["--playlist-start".into(), spec.playlist_start.unwrap().to_string(), "--playlist-end".into(), spec.playlist_end.unwrap().to_string()]);
        }
        _ => args.push("--no-playlist".into()),
    }
    if spec.mode == "audio" {
        if !["mp3", "m4a", "opus", "flac", "wav"].contains(&spec.audio_format.as_str()) { return Err("Choose a supported audio format.".into()) }
        args.extend(["--extract-audio".into(), "--audio-format".into(), spec.audio_format.clone(), "--audio-quality".into(), "0".into()]);
    } else {
        let fmt = match spec.video_quality.as_str() {
            "2160p" => "bv*[height<=2160]+ba/b[height<=2160]", "1440p" => "bv*[height<=1440]+ba/b[height<=1440]",
            "1080p" => "bv*[height<=1080]+ba/b[height<=1080]", "720p" => "bv*[height<=720]+ba/b[height<=720]",
            "480p" => "bv*[height<=480]+ba/b[height<=480]", "Best" => "bv*+ba/b",
            _ => return Err("Choose a supported quality.".into()),
        };
        args.extend(["--format".into(), fmt.into()]);
        if ["MP4", "MKV"].contains(&spec.video_container.as_str()) { args.extend(["--remux-video".into(), spec.video_container.to_lowercase()]); }
    }
    if spec.mode == "video" && spec.subtitle_mode != "None" {
        args.push("--write-subs".into());
        if spec.automatic_subtitles { args.push("--write-auto-subs".into()); }
        let langs = spec.subtitle_languages.split(',').map(str::trim).filter(|s| !s.is_empty()).collect::<Vec<_>>().join(",");
        if !langs.is_empty() { args.extend(["--sub-langs".into(), langs]); }
        if spec.subtitle_mode == "Embed" { args.push("--embed-subs".into()); }
    }
    if spec.embed_metadata { args.push("--embed-metadata".into()); }
    if spec.embed_thumbnail { args.push("--embed-thumbnail".into()); }
    args.extend(spec.extra_args.clone());
    args.extend(["--".into(), url]);
    Ok(args)
}

pub fn progress(line: &str) -> Option<Value> {
    let text = line.trim().strip_prefix(PREFIX)?;
    serde_json::from_str::<Value>(text).ok().filter(Value::is_object)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn rejects_embedded_credentials() { assert!(valid_url("https://me:secret@example.com/v").is_err()); }
    #[test] fn sensitive_links_are_not_saved() { assert_eq!(safe_history_url("https://example.com/watch?token=x"), ""); }
    #[test] fn audio_arguments_are_separate() {
        let s = DownloadSpec { url: "https://example.com/watch".into(), output_dir: std::env::temp_dir().to_string_lossy().into(), mode: "audio".into(), ..Default::default() };
        let a = download_args(&s, Path::new("C:\\tools")).unwrap();
        assert!(a.contains(&"--extract-audio".into()));
        assert_eq!(&a[a.len()-2..], ["--", "https://example.com/watch"]);
        assert!(!a.contains(&"--write-subs".into()));
    }
    #[test] fn playlist_subtitles_and_browser_map_to_arguments() {
        let s = DownloadSpec { url: "https://example.com/list".into(), output_dir: std::env::temp_dir().to_string_lossy().into(),
            playlist_mode: "Playlist range".into(), playlist_start: Some(2), playlist_end: Some(3),
            subtitle_mode: "Embed".into(), automatic_subtitles: true, cookie_source: "Browser".into(), browser: "firefox".into(), ..Default::default() };
        let a = download_args(&s, Path::new("C:\\tools")).unwrap();
        for flag in ["--playlist-start", "--playlist-end", "--embed-subs", "--write-auto-subs", "--cookies-from-browser"] {
            assert!(a.contains(&flag.to_string()), "missing {flag}");
        }
        assert!(a.windows(2).any(|v| v == ["--playlist-start", "2"]));
        assert!(a.windows(2).any(|v| v == ["--cookies-from-browser", "firefox"]));
    }
    #[test] fn progress_requires_marker_and_valid_json() {
        assert!(progress("[download] 50%").is_none());
        assert!(progress("__YTDLP_PROGRESS__bad").is_none());
        assert_eq!(progress("__YTDLP_PROGRESS__{\"_percent_str\":\" 50%\"}").unwrap()["_percent_str"], " 50%");
    }
}
