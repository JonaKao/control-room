//! Everything derived by the framework's own `framework/aaf.py`: the task timeline (task_stats),
//! the time estimate, and Git (info, files, push, pull). The core never runs `git` itself; it runs
//! aaf.py as a subprocess with Python, and caches the answers the way server.py did.

use std::collections::HashMap;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde_json::{json, Map, Value};
use wait_timeout::ChildExt;

use crate::py::{last_chars, py_str, py_strip, universal_newlines};
use crate::records::read_jsonl;

/// Phases in which the agent is changing files; pulling then would pull the rug from under it.
pub const WORKING: [&str; 5] = ["planning", "implementing", "checking", "reviewing", "fixing"];
pub const STATS_TASKS_EVENTS: usize = 400;
pub const TASK_KEYS: [&str; 9] = ["task", "start", "end", "outcome", "attempts", "first_try", "reviews", "drafts", "times_stuck"];

pub const STATS_CODE: &str = concat!(
    "import importlib.util, json, sys\n",
    "spec = importlib.util.spec_from_file_location('aaf', sys.argv[1])\n",
    "aaf = importlib.util.module_from_spec(spec); spec.loader.exec_module(aaf)\n",
    "print(json.dumps(aaf.task_stats(sys.argv[2])))\n",
);

pub const ESTIMATE_CODE: &str = concat!(
    "import datetime as real, importlib.util, json, sys, types\n",
    "spec = importlib.util.spec_from_file_location('aaf', sys.argv[1])\n",
    "aaf = importlib.util.module_from_spec(spec); spec.loader.exec_module(aaf)\n",
    "aaf.PROJECTS = sys.argv[2]\n",
    "if sys.argv[4]:\n",
    "    at = real.datetime.fromisoformat(sys.argv[4])\n",
    "    class Fixed(real.datetime):\n",
    "        @classmethod\n",
    "        def now(cls, tz=None): return at if tz is None else at.astimezone(tz)\n",
    "    aaf.dt = types.SimpleNamespace(datetime=Fixed, timedelta=real.timedelta,\n",
    "                                   timezone=real.timezone, date=real.date)\n",
    "print(json.dumps({'estimate': aaf.estimate(sys.argv[3]), 'held': aaf._calibration()}))\n",
);

/// What a finished subprocess left: exit code (None: it could not start), stdout, stderr.
#[derive(Clone, Debug)]
pub struct Output {
    pub code: Option<i32>,
    pub out: String,
    pub err: String,
}

/// Runs Python. Tests replace it to count runs or make them fail or slow.
pub trait Runner: Send + Sync {
    /// `python <args...>` in `cwd`, killed after `timeout`.
    fn python(&self, args: &[String], cwd: &Path, timeout: Duration, env: &[(&str, &str)]) -> Output;
    /// "Python 3.12.10 at C:\...\python.exe", or None when no Python 3 was found.
    fn describe(&self) -> Option<String> {
        None
    }
    /// Use this Python from now on (None: look for one).
    fn set_python(&self, _path: Option<String>) {}
}

/// The real runner: finds Python once (the configured path, then python3, python, py -3).
pub struct PythonRunner {
    configured: Mutex<Option<String>>,
    found: Mutex<Option<Option<(Vec<String>, String)>>>,
}

impl PythonRunner {
    pub fn new(configured: Option<String>) -> Self {
        PythonRunner { configured: Mutex::new(configured), found: Mutex::new(None) }
    }

    pub fn set_configured(&self, path: Option<String>) {
        *self.configured.lock().unwrap() = path;
        *self.found.lock().unwrap() = None;
    }

    fn candidates(&self) -> Vec<Vec<String>> {
        let mut c: Vec<Vec<String>> = Vec::new();
        if let Some(p) = self.configured.lock().unwrap().clone().filter(|p| !p.trim().is_empty()) {
            c.push(vec![p]);
        }
        c.push(vec!["python3".into()]);
        c.push(vec!["python".into()]);
        if cfg!(windows) {
            c.push(vec!["py".into(), "-3".into()]);
        }
        c
    }

    /// The command that starts Python 3, and what was found ("Python 3.12.10 at C:\...\python.exe"). A chosen
    /// Python that does not start is skipped (the next one is used), and the description says so.
    pub fn find(&self) -> Option<(Vec<String>, String)> {
        let chosen = self.configured.lock().unwrap().clone().filter(|p| !p.trim().is_empty());
        let mut skipped = false;
        for cand in self.candidates() {
            let mut cmd = Command::new(&cand[0]);
            cmd.args(&cand[1..]).arg("-c").arg("import sys; print('Python %d.%d.%d' % sys.version_info[:3]); print(sys.executable)");
            no_window(&mut cmd);
            let out = run(cmd, Path::new("."), Duration::from_secs(10), &[]);
            if out.code == Some(0) && out.out.starts_with("Python 3.") {
                let mut lines = out.out.lines();
                let version = lines.next().unwrap_or("").to_string();
                let exe = lines.next().unwrap_or("").trim().to_string();
                let mut d = if exe.is_empty() { version } else { format!("{} at {}", version, exe) };
                if skipped {
                    d.push_str(&format!(" (the Python you chose, {}, did not start)", chosen.clone().unwrap_or_default()));
                }
                return Some((cand, d));
            }
            if chosen.as_deref() == Some(cand[0].as_str()) {
                skipped = true;
            }
        }
        None
    }

    fn found(&self) -> Option<(Vec<String>, String)> {
        let mut found = self.found.lock().unwrap();
        if found.is_none() {
            *found = Some(self.find());
        }
        found.clone().unwrap()
    }

    fn command(&self) -> Option<Vec<String>> {
        self.found().map(|(c, _)| c)
    }
}

impl Runner for PythonRunner {
    fn describe(&self) -> Option<String> {
        self.found().map(|(_, d)| d)
    }

    fn set_python(&self, path: Option<String>) {
        self.set_configured(path);
    }

    fn python(&self, args: &[String], cwd: &Path, timeout: Duration, env: &[(&str, &str)]) -> Output {
        let Some(py) = self.command() else {
            return Output { code: None, out: String::new(), err: "Python 3 was not found on this computer".into() };
        };
        let mut cmd = Command::new(&py[0]);
        cmd.args(&py[1..]).args(args);
        no_window(&mut cmd);
        run(cmd, cwd, timeout, env)
    }
}

#[cfg(windows)]
fn no_window(cmd: &mut Command) {
    use std::os::windows::process::CommandExt;
    cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW: no console flashes up from the app
}
#[cfg(not(windows))]
fn no_window(_cmd: &mut Command) {}

/// Run a command with a time limit, reading its output as text (UTF-8, broken bytes replaced,
/// newlines as Python's text mode gives them).
pub fn run(mut cmd: Command, cwd: &Path, timeout: Duration, env: &[(&str, &str)]) -> Output {
    cmd.current_dir(cwd).stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::piped());
    for (k, v) in env {
        cmd.env(k, v);
    }
    let mut child = match cmd.spawn() {
        Ok(c) => c,
        Err(e) => return Output { code: None, out: String::new(), err: e.to_string() },
    };
    let mut so = child.stdout.take().unwrap();
    let mut se = child.stderr.take().unwrap();
    let t_out = std::thread::spawn(move || {
        let mut b = Vec::new();
        let _ = so.read_to_end(&mut b);
        b
    });
    let t_err = std::thread::spawn(move || {
        let mut b = Vec::new();
        let _ = se.read_to_end(&mut b);
        b
    });
    let status = match child.wait_timeout(timeout) {
        Ok(Some(s)) => s,
        _ => {
            let _ = child.kill();
            let _ = child.wait();
            return Output { code: Some(124), out: String::new(), err: format!("timed out after {} s", timeout.as_secs()) };
        }
    };
    let text = |b: Vec<u8>| universal_newlines(&String::from_utf8_lossy(&b));
    Output { code: status.code().or(Some(1)), out: text(t_out.join().unwrap_or_default()), err: text(t_err.join().unwrap_or_default()) }
}

struct GitEntry {
    started: Instant,
    finished: Instant,
    data: Value,
}

type Key = (PathBuf, String);

/// How long derived answers are kept (server.py's GIT_CACHE_S, FILES_CACHE_S, ESTIMATE_CACHE_S).
#[derive(Clone, Copy)]
pub struct CacheTimes {
    pub git: Duration,
    pub files: Duration,
    pub estimate: Duration,
}

impl Default for CacheTimes {
    fn default() -> Self {
        CacheTimes { git: Duration::from_secs(15), files: Duration::from_secs(30), estimate: Duration::from_secs(15) }
    }
}

/// aaf.py, its runner and the caches of what it derived.
pub struct Aaf {
    pub runner: Box<dyn Runner>,
    pub times: Mutex<CacheTimes>,
    /// "now" for the time estimate as an ISO time stamp; None is the real time (checks pin it).
    pub clock: Option<String>,
    /// aaf.py files that derive the timeline and estimate for a workspace without one (the fixtures).
    pub fallback_aaf: Vec<PathBuf>,
    git_cache: Mutex<HashMap<Key, GitEntry>>,
    git_info_locks: Mutex<HashMap<Key, Arc<Mutex<()>>>>,
    git_action_locks: Mutex<HashMap<Key, Arc<Mutex<()>>>>,
    files_cache: Mutex<HashMap<Key, (Instant, Value)>>,
    stats_cache: Mutex<HashMap<Key, (Option<(u64, u128)>, Value)>>,
    estimate_cache: Mutex<HashMap<Key, (Instant, Value)>>,
}

fn key(root: &Path, name: &str) -> Key {
    (root.to_path_buf(), name.to_string())
}

fn arg(p: &Path) -> String {
    p.to_string_lossy().into_owned()
}

/// The nearest folder at or above `start` that holds framework/aaf.py.
pub fn find_workspace(start: &Path) -> Option<PathBuf> {
    let mut d = Some(start);
    while let Some(dir) = d {
        if dir.join("framework").join("aaf.py").is_file() {
            return Some(dir.to_path_buf());
        }
        d = dir.parent();
    }
    None
}

impl Aaf {
    pub fn new(runner: Box<dyn Runner>, clock: Option<String>, fallback_aaf: Vec<PathBuf>) -> Self {
        Aaf {
            runner,
            times: Mutex::new(CacheTimes::default()),
            clock,
            fallback_aaf,
            git_cache: Mutex::new(HashMap::new()),
            git_info_locks: Mutex::new(HashMap::new()),
            git_action_locks: Mutex::new(HashMap::new()),
            files_cache: Mutex::new(HashMap::new()),
            stats_cache: Mutex::new(HashMap::new()),
            estimate_cache: Mutex::new(HashMap::new()),
        }
    }

    fn times(&self) -> CacheTimes {
        *self.times.lock().unwrap()
    }

    /// Run the served workspace's framework/aaf.py.
    pub fn aaf(&self, root: &Path, args: &[&str], timeout: u64) -> Output {
        let path = root.join("framework").join("aaf.py");
        if !path.is_file() {
            return Output { code: None, out: String::new(), err: "framework/aaf.py not found".into() };
        }
        let mut a = vec![arg(&path)];
        a.extend(args.iter().map(|s| s.to_string()));
        self.runner.python(&a, root, Duration::from_secs(timeout), &[("GIT_TERMINAL_PROMPT", "0")])
    }

    /// The aaf.py whose task_stats() derives the task timeline: the served workspace's, or, for a
    /// workspace without one (the fixtures), the one this app was built in or runs from.
    pub fn stats_aaf_path(&self, root: &Path) -> Option<PathBuf> {
        let own = root.join("framework").join("aaf.py");
        if own.is_file() {
            return Some(own);
        }
        self.fallback_aaf.iter().find(|p| p.is_file()).cloned()
    }

    fn stats_run(&self, aaf_path: &Path, pdir: &Path) -> Value {
        let args = vec!["-c".to_string(), STATS_CODE.to_string(), arg(aaf_path), arg(pdir)];
        let out = self.runner.python(&args, pdir, Duration::from_secs(20), &[]);
        let data = if out.code == Some(0) { serde_json::from_str::<Value>(&out.out).ok() } else { None };
        match data {
            Some(Value::Object(mut m)) => {
                m.insert("available".into(), Value::Bool(true));
                Value::Object(m)
            }
            _ => json!({"available": false, "summary": {}, "tasks": [], "error": "could not read the task history"}),
        }
    }

    /// The task timeline, recomputed only when the project's event log changes.
    pub fn task_stats(&self, root: &Path, name: &str) -> Value {
        let pdir = root.join("projects").join(name);
        let events = pdir.join("state").join("events.jsonl");
        let sig = std::fs::metadata(&events).ok().map(|m| {
            let ns = m.modified().ok().and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok()).map(|d| d.as_nanos()).unwrap_or(0);
            (m.len(), ns)
        });
        let Some(aaf_path) = self.stats_aaf_path(root) else {
            return json!({"available": false, "summary": {}, "tasks": [], "events": []});
        };
        if let Some((s, data)) = self.stats_cache.lock().unwrap().get(&key(root, name)) {
            if *s == sig {
                return data.clone();
            }
        }
        let mut data = self.stats_run(&aaf_path, &pdir);
        // The events inside the shown tasks, so the page can say what happened in each segment.
        // Times are compared as times: the log may mix time zone offsets.
        let tasks_len = data.get("tasks").and_then(|t| t.as_array()).map(|a| a.len()).unwrap_or(0);
        let first = if tasks_len > 12 { when(&data["tasks"][tasks_len - 12]["start"]) } else { None };
        let rows: Vec<Value> = read_jsonl(&events, None)
            .into_iter()
            .filter(|e| match first {
                None => true,
                Some(f) => when(e.get("ts").unwrap_or(&Value::Null)).unwrap_or(f) >= f,
            })
            .collect();
        let start = rows.len().saturating_sub(STATS_TASKS_EVENTS);
        let picked: Vec<Value> = rows[start..]
            .iter()
            .map(|e| {
                let mut m = Map::new();
                if let Some(o) = e.as_object() {
                    for k in ["ts", "kind", "text", "verdict", "passed"] {
                        if let Some(v) = o.get(k) {
                            m.insert(k.into(), v.clone());
                        }
                    }
                }
                Value::Object(m)
            })
            .collect();
        data["events"] = Value::Array(picked);
        if data["available"] == Value::Bool(true) {
            // a failed run is tried again on the next request
            self.stats_cache.lock().unwrap().insert(key(root, name), (sig, data.clone()));
        }
        data
    }

    /// aaf.estimate(<project folder>) for the served workspace, plus aaf's calibration as `held`.
    /// Cached briefly like the Git info, a failed run too.
    pub fn estimate(&self, root: &Path, name: &str) -> Value {
        let Some(aaf_path) = self.stats_aaf_path(root) else { return json!({"available": false}) };
        let k = key(root, name);
        if let Some((at, data)) = self.estimate_cache.lock().unwrap().get(&k) {
            if at.elapsed() < self.times().estimate {
                return data.clone();
            }
        }
        let projects = root.join("projects");
        let args = vec![
            "-c".to_string(),
            ESTIMATE_CODE.to_string(),
            arg(&aaf_path),
            arg(&projects),
            arg(&projects.join(name)),
            self.clock.clone().unwrap_or_default(),
        ];
        let out = self.runner.python(&args, root, Duration::from_secs(20), &[]);
        let parsed = if out.code == Some(0) { serde_json::from_str::<Value>(&out.out).ok() } else { None };
        let data = match parsed {
            Some(Value::Object(o)) if o.get("estimate").map(|e| e.is_object()).unwrap_or(false) => {
                let mut m = o["estimate"].as_object().unwrap().clone();
                m.insert("available".into(), Value::Bool(true));
                m.insert("held".into(), o.get("held").cloned().unwrap_or(Value::Null));
                Value::Object(m)
            }
            // kept as briefly as a good answer, so a broken run is not repeated on every poll
            _ => json!({"available": false, "error": "could not work out the estimate"}),
        };
        self.estimate_cache.lock().unwrap().insert(k, (Instant::now(), data.clone()));
        data
    }

    /// `aaf.py git info <name> --fetch`, cached briefly so polling does not hammer GitHub.
    /// Requests arriving while one is running wait for it and share its answer.
    pub fn git_info(&self, root: &Path, name: &str, fresh: bool) -> Value {
        let asked = Instant::now();
        let k = key(root, name);
        let life = self.times().git;
        if let Some(hit) = self.git_cache.lock().unwrap().get(&k) {
            if !fresh && asked.duration_since(hit.finished) < life {
                return hit.data.clone();
            }
        }
        if !root.join("framework").join("aaf.py").is_file() {
            return json!({"available": false, "repo": false});
        }
        let lock = self.git_info_locks.lock().unwrap().entry(k.clone()).or_default().clone();
        let _guard = lock.lock().unwrap();
        if let Some(hit) = self.git_cache.lock().unwrap().get(&k) {
            // A run that started after we asked is always good enough, however long it took.
            // Otherwise a plain request may still use an entry that finished recently; a fresh one may not.
            if hit.started >= asked || (!fresh && hit.finished.elapsed() < life) {
                return hit.data.clone();
            }
        }
        let started = Instant::now(); // a run that began before a push never counts as fresh
        let out = self.aaf(root, &["git", "info", name, "--fetch"], 30);
        let parsed = if out.code == Some(0) { serde_json::from_str::<Value>(&out.out).ok() } else { None };
        let mut data = match parsed {
            Some(Value::Null) | None => json!({"available": true, "repo": false, "error": err_tail(&out, 400)}),
            Some(v) => v,
        };
        if let Value::Object(m) = &mut data {
            m.entry("available").or_insert(Value::Bool(true));
        }
        self.git_cache.lock().unwrap().insert(k, GitEntry { started, finished: Instant::now(), data: data.clone() });
        data
    }

    /// `aaf.py git files <name>` for the change map, cached briefly like the Git info.
    pub fn git_files(&self, root: &Path, name: &str, fresh: bool) -> Value {
        if !root.join("framework").join("aaf.py").is_file() {
            return json!({"available": false, "repo": false, "files": []});
        }
        let k = key(root, name);
        if let Some((at, data)) = self.files_cache.lock().unwrap().get(&k) {
            if !fresh && at.elapsed() < self.times().files {
                return data.clone();
            }
        }
        let out = self.aaf(root, &["git", "files", name], 30);
        let parsed = if out.code == Some(0) { serde_json::from_str::<Value>(&out.out).ok() } else { None };
        match parsed {
            Some(Value::Object(mut m)) => {
                m.insert("available".into(), Value::Bool(true));
                let data = Value::Object(m);
                self.files_cache.lock().unwrap().insert(k, (Instant::now(), data.clone()));
                data
            }
            _ => json!({"available": true, "repo": false, "files": [], "error": err_tail(&out, 400)}),
        }
    }

    /// Push or pull through aaf.py. Returns (http code, result).
    pub fn git_action(&self, root: &Path, name: &str, action: &str) -> (u16, Value) {
        let st = crate::records::read_obj(&root.join("projects").join(name).join("state").join("status.json"));
        let phase = st.get("phase").and_then(|p| p.as_str()).unwrap_or("");
        if action == "pull" && WORKING.contains(&phase) {
            return (409, json!({"ok": false, "message": "The agent is working on this project right now. Pull again once it has finished or stopped."}));
        }
        let k = key(root, name);
        let lock = self.git_action_locks.lock().unwrap().entry(k.clone()).or_default().clone();
        let out = {
            let Ok(_guard) = lock.try_lock() else {
                return (409, json!({"ok": false, "message": "A push or pull for this project is already running."}));
            };
            self.aaf(root, &["git", action, name], 120)
        };
        self.git_cache.lock().unwrap().remove(&k);
        self.files_cache.lock().unwrap().remove(&k);
        let text = py_strip(&format!("{}\n{}", out.out, out.err)).to_string();
        let text = text.strip_prefix("error: ").map(|s| s.to_string()).unwrap_or(text);
        if out.code == Some(0) {
            let msg = if text.is_empty() { if action == "push" { "Pushed.".into() } else { "Pulled.".into() } } else { text };
            return (200, json!({"ok": true, "message": msg}));
        }
        let msg = last_chars(&text, 600);
        (502, json!({"ok": false, "message": if msg.is_empty() { format!("{} failed", action) } else { msg }}))
    }

    /// The task history of every project, for the workspace's track record (server.py TASK_KEYS).
    pub fn task_row(t: &Value) -> Value {
        let mut m = Map::new();
        for k in TASK_KEYS {
            m.insert(k.into(), t.get(k).cloned().unwrap_or(Value::Null));
        }
        Value::Object(m)
    }

    #[cfg(test)]
    pub fn age_estimate(&self, root: &Path, name: &str, by: Duration) {
        if let Some(e) = self.estimate_cache.lock().unwrap().get_mut(&key(root, name)) {
            e.0 -= by;
        }
    }
}

/// `(err or out).strip()[-n:]`
fn err_tail(o: &Output, n: usize) -> String {
    let s = if o.err.is_empty() { &o.out } else { &o.err };
    last_chars(py_strip(s), n)
}

/// An ISO time stamp as microseconds since the epoch, or None (also for a time without a zone,
/// as server.py's _when did). Follows Python's datetime.fromisoformat.
pub fn when(ts: &Value) -> Option<i128> {
    let s = py_str(ts);
    let v = parse_iso(&s)?;
    if v == 0 {
        None // server.py: `_when(x) or first` treats the epoch as missing
    } else {
        Some(v)
    }
}

fn digits(s: &str, n: usize) -> Option<i64> {
    if s.len() >= n && s.as_bytes()[..n].iter().all(|b| b.is_ascii_digit()) {
        s[..n].parse().ok()
    } else {
        None
    }
}

fn days_from_civil(y: i64, m: i64, d: i64) -> i64 {
    let y = if m <= 2 { y - 1 } else { y };
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = y - era * 400;
    let mp = (m + 9) % 12;
    let doy = (153 * mp + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146097 + doe - 719468
}

fn days_in_month(y: i64, m: i64) -> i64 {
    match m {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        _ => if (y % 4 == 0 && y % 100 != 0) || y % 400 == 0 { 29 } else { 28 },
    }
}

/// Parse "HH[:MM[:SS[.f+]]]" or "HH[MM[SS[.f+]]]"; returns microseconds into the day.
fn parse_clock(t: &str) -> Option<i64> {
    let ext = t.len() > 2 && t.as_bytes()[2] == b':';
    let h = digits(t, 2)?;
    let mut rest = &t[2..];
    let mut m = 0;
    let mut s = 0;
    let mut us = 0;
    if !rest.is_empty() {
        if ext {
            rest = rest.strip_prefix(':')?;
        }
        m = digits(rest, 2)?;
        rest = &rest[2..];
        if !rest.is_empty() {
            if ext {
                rest = rest.strip_prefix(':')?;
            }
            s = digits(rest, 2)?;
            rest = &rest[2..];
            if !rest.is_empty() {
                let frac = rest.strip_prefix('.').or_else(|| rest.strip_prefix(','))?;
                if frac.is_empty() || !frac.bytes().all(|b| b.is_ascii_digit()) {
                    return None;
                }
                let mut f6: String = frac.chars().take(6).collect();
                while f6.len() < 6 {
                    f6.push('0');
                }
                us = f6.parse::<i64>().ok()?;
            }
        }
    }
    if h > 24 || m > 59 || s > 59 || (h == 24 && (m, s, us) != (0, 0, 0)) {
        return None;
    }
    Some(((h * 60 + m) * 60 + s) * 1_000_000 + us)
}

fn parse_iso(s: &str) -> Option<i128> {
    if !s.is_ascii() {
        return None;
    }
    // date: YYYY-MM-DD or YYYYMMDD
    let (y, mo, d, rest) = if s.len() >= 10 && s.as_bytes()[4] == b'-' {
        (digits(s, 4)?, digits(&s[5..], 2)?, { if s.as_bytes()[7] != b'-' { return None; } digits(&s[8..], 2)? }, &s[10..])
    } else {
        (digits(s, 4)?, digits(&s[4..], 2)?, digits(&s[6..], 2)?, s.get(8..)?)
    };
    if !(1..=12).contains(&mo) || d < 1 || d > days_in_month(y, mo) || y < 1 {
        return None;
    }
    if rest.is_empty() {
        return None; // a date alone has no time zone
    }
    let time = &rest[1..]; // any one separator
    let tz_at = time.find(|c| c == '+' || c == '-' || c == 'Z' || c == 'z');
    let (clock, tz) = match tz_at {
        Some(i) => (&time[..i], &time[i..]),
        None => return None, // no zone: server.py treats it as unknown
    };
    let us = parse_clock(clock)?;
    let off_us: i64 = if tz == "Z" || tz == "z" {
        0
    } else {
        let sign = if tz.starts_with('-') { -1 } else { 1 };
        let o = &tz[1..];
        let o_ext = o.len() > 2 && o.as_bytes()[2] == b':';
        let oh = digits(o, 2)?;
        let mut r = &o[2..];
        let mut om = 0;
        let mut os = 0;
        let mut ous = 0;
        if !r.is_empty() {
            if o_ext {
                r = r.strip_prefix(':')?;
            }
            om = digits(r, 2)?;
            r = &r[2..];
            if !r.is_empty() {
                if o_ext {
                    r = r.strip_prefix(':')?;
                }
                os = digits(r, 2)?;
                r = &r[2..];
                if !r.is_empty() {
                    let f = r.strip_prefix('.')?;
                    if f.len() != 6 || !f.bytes().all(|b| b.is_ascii_digit()) {
                        return None;
                    }
                    ous = f.parse().ok()?;
                }
            }
        }
        if oh > 23 || om > 59 || os > 59 {
            return None;
        }
        sign * (((oh * 60 + om) * 60 + os) * 1_000_000 + ous)
    };
    let day = days_from_civil(y, mo, d) as i128;
    Some(day * 86_400_000_000 + us as i128 - off_us as i128)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    /// Tests that measure time, and tests that start Python, take turns: run side by side, the
    /// Python starts could delay the 150 ms steps of the timing tests on a busy machine.
    static TURNS: Mutex<()> = Mutex::new(());
    fn turn() -> std::sync::MutexGuard<'static, ()> {
        TURNS.lock().unwrap_or_else(|e| e.into_inner())
    }

    #[test]
    fn iso_times_compare_across_offsets() {
        let a = when(&json!("2026-10-14T09:30:00+01:00")).unwrap();
        let b = when(&json!("2026-10-14T10:30:00+02:00")).unwrap();
        assert_eq!(a, b);
        assert!(when(&json!("2026-10-14T10:00:00+02:00")).unwrap() < a);
        assert_eq!(when(&json!("2026-10-14T08:30:00Z")), Some(a));
        assert_eq!(when(&json!("2026-10-14T08:30:00.5+00:00")).unwrap() - a, 500_000);
        assert_eq!(when(&json!("1970-01-01T00:00:00+00:00")), None);
        assert_eq!(when(&json!("2026-10-14T10:00:00")), None); // no zone
        assert_eq!(when(&json!("2026-10-14")), None);
        assert_eq!(when(&json!("yesterday")), None);
        assert_eq!(when(&json!(null)), None);
        assert_eq!(when(&json!("2026-02-30T10:00:00+00:00")), None);
        assert_eq!(when(&json!("20261014T083000+0000")), Some(a));
    }

    /// A runner that answers from a closure and counts its runs.
    pub struct Fake<F: Fn(&[String]) -> Output + Send + Sync> {
        pub f: F,
        pub calls: Arc<AtomicUsize>,
    }
    impl<F: Fn(&[String]) -> Output + Send + Sync> Runner for Fake<F> {
        fn python(&self, args: &[String], _cwd: &Path, _t: Duration, _env: &[(&str, &str)]) -> Output {
            self.calls.fetch_add(1, Ordering::SeqCst);
            (self.f)(args)
        }
    }

    fn ok(s: &str) -> Output {
        Output { code: Some(0), out: s.into(), err: String::new() }
    }

    fn workspace() -> tempfile::TempDir {
        let dir = tempfile::tempdir().unwrap();
        std::fs::create_dir_all(dir.path().join("framework")).unwrap();
        std::fs::write(dir.path().join("framework").join("aaf.py"), "# stand-in\n").unwrap();
        std::fs::create_dir_all(dir.path().join("projects").join("p").join("state")).unwrap();
        dir
    }

    fn fake<F: Fn(&[String]) -> Output + Send + Sync + 'static>(f: F) -> (Aaf, Arc<AtomicUsize>) {
        let calls = Arc::new(AtomicUsize::new(0));
        (Aaf::new(Box::new(Fake { f, calls: calls.clone() }), None, vec![]), calls)
    }

    #[test]
    fn failed_estimate_is_cached_briefly_not_retried_on_every_poll() {
        let ws = workspace();
        let (a, calls) = fake(|_| Output { code: Some(1), out: String::new(), err: "boom".into() });
        let first = a.estimate(ws.path(), "p");
        let second = a.estimate(ws.path(), "p");
        assert_eq!(first, json!({"available": false, "error": "could not work out the estimate"}));
        assert_eq!(second, first);
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        a.age_estimate(ws.path(), "p", Duration::from_secs(16));
        a.estimate(ws.path(), "p");
        assert_eq!(calls.load(Ordering::SeqCst), 2, "after the cache time: run again");
    }

    #[test]
    fn estimate_carries_available_and_held() {
        let ws = workspace();
        let (a, _) = fake(|args| {
            assert_eq!(args[0], "-c");
            assert_eq!(args[1], ESTIMATE_CODE);
            ok("{\"estimate\": {\"active\": true}, \"held\": {\"coverage\": 0.7}}")
        });
        assert_eq!(a.estimate(ws.path(), "p"), json!({"active": true, "available": true, "held": {"coverage": 0.7}}));
    }

    #[test]
    fn unavailable_without_aaf() {
        let dir = tempfile::tempdir().unwrap();
        let (a, calls) = fake(|_| ok("{}"));
        assert_eq!(a.estimate(dir.path(), "p"), json!({"available": false}));
        assert_eq!(a.task_stats(dir.path(), "p"), json!({"available": false, "summary": {}, "tasks": [], "events": []}));
        assert_eq!(a.git_info(dir.path(), "p", false), json!({"available": false, "repo": false}));
        assert_eq!(a.git_files(dir.path(), "p", false), json!({"available": false, "repo": false, "files": []}));
        assert_eq!(calls.load(Ordering::SeqCst), 0);
    }

    #[test]
    fn stats_cached_until_the_event_log_changes_and_failures_retried() {
        let ws = workspace();
        let events = ws.path().join("projects/p/state/events.jsonl");
        std::fs::write(&events, "{\"ts\": \"2026-10-14T10:00:00+02:00\", \"kind\": \"status\", \"text\": \"Planning: A\"}\n").unwrap();
        let n = Arc::new(AtomicUsize::new(0));
        let n2 = n.clone();
        let (a, calls) = fake(move |_| {
            if n2.fetch_add(1, Ordering::SeqCst) == 0 { Output { code: Some(1), out: String::new(), err: String::new() } }
            else { ok("{\"summary\": {}, \"tasks\": []}") }
        });
        let d = a.task_stats(ws.path(), "p");
        assert_eq!(d["available"], false, "the first run fails");
        assert_eq!(d["events"].as_array().unwrap().len(), 1);
        assert_eq!(a.task_stats(ws.path(), "p")["available"], true, "a failed run is tried again");
        a.task_stats(ws.path(), "p");
        assert_eq!(calls.load(Ordering::SeqCst), 2, "cached while the log is unchanged");
        std::fs::write(&events, "{\"ts\": \"2026-10-14T10:00:00+02:00\", \"kind\": \"status\", \"text\": \"Planning: A\"}\n{\"ts\": \"x\"}\n").unwrap();
        a.task_stats(ws.path(), "p");
        assert_eq!(calls.load(Ordering::SeqCst), 3, "the log changed");
    }

    #[test]
    fn stats_events_filtered_by_time_not_text() {
        let ws = workspace();
        let mut ev = String::new();
        let mut tasks = Vec::new();
        for h in 0..13 {
            let ts = format!("2026-10-14T{:02}:00:00+02:00", 9 + h);
            ev.push_str(&format!("{{\"ts\": \"{ts}\", \"kind\": \"status\", \"text\": \"Planning: T{h}\"}}\n"));
            if h == 1 {
                ev.push_str("{\"ts\": \"2026-10-14T09:30:00+01:00\", \"kind\": \"decision\", \"text\": \"Mixed offset\"}\n");
            }
            tasks.push(json!({"task": format!("T{h}"), "start": ts}));
        }
        std::fs::write(ws.path().join("projects/p/state/events.jsonl"), ev).unwrap();
        let answer = json!({"summary": {}, "tasks": tasks}).to_string();
        let (a, _) = fake(move |_| ok(&answer));
        let d = a.task_stats(ws.path(), "p");
        let texts: Vec<&str> = d["events"].as_array().unwrap().iter().map(|e| e["text"].as_str().unwrap()).collect();
        assert!(texts.contains(&"Mixed offset"));
        assert!(!texts.contains(&"Planning: T0"));
    }

    #[test]
    fn files_cached_unless_fresh_and_failures_not_cached() {
        let ws = workspace();
        let (a, calls) = fake(|args| {
            assert_eq!(&args[1..], ["git", "files", "p"]);
            ok("{\"repo\": true, \"files\": []}")
        });
        assert_eq!(a.git_files(ws.path(), "p", false), json!({"repo": true, "files": [], "available": true}));
        a.git_files(ws.path(), "p", false);
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        a.git_files(ws.path(), "p", true);
        assert_eq!(calls.load(Ordering::SeqCst), 2);
        let (b, calls) = fake(|_| Output { code: Some(2), out: String::new(), err: "  not a repo \n".into() });
        assert_eq!(b.git_files(ws.path(), "p", false), json!({"available": true, "repo": false, "files": [], "error": "not a repo"}));
        b.git_files(ws.path(), "p", false);
        assert_eq!(calls.load(Ordering::SeqCst), 2);
    }

    #[test]
    fn failed_git_info_is_cached_too() {
        let ws = workspace();
        let (a, calls) = fake(|_| Output { code: Some(1), out: "out".into(), err: String::new() });
        assert_eq!(a.git_info(ws.path(), "p", false), json!({"available": true, "repo": false, "error": "out"}));
        a.git_info(ws.path(), "p", false);
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }

    fn slow(sleep_ms: u64) -> (Arc<Aaf>, Arc<AtomicUsize>, tempfile::TempDir) {
        let ws = workspace();
        let counter = Arc::new(AtomicUsize::new(0));
        let c2 = counter.clone();
        let (a, calls) = fake(move |_| {
            let n = c2.fetch_add(1, Ordering::SeqCst) + 1;
            std::thread::sleep(Duration::from_millis(sleep_ms));
            ok(&format!("{{\"repo\": false, \"run\": {n}}}"))
        });
        (Arc::new(a), calls, ws)
    }

    fn ask(a: &Arc<Aaf>, root: &Path, fresh: bool, delay_ms: u64) -> std::thread::JoinHandle<Value> {
        let a = a.clone();
        let root = root.to_path_buf();
        std::thread::spawn(move || {
            std::thread::sleep(Duration::from_millis(delay_ms));
            a.git_info(&root, "p", fresh)
        })
    }

    #[test]
    fn concurrent_git_info_requests_run_aaf_once() {
        let _turn = turn();
        let (a, calls, ws) = slow(500);
        let hs: Vec<_> = (0..5).map(|_| ask(&a, ws.path(), false, 0)).collect();
        for h in hs {
            h.join().unwrap();
        }
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn fetch_slower_than_cache_life_still_runs_once() {
        let _turn = turn();
        let (a, calls, ws) = slow(500);
        a.times.lock().unwrap().git = Duration::from_millis(200);
        let started = Instant::now();
        let hs: Vec<_> = (0..5).map(|_| ask(&a, ws.path(), false, 0)).collect();
        for h in hs {
            h.join().unwrap();
        }
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert!(started.elapsed() < Duration::from_millis(1500), "waiting requests were served one after another");
    }

    #[test]
    fn fresh_request_does_not_reuse_a_run_that_started_before_it() {
        let _turn = turn();
        let (a, calls, ws) = slow(500);
        let first = ask(&a, ws.path(), false, 0);
        let second = ask(&a, ws.path(), true, 150);
        assert_eq!(first.join().unwrap()["run"], 1);
        assert_eq!(second.join().unwrap()["run"], 2, "fresh request got data fetched before it asked");
        assert_eq!(calls.load(Ordering::SeqCst), 2);
    }

    #[test]
    fn fresh_request_reuses_a_run_that_started_after_it() {
        let _turn = turn();
        let (a, calls, ws) = slow(500);
        let x = ask(&a, ws.path(), false, 0);
        let y = ask(&a, ws.path(), true, 150);
        let z = ask(&a, ws.path(), true, 250);
        x.join().unwrap();
        assert_eq!(y.join().unwrap()["run"], 2);
        assert_eq!(z.join().unwrap()["run"], 2);
        assert_eq!(calls.load(Ordering::SeqCst), 2, "fresh requests waiting together should share one run");
    }

    #[test]
    fn pull_refused_while_working_and_one_action_at_a_time() {
        let _turn = turn();
        let ws = workspace();
        std::fs::write(ws.path().join("projects/p/state/status.json"), "{\"phase\": \"checking\"}").unwrap();
        let (a, calls) = fake(|_| ok(""));
        let (code, body) = a.git_action(ws.path(), "p", "pull");
        assert_eq!(code, 409);
        assert_eq!(body["ok"], false);
        assert_eq!(calls.load(Ordering::SeqCst), 0);
        let (code, body) = a.git_action(ws.path(), "p", "push");
        assert_eq!((code, body), (200, json!({"ok": true, "message": "Pushed."})));

        let (b, _) = fake(|_| Output { code: Some(1), out: String::new(), err: "error: rejected\nerror: again".into() });
        let (code, body) = b.git_action(ws.path(), "p", "push");
        assert_eq!(code, 502);
        assert_eq!(body["message"], "rejected\nerror: again");

        let (s, _, ws2) = slow(400);
        let s2 = s.clone();
        let root = ws2.path().to_path_buf();
        let h = std::thread::spawn(move || s2.git_action(&root, "p", "push"));
        std::thread::sleep(Duration::from_millis(100));
        assert_eq!(s.git_action(ws2.path(), "p", "push").0, 409, "a second push while one runs");
        assert_eq!(h.join().unwrap().0, 200);
    }

    #[test]
    fn a_chosen_python_that_does_not_start_is_said() {
        let _turn = turn();
        let r = PythonRunner::new(Some("C:/no/such/python.exe".into()));
        if let Some((_, d)) = r.find() {
            assert!(d.starts_with("Python 3.") && d.contains("did not start") && d.contains("C:/no/such/python.exe"), "{d}");
        }
        let plain = PythonRunner::new(None);
        if let Some((_, d)) = plain.find() {
            assert!(!d.contains("did not start"), "{d}");
        }
    }

    #[test]
    fn python_snippets_compile() {
        let _turn = turn();
        assert!(ESTIMATE_CODE.contains("\n    at = real.datetime"), "indentation kept");
        let r = PythonRunner::new(None);
        if r.find().is_none() {
            return; // no Python on this machine: nothing to compile with
        }
        for code in [STATS_CODE, ESTIMATE_CODE] {
            let args = vec!["-c".to_string(), "import sys; compile(sys.argv[1], 'x', 'exec')".to_string(), code.to_string()];
            let o = r.python(&args, Path::new("."), Duration::from_secs(20), &[]);
            assert_eq!(o.code, Some(0), "{}", o.err);
        }
    }

    #[test]
    fn subprocess_time_limit() {
        let _turn = turn();
        let mut cmd = if cfg!(windows) { let mut c = Command::new("cmd"); c.args(["/C", "ping -n 5 127.0.0.1 >NUL"]); c }
                      else { let mut c = Command::new("sleep"); c.arg("5"); c };
        cmd.stdout(Stdio::piped());
        let t = Instant::now();
        let o = run(cmd, Path::new("."), Duration::from_secs(1), &[]);
        assert_eq!(o.code, Some(124));
        assert!(t.elapsed() < Duration::from_secs(4));
    }
}
