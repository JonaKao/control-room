//! Watching every workspace, also those not shown: how many projects need the human (for the tray),
//! with the same reading code as the page.

use std::path::{Path, PathBuf};

use serde_json::{json, Value};

use crate::py::{opt_truthy, py_str};
use crate::records;
use crate::workspaces::Workspaces;

/// Does this project need the human? The page's rule (index.html `toneOf`): the phase is `waiting`
/// (a fix waits for a decision) or `stuck`, or the newest step is an unanswered wait in Claude Code
/// that asks for permission, or any unanswered wait while a task is under way (not done or idle).
pub fn needs_you(summary: &Value) -> bool {
    let phase = summary.get("phase").and_then(|p| p.as_str()).unwrap_or("idle");
    if phase == "waiting" || phase == "stuck" {
        return true;
    }
    let Some(a) = summary.get("activity").and_then(|a| a.as_object()) else { return false };
    if a.get("kind").and_then(|k| k.as_str()) != Some("waiting") || opt_truthy(a.get("resolved")) {
        return false;
    }
    let asks_permission = a.get("text").map(py_str).unwrap_or_default().to_lowercase().contains("permission");
    asks_permission || !(phase == "done" || phase == "idle")
}

/// The projects of a workspace that need the human, by name.
pub fn needing(root: &Path) -> Vec<String> {
    let projects = root.join("projects");
    records::project_names(&projects)
        .into_iter()
        .filter(|n| needs_you(&records::summary(&projects.join(n), n)))
        .collect()
}

/// One workspace in the tray menu.
#[derive(Clone, Debug, PartialEq)]
pub struct WsCount {
    pub path: PathBuf,
    pub name: String,
    pub found: bool,
    pub needs: usize,
}

/// Every workspace of the list with how many of its projects need the human.
pub fn counts(ws: &Workspaces) -> Vec<WsCount> {
    ws.list()
        .into_iter()
        .map(|e| {
            let found = e.path.join("projects").is_dir();
            let needs = if found { needing(&e.path).len() } else { 0 };
            WsCount { path: e.path, name: e.name, found, needs }
        })
        .collect()
}

/// What the tray shows: its menu (id, label) and whether the icon carries the dot.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct TrayModel {
    pub items: Vec<(String, String)>,
    pub total: usize,
    pub dot: bool,
}

pub const OPEN: &str = "open";
pub const QUIT: &str = "quit";
pub const WS_PREFIX: &str = "ws:";

pub fn tray_model(counts: &[WsCount]) -> TrayModel {
    let mut items = vec![(OPEN.to_string(), "Open Agent Control Room".to_string())];
    for (i, c) in counts.iter().enumerate() {
        let state = if !c.found {
            "folder not found".to_string()
        } else if c.needs == 0 {
            "nothing needs you".to_string()
        } else {
            format!("{} need{} you", c.needs, if c.needs == 1 { "s" } else { "" })
        };
        items.push((format!("{}{}", WS_PREFIX, i), format!("{} — {}", c.name, state)));
    }
    items.push((QUIT.to_string(), "Quit".to_string()));
    let total: usize = counts.iter().map(|c| c.needs).sum();
    TrayModel { items, total, dot: total > 0 }
}

/// The tooltip of the tray icon.
pub fn tooltip(m: &TrayModel) -> String {
    match m.total {
        0 => "Agent Control Room: nothing needs you".to_string(),
        1 => "Agent Control Room: 1 project needs you".to_string(),
        n => format!("Agent Control Room: {} projects need you", n),
    }
}

pub fn tray_json(m: &TrayModel) -> Value {
    json!({"items": m.items.iter().map(|(id, label)| json!({"id": id, "label": label})).collect::<Vec<_>>(),
           "total": m.total, "dot": m.dot, "tooltip": tooltip(m)})
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixtures() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("..").join("fixtures").join("workspace")
    }

    #[test]
    fn the_page_rule_for_needs_you() {
        assert!(needs_you(&json!({"phase": "waiting"})));
        assert!(needs_you(&json!({"phase": "stuck", "activity": null})));
        assert!(!needs_you(&json!({"phase": "implementing", "activity": {"kind": "read"}})));
        let ask = |phase: &str, text: &str, resolved: bool| {
            let mut a = json!({"kind": "waiting", "text": text});
            if resolved {
                a["resolved"] = json!("done");
            }
            needs_you(&json!({"phase": phase, "activity": a}))
        };
        assert!(ask("implementing", "Waiting for your reply in Claude Code", false));
        assert!(ask("done", "Waiting for your PERMISSION in Claude Code", false), "a permission prompt always needs you");
        assert!(!ask("done", "Waiting for your reply in Claude Code", false), "idle after a finished task");
        assert!(!ask("idle", "Waiting for your reply in Claude Code", false));
        assert!(!ask("implementing", "Waiting for your permission in Claude Code", true), "answered");
        assert!(!needs_you(&json!({})));
    }

    #[test]
    fn fixtures_have_three_projects_that_need_you() {
        // parser waits for a decision, scheduler is stuck, web-scraper waits for permission (as the page's rail says).
        let mut got = needing(&fixtures());
        got.sort();
        assert_eq!(got, ["parser", "scheduler", "web-scraper"]);
    }

    #[test]
    fn tray_menu_and_dot_follow_the_count() {
        let c = |name: &str, found: bool, needs: usize| WsCount { path: PathBuf::from(name), name: name.into(), found, needs };
        let m = tray_model(&[c("Main", true, 3), c("Lab", true, 0), c("Old", false, 0)]);
        let labels: Vec<&str> = m.items.iter().map(|(_, l)| l.as_str()).collect();
        assert_eq!(labels, ["Open Agent Control Room", "Main — 3 need you", "Lab — nothing needs you", "Old — folder not found", "Quit"]);
        assert_eq!(m.items[1].0, "ws:0");
        assert!(m.dot);
        assert_eq!(tray_model(&[c("Main", true, 1)]).items[1].1, "Main — 1 needs you");
        let calm = tray_model(&[c("Main", true, 0)]);
        assert!(!calm.dot && calm.total == 0, "no dot while nothing needs you");
        assert!(!tray_model(&[]).dot);
        assert_eq!(tooltip(&m), "Agent Control Room: 3 projects need you");
    }
}
