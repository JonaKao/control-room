//! The app's own settings and its list of workspaces, kept in `settings.json` in the app's settings
//! folder (or `--config DIR`, so checks never touch the real one). One workspace is shown at a time.
//!
//! settings.json: {"workspaces": [{"path": "...", "name": "..."}], "current": "...", "python": "...",
//! "start_at_login": false, "notify": {...}}. Keys this version does not know are kept as they are.

use std::path::{Path, PathBuf};
use std::sync::Mutex;

use serde_json::{json, Map, Value};

pub const APP_NAME: &str = "Agent Control Room";
pub const MAX_NAME: usize = 60;

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

fn absolute(p: &Path) -> PathBuf {
    std::path::absolute(p).unwrap_or_else(|_| p.to_path_buf())
}

/// Two paths name the same folder (Windows and macOS ignore case in folder names by default).
pub fn same_path(a: &Path, b: &Path) -> bool {
    let norm = |p: &Path| {
        let s = absolute(p).to_string_lossy().trim_end_matches(['/', '\\']).to_string();
        if cfg!(any(windows, target_os = "macos")) { s.to_lowercase() } else { s }
    };
    norm(a) == norm(b)
}

/// Is this folder a workspace? A workspace holds a `projects` folder (and normally `framework/aaf.py`;
/// without it the page says the framework tool is missing). Returns the reason in plain words if not.
pub fn check_folder(path: &Path) -> Result<PathBuf, String> {
    if path.as_os_str().is_empty() {
        return Err("Choose a folder first.".into());
    }
    if !path.is_dir() {
        return Err(format!("There is no folder at {}.", path.display()));
    }
    if !path.join("projects").is_dir() {
        return Err(format!(
            "{} is not a workspace: it has no projects folder. Choose the folder of the Agentic AI Framework that \
             holds the folders framework and projects.",
            path.display()
        ));
    }
    Ok(absolute(path))
}

fn default_name(path: &Path) -> String {
    path.file_name().map(|n| n.to_string_lossy().into_owned()).filter(|n| !n.is_empty()).unwrap_or_else(|| path.display().to_string())
}

#[derive(Clone, Debug, PartialEq)]
pub struct Entry {
    pub path: PathBuf,
    pub name: String,
    /// false: given with --root for this run only, not in the settings file
    pub saved: bool,
}

struct State {
    settings: Map<String, Value>,
    /// --root: shown first and chosen for this run, not saved unless renamed
    extra: Option<PathBuf>,
    current: Option<PathBuf>,
}

/// The workspace list, the current workspace and the rest of the settings.
pub struct Workspaces {
    config: PathBuf,
    state: Mutex<State>,
}

impl Workspaces {
    pub fn new(config: PathBuf, root: Option<PathBuf>) -> Self {
        let settings = load_settings(&config);
        let extra = root.map(|r| absolute(&r));
        let w = Workspaces { config, state: Mutex::new(State { settings, extra: extra.clone(), current: None }) };
        let saved = w.saved();
        let wanted = w.state.lock().unwrap().settings.get("current").and_then(|v| v.as_str()).map(PathBuf::from);
        let current = extra
            .or_else(|| wanted.filter(|c| saved.iter().any(|e| same_path(&e.path, c))))
            .or_else(|| saved.first().map(|e| e.path.clone()));
        w.state.lock().unwrap().current = current;
        w
    }

    pub fn config_dir(&self) -> &Path {
        &self.config
    }

    fn saved_from(settings: &Map<String, Value>) -> Vec<Entry> {
        let mut out: Vec<Entry> = Vec::new();
        if let Some(Value::Array(list)) = settings.get("workspaces") {
            for w in list {
                let Some(p) = w.get("path").and_then(|v| v.as_str()).filter(|s| !s.is_empty()) else { continue };
                let path = PathBuf::from(p);
                if out.iter().any(|e| same_path(&e.path, &path)) {
                    continue;
                }
                let name = w.get("name").and_then(|v| v.as_str()).map(|s| s.trim().to_string()).filter(|s| !s.is_empty())
                    .unwrap_or_else(|| default_name(&path));
                out.push(Entry { path, name, saved: true });
            }
        }
        out
    }

    fn saved(&self) -> Vec<Entry> {
        Self::saved_from(&self.state.lock().unwrap().settings)
    }

    /// Every workspace: --root first if it is not saved, then the saved ones in their order.
    pub fn list(&self) -> Vec<Entry> {
        let st = self.state.lock().unwrap();
        let mut out = Self::saved_from(&st.settings);
        if let Some(x) = &st.extra {
            if !out.iter().any(|e| same_path(&e.path, x)) {
                out.insert(0, Entry { path: x.clone(), name: default_name(x), saved: false });
            }
        }
        out
    }

    pub fn current(&self) -> Option<PathBuf> {
        self.state.lock().unwrap().current.clone()
    }

    fn find(&self, path: &Path) -> Option<Entry> {
        self.list().into_iter().find(|e| same_path(&e.path, path))
    }

    fn write(&self, st: &mut State) -> Result<(), String> {
        if let Some(c) = &st.current {
            if Self::saved_from(&st.settings).iter().any(|e| same_path(&e.path, c)) {
                st.settings.insert("current".into(), Value::String(c.to_string_lossy().into_owned()));
            }
        }
        std::fs::create_dir_all(&self.config).map_err(|e| format!("The settings could not be saved: {e}"))?;
        let tmp = self.config.join("settings.json.tmp");
        let text = serde_json::to_string_pretty(&Value::Object(st.settings.clone())).unwrap_or_default();
        std::fs::write(&tmp, text).map_err(|e| format!("The settings could not be saved: {e}"))?;
        std::fs::rename(&tmp, self.config.join("settings.json")).map_err(|e| format!("The settings could not be saved: {e}"))
    }

    fn set_saved(st: &mut State, list: &[Entry]) {
        let arr: Vec<Value> = list
            .iter()
            .filter(|e| e.saved)
            .map(|e| json!({"path": e.path.to_string_lossy(), "name": e.name}))
            .collect();
        st.settings.insert("workspaces".into(), Value::Array(arr));
    }

    /// Add a folder (or choose it again if it is already listed) and show it.
    pub fn add(&self, path: &Path, name: Option<&str>) -> Result<Entry, String> {
        let path = check_folder(path)?;
        let name = clean_name(name.unwrap_or(""))?.unwrap_or_else(|| default_name(&path));
        let mut st = self.state.lock().unwrap();
        let mut saved = Self::saved_from(&st.settings);
        let entry = match saved.iter().find(|e| same_path(&e.path, &path)) {
            Some(e) => e.clone(),
            None => {
                let e = Entry { path: path.clone(), name, saved: true };
                saved.push(e.clone());
                e
            }
        };
        Self::set_saved(&mut st, &saved);
        st.current = Some(entry.path.clone());
        self.write(&mut st)?;
        Ok(entry)
    }

    pub fn select(&self, path: &Path) -> Result<(), String> {
        let e = self.find(path).ok_or_else(|| "That workspace is not in the list.".to_string())?;
        let mut st = self.state.lock().unwrap();
        st.current = Some(e.path);
        if e.saved {
            self.write(&mut st)?;
        }
        Ok(())
    }

    pub fn rename(&self, path: &Path, name: &str) -> Result<(), String> {
        let e = self.find(path).ok_or_else(|| "That workspace is not in the list.".to_string())?;
        let name = clean_name(name)?.ok_or_else(|| "Give the workspace a name.".to_string())?;
        let mut st = self.state.lock().unwrap();
        let mut saved = Self::saved_from(&st.settings);
        match saved.iter_mut().find(|s| same_path(&s.path, &e.path)) {
            Some(s) => s.name = name,
            None => saved.insert(0, Entry { path: e.path, name, saved: true }), // --root: renaming keeps it
        }
        Self::set_saved(&mut st, &saved);
        self.write(&mut st)
    }

    /// Take a workspace off the list (its folder is not touched).
    pub fn remove(&self, path: &Path) -> Result<(), String> {
        let e = self.find(path).ok_or_else(|| "That workspace is not in the list.".to_string())?;
        let mut st = self.state.lock().unwrap();
        let saved: Vec<Entry> = Self::saved_from(&st.settings).into_iter().filter(|s| !same_path(&s.path, &e.path)).collect();
        if st.extra.as_ref().map(|x| same_path(x, &e.path)).unwrap_or(false) {
            st.extra = None;
        }
        Self::set_saved(&mut st, &saved);
        if st.current.as_ref().map(|c| same_path(c, &e.path)).unwrap_or(false) {
            st.current = st.extra.clone().or_else(|| saved.first().map(|s| s.path.clone()));
            match &st.current {
                Some(c) => {
                    let c = c.to_string_lossy().into_owned();
                    st.settings.insert("current".into(), Value::String(c));
                }
                None => {
                    st.settings.remove("current");
                }
            }
        }
        self.write(&mut st)
    }

    pub fn python(&self) -> Option<String> {
        python_path(&self.state.lock().unwrap().settings)
    }

    pub fn set_python(&self, path: &str) -> Result<(), String> {
        let mut st = self.state.lock().unwrap();
        let p = path.trim();
        if p.is_empty() {
            st.settings.remove("python");
        } else {
            st.settings.insert("python".into(), Value::String(p.to_string()));
        }
        self.write(&mut st)
    }

    /// A setting by name (for the parts of the app that keep their own, such as notifications).
    pub fn get(&self, key: &str) -> Option<Value> {
        self.state.lock().unwrap().settings.get(key).cloned()
    }

    pub fn set(&self, key: &str, value: Value) -> Result<(), String> {
        let mut st = self.state.lock().unwrap();
        st.settings.insert(key.into(), value);
        self.write(&mut st)
    }

    /// What the page needs: every workspace, whether its folder is there, which one is shown.
    pub fn to_json(&self) -> Value {
        let current = self.current();
        let list: Vec<Value> = self
            .list()
            .iter()
            .map(|e| {
                json!({"path": e.path.to_string_lossy(), "name": e.name, "saved": e.saved,
                       "found": e.path.join("projects").is_dir(),
                       "current": current.as_ref().map(|c| same_path(c, &e.path)).unwrap_or(false)})
            })
            .collect();
        json!({"workspaces": list, "current": current.map(|c| c.to_string_lossy().into_owned())})
    }
}

fn clean_name(name: &str) -> Result<Option<String>, String> {
    let n: String = name.trim().chars().filter(|c| !c.is_control()).collect();
    if n.is_empty() {
        return Ok(None);
    }
    if n.chars().count() > MAX_NAME {
        return Err(format!("Keep the name under {} characters.", MAX_NAME));
    }
    Ok(Some(n))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ws(dir: &Path, name: &str) -> PathBuf {
        let p = dir.join(name);
        std::fs::create_dir_all(p.join("projects")).unwrap();
        p
    }

    #[test]
    fn add_select_rename_remove_and_restart() {
        let tmp = tempfile::tempdir().unwrap();
        let cfg = tmp.path().join("config");
        let a = ws(tmp.path(), "alpha");
        let b = ws(tmp.path(), "beta");
        let w = Workspaces::new(cfg.clone(), None);
        assert_eq!(w.current(), None);
        assert!(w.list().is_empty());
        w.add(&a, None).unwrap();
        w.add(&b, Some("Second")).unwrap();
        assert!(same_path(&w.current().unwrap(), &b), "adding shows the new workspace");
        assert_eq!(w.list().iter().map(|e| e.name.as_str()).collect::<Vec<_>>(), ["alpha", "Second"]);
        w.select(&a).unwrap();
        w.rename(&a, "  Main  ").unwrap();
        assert!(w.rename(&a, "   ").is_err());
        assert!(w.rename(&a, &"x".repeat(61)).is_err());
        // A restart reads the same list, names and current workspace.
        let again = Workspaces::new(cfg.clone(), None);
        assert_eq!(again.list().iter().map(|e| e.name.as_str()).collect::<Vec<_>>(), ["Main", "Second"]);
        assert!(same_path(&again.current().unwrap(), &a));
        again.remove(&a).unwrap();
        assert!(same_path(&again.current().unwrap(), &b), "removing the shown one shows the next");
        again.remove(&b).unwrap();
        assert_eq!(again.current(), None);
        assert!(again.select(&a).is_err());
        assert!(Workspaces::new(cfg, None).list().is_empty());
    }

    #[test]
    fn refuses_a_folder_that_is_not_a_workspace() {
        let tmp = tempfile::tempdir().unwrap();
        let w = Workspaces::new(tmp.path().join("config"), None);
        let plain = tmp.path().join("plain");
        std::fs::create_dir_all(&plain).unwrap();
        let err = w.add(&plain, None).unwrap_err();
        assert!(err.contains("not a workspace") && err.contains("projects"), "{err}");
        assert!(w.add(&tmp.path().join("missing"), None).unwrap_err().contains("no folder"));
        assert!(w.add(Path::new(""), None).is_err());
        assert!(w.list().is_empty());
        assert!(!tmp.path().join("config").join("settings.json").exists(), "a refusal writes nothing");
    }

    #[test]
    fn a_missing_folder_stays_listed_as_not_found() {
        let tmp = tempfile::tempdir().unwrap();
        let cfg = tmp.path().join("config");
        let a = ws(tmp.path(), "alpha");
        let b = ws(tmp.path(), "beta");
        let w = Workspaces::new(cfg.clone(), None);
        w.add(&a, None).unwrap();
        w.add(&b, None).unwrap();
        std::fs::remove_dir_all(&b).unwrap();
        let again = Workspaces::new(cfg, None);
        let j = again.to_json();
        let list = j["workspaces"].as_array().unwrap();
        assert_eq!(list.len(), 2);
        assert_eq!(list[1]["found"], false);
        assert_eq!(list[1]["current"], true, "still shown, as not found");
        assert_eq!(list[0]["found"], true);
    }

    #[test]
    fn root_given_on_the_command_line_is_shown_but_not_saved() {
        let tmp = tempfile::tempdir().unwrap();
        let cfg = tmp.path().join("config");
        let a = ws(tmp.path(), "alpha");
        let r = ws(tmp.path(), "fixtures");
        Workspaces::new(cfg.clone(), None).add(&a, None).unwrap();
        let w = Workspaces::new(cfg.clone(), Some(r.clone()));
        assert!(same_path(&w.current().unwrap(), &r));
        assert_eq!(w.list().iter().map(|e| (e.name.as_str(), e.saved)).collect::<Vec<_>>(), [("fixtures", false), ("alpha", true)]);
        w.select(&a).unwrap();
        let later = Workspaces::new(cfg, None);
        assert_eq!(later.list().len(), 1, "--root was not written to the settings");
        assert!(same_path(&later.current().unwrap(), &a));
    }

    #[test]
    fn keeps_settings_it_does_not_know_and_the_python_path() {
        let tmp = tempfile::tempdir().unwrap();
        let cfg = tmp.path().join("config");
        std::fs::create_dir_all(&cfg).unwrap();
        std::fs::write(cfg.join("settings.json"), r#"{"future": {"x": 1}, "workspaces": [{"path": ""}, 5]}"#).unwrap();
        let w = Workspaces::new(cfg.clone(), None);
        assert!(w.list().is_empty(), "broken entries are skipped");
        w.set_python("  C:\\Python312\\python.exe ").unwrap();
        let again = Workspaces::new(cfg.clone(), None);
        assert_eq!(again.python().as_deref(), Some("C:\\Python312\\python.exe"));
        assert_eq!(load_settings(&cfg)["future"], json!({"x": 1}));
        again.set_python("").unwrap();
        assert_eq!(Workspaces::new(cfg, None).python(), None);
    }
}
