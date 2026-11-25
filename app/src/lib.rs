//! The Agent Control Room's core: reads every project's records in a workspace and answers the
//! page's questions. One router (`api`) answers them, reached two ways: over HTTP on 127.0.0.1 in
//! `control-room serve` (for the checks and CI), and inside the app window without a network port.
//!
//! The core never writes project files. Its one change to a project is Git push and pull, through
//! `framework/aaf.py git push|pull`, never `git` itself.

pub mod aaf;
pub mod activity;
pub mod api;
pub mod desktop;
pub mod py;
pub mod reasons;
pub mod watch;
pub mod records;
pub mod workspaces;

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use serde_json::{json, Map, Value};

use crate::aaf::Aaf;
use crate::records as rec;

/// The core: the workspace list (one shown at a time), and aaf.py with its caches.
pub struct Core {
    pub workspaces: workspaces::Workspaces,
    /// The app window has a system folder picker; `serve` has not.
    pub can_pick: bool,
    pub aaf: Aaf,
    pub config: PathBuf,
}

/// Where to look for an aaf.py that derives the timeline for a workspace without one (the fixtures):
/// the workspace this program runs from, or the one it was built in.
pub fn fallback_aaf() -> Vec<PathBuf> {
    let mut out = Vec::new();
    if let Ok(exe) = std::env::current_exe() {
        if let Some(ws) = exe.parent().and_then(aaf::find_workspace) {
            out.push(ws.join("framework").join("aaf.py"));
        }
    }
    if let Some(ws) = aaf::find_workspace(Path::new(env!("CARGO_MANIFEST_DIR"))) {
        out.push(ws.join("framework").join("aaf.py"));
    }
    out
}

impl Core {
    /// A core showing `root` for this run (as `--root` does), with settings in `config`.
    pub fn new(root: PathBuf, aaf: Aaf, config: PathBuf) -> Self {
        Self::with_workspaces(Some(root), aaf, config)
    }

    /// A core showing the workspaces of the settings in `config`, and `root` first if given.
    pub fn with_workspaces(root: Option<PathBuf>, aaf: Aaf, config: PathBuf) -> Self {
        let workspaces = workspaces::Workspaces::new(config.clone(), root.map(|r| absolute(&r)));
        Core { workspaces, can_pick: false, aaf, config }
    }

    /// The workspace shown now. With none (first start), an empty folder name that holds no projects.
    pub fn root(&self) -> PathBuf {
        self.workspaces.current().unwrap_or_default()
    }

    pub fn projects_dir(&self) -> PathBuf {
        self.root().join("projects")
    }

    pub fn project_names(&self) -> Vec<String> {
        if self.workspaces.current().is_none() {
            return Vec::new(); // never the projects folder of wherever the program happens to run
        }
        rec::project_names(&self.projects_dir())
    }

    pub fn summary(&self, name: &str) -> Value {
        rec::summary(&self.projects_dir().join(name), name)
    }

    /// The project's track record: its review history and why reviews rejected work.
    pub fn record(&self, name: &str) -> Value {
        let pdir = self.projects_dir().join(name);
        let rows = rec::read_jsonl(&pdir.join("state").join("review_history.jsonl"), None);
        let items = reasons::done_items(&pdir);
        let start = rows.len().saturating_sub(200);
        json!({"reviews": rows[start..].to_vec(), "reasons": reasons::review_reasons(&rows, Some(&items), None)})
    }

    /// Everything the page shows for one project (server.py detail()).
    pub fn detail(&self, name: &str) -> Value {
        let root = self.root();
        let pdir = root.join("projects").join(name);
        let state = pdir.join("state");
        let mut m = Map::new();
        m.insert("summary".into(), rec::summary(&pdir, name));
        m.insert("meta".into(), rec::read_json_or_empty(&pdir.join("project.json")));
        m.insert("status".into(), rec::read_json_or_empty(&state.join("status.json")));
        m.insert("checks".into(), rec::read_json(&state.join("checks.json")).unwrap_or(Value::Null));
        m.insert("check_history".into(), Value::Array(rec::read_jsonl(&state.join("check_history.jsonl"), Some(40))));
        m.insert("review".into(), rec::read_json(&state.join("review.json")).unwrap_or(Value::Null));
        m.insert("decisions".into(), Value::Array(rec::parse_decisions(&rec::read_text(&state.join("decisions.md")))));
        m.insert("progress".into(), Value::String(rec::read_text(&state.join("progress.md"))));
        m.insert("events".into(), Value::Array(rec::read_jsonl(&state.join("events.jsonl"), Some(60))));
        m.insert(
            "activity".into(),
            Value::Array(rec::read_activity(&state.join("activity.jsonl"), rec::ACTIVITY_LAST).into_iter().map(Value::Object).collect()),
        );
        m.insert("plots".into(), Value::Array(rec::plots(&pdir)));
        m.insert("tasks".into(), self.aaf.task_stats(&root, name));
        m.insert("record".into(), self.record(name));
        m.insert("estimate".into(), self.aaf.estimate(&root, name));
        m.insert("drafts".into(), Value::Array(rec::drafts(&pdir)));
        m.insert("discarded".into(), Value::Array(rec::read_jsonl(&state.join("discarded_drafts.jsonl"), Some(20))));
        Value::Object(m)
    }

    /// Every project's track record side by side, and the most common reasons across all of them.
    pub fn workspace_record(&self) -> Value {
        let root = self.root();
        let available = self.aaf.stats_aaf_path(&root).is_some();
        let mut projects = Vec::new();
        let mut rows = Vec::new();
        let mut items: HashMap<String, Vec<String>> = HashMap::new();
        for name in self.project_names() {
            let pdir = root.join("projects").join(&name);
            let st = self.aaf.task_stats(&root, &name);
            for r in rec::read_jsonl(&pdir.join("state").join("review_history.jsonl"), None) {
                if let Value::Object(mut m) = r {
                    m.insert("project".into(), Value::String(name.clone()));
                    rows.push(Value::Object(m));
                }
            }
            let summary = match st.get("summary") {
                Some(v) if py::truthy(v) => v.clone(),
                _ => json!({}),
            };
            let tasks: Vec<Value> = match st.get("tasks") {
                Some(Value::Array(a)) => a.iter().map(Aaf::task_row).collect(),
                _ => Vec::new(),
            };
            items.insert(name.clone(), reasons::done_items(&pdir));
            projects.push(json!({"name": name, "summary": summary, "tasks": tasks}));
        }
        json!({"available": available, "projects": projects, "reasons": reasons::review_reasons(&rows, None, Some(&items))})
    }
}

fn absolute(p: &Path) -> PathBuf {
    std::path::absolute(p).unwrap_or_else(|_| p.to_path_buf())
}
