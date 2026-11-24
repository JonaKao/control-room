//! The app's own settings: where they live, and what they hold. The checks point `--config` at a
//! temporary folder so they never touch the real one.

use std::path::{Path, PathBuf};

use serde_json::{Map, Value};

pub const APP_NAME: &str = "Agent Control Room";

/// The app's settings folder: %APPDATA%\Agent Control Room on Windows,
/// ~/Library/Application Support/Agent Control Room on a Mac.
pub fn default_config_dir() -> PathBuf {
    if cfg!(windows) {
        if let Some(d) = std::env::var_os("APPDATA") {
            return PathBuf::from(d).join(APP_NAME);
        }
    } else if cfg!(target_os = "macos") {
        if let Some(h) = std::env::var_os("HOME") {
            return PathBuf::from(h).join("Library").join("Application Support").join(APP_NAME);
        }
    }
    let base = std::env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".config")))
        .unwrap_or_else(|| PathBuf::from("."));
    base.join(APP_NAME)
}

/// settings.json in the config folder, or an empty object.
pub fn load_settings(config: &Path) -> Map<String, Value> {
    match crate::records::read_json(&config.join("settings.json")) {
        Some(Value::Object(m)) => m,
        _ => Map::new(),
    }
}

/// The Python path chosen in the settings, if any.
pub fn python_path(settings: &Map<String, Value>) -> Option<String> {
    settings.get("python").and_then(|v| v.as_str()).map(|s| s.to_string()).filter(|s| !s.trim().is_empty())
}
