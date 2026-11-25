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

// ---- Events: what becomes true in any workspace, for notifications and /api/events.

pub const KINDS: [&str; 5] = ["waiting", "decision", "stuck", "finished", "failing"];
pub const KEEP_EVENTS: usize = 200;

/// One thing that became true in a project.
#[derive(Clone, Debug, PartialEq)]
pub struct Event {
    pub id: u64,
    pub at: String,
    pub workspace: PathBuf,
    pub workspace_name: String,
    pub project: String,
    pub kind: &'static str,
    pub key: String,
    pub text: String,
    /// false when its kind is switched off in the settings: listed here, but no system notification
    pub notify: bool,
}

impl Event {
    pub fn to_json(&self) -> Value {
        json!({"id": self.id, "at": self.at, "workspace": self.workspace.to_string_lossy(), "workspace_name": self.workspace_name,
               "project": self.project, "kind": self.kind, "key": self.key, "text": self.text, "notify": self.notify})
    }
}

/// What a project looked like at one look.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Look {
    pub phase: String,
    pub updated: String,
    pub drafts: Vec<String>,
    /// an unanswered wait in Claude Code that needs the human (the page's rule), by its step id
    pub waiting: Option<String>,
    pub permission: bool,
    /// the newest test run (its time and position), and whether it fails where the one before passed
    pub check: Option<String>,
    pub failing: bool,
    pub review_pass: bool,
}

pub fn look(pdir: &Path) -> Look {
    let state = pdir.join("state");
    let st = records::read_obj(&state.join("status.json"));
    let phase = st.get("phase").and_then(|v| v.as_str()).unwrap_or("idle").to_string();
    let updated = st.get("updated").map(py_str).unwrap_or_default();
    // A draft by its id and the time and round it was saved: ids come back (a fix saved again after
    // "continue", or fix-1 in the next /fix run), and each save is a new decision.
    let stamp = |d: &Value| {
        let f = |k: &str| d.get(k).map(py_str).unwrap_or_default();
        format!("{}@{}#{}", d.get("id").map(py_str).unwrap_or_else(|| py_str(d)), f("created"), f("rounds"))
    };
    let mut drafts: Vec<String> = records::drafts(pdir).iter().map(stamp).collect();
    drafts.sort();
    let step = records::read_activity(&state.join("activity.jsonl"), 1).pop();
    let mut waiting = None;
    let mut permission = false;
    if let Some(a) = &step {
        if a.get("kind").and_then(|k| k.as_str()) == Some("waiting") && !opt_truthy(a.get("resolved")) {
            permission = a.get("text").map(py_str).unwrap_or_default().to_lowercase().contains("permission");
            if permission || !(phase == "done" || phase == "idle") {
                waiting = Some(match a.get("tool_use_id").filter(|v| opt_truthy(Some(v))) {
                    Some(id) => py_str(id),
                    None => format!("{}|{}", a.get("ts").map(py_str).unwrap_or_default(), a.get("text").map(py_str).unwrap_or_default()),
                });
            }
        }
    }
    let all = records::read_jsonl(&state.join("check_history.jsonl"), None);
    let passed = |v: &Value| v.get("passed").map(|p| opt_truthy(Some(p))).unwrap_or(false);
    let check = all.last().map(|v| format!("{}#{}", v.get("ran_at").map(py_str).unwrap_or_default(), all.len()));
    let n = all.len();
    let failing = n >= 2 && !passed(&all[n - 1]) && passed(&all[n - 2]);
    let review_pass = records::read_obj(&state.join("review.json")).get("verdict").map(py_str).unwrap_or_default().to_lowercase() == "pass";
    Look { phase, updated, drafts, waiting, permission, check, failing, review_pass }
}

/// What became true between two looks: (kind, key). A key names the change itself (the step id, the
/// draft id, the time of the status or test run), so the same change is never raised twice.
pub fn changes(prev: &Look, now: &Look) -> Vec<(&'static str, String)> {
    let mut out = Vec::new();
    if let Some(w) = &now.waiting {
        if prev.waiting.as_ref() != Some(w) {
            out.push(("waiting", format!("step:{w}")));
        }
    }
    let new_drafts: Vec<&String> = now.drafts.iter().filter(|d| !prev.drafts.contains(d)).collect();
    if !new_drafts.is_empty() {
        out.extend(new_drafts.into_iter().map(|d| ("decision", format!("draft:{d}"))));
    } else if now.phase == "waiting" && prev.phase != "waiting" && !now.drafts.is_empty() {
        out.push(("decision", format!("phase:{}", now.updated)));
    }
    if now.phase == "stuck" && prev.phase != "stuck" {
        out.push(("stuck", format!("phase:{}", now.updated)));
    }
    if now.phase == "done" && prev.phase != "done" && now.review_pass {
        out.push(("finished", format!("phase:{}", now.updated)));
    }
    if now.failing && now.check != prev.check {
        out.push(("failing", format!("run:{}", now.check.clone().unwrap_or_default())));
    }
    out
}

/// The notification's words.
pub fn event_text(kind: &str, project: &str, permission: bool) -> String {
    match kind {
        "waiting" if permission => format!("{project} is waiting for your permission in Claude Code"),
        "waiting" => format!("{project} is waiting for your reply in Claude Code"),
        "decision" => format!("{project} needs your decision on a fix it could not finish"),
        "stuck" => format!("{project} is stuck and needs your help"),
        "finished" => format!("{project} finished its task, and the review approved it"),
        _ => format!("{project}: tests that passed before are failing now"),
    }
}

/// "Now" as an ISO time stamp (UTC).
pub fn now_iso() -> String {
    let secs = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs() as i64).unwrap_or(0);
    let (days, rem) = (secs.div_euclid(86400), secs.rem_euclid(86400));
    let z = days + 719468;
    let era = z.div_euclid(146097);
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = yoe + era * 400 + if m <= 2 { 1 } else { 0 };
    format!("{:04}-{:02}-{:02}T{:02}:{:02}:{:02}Z", y, m, d, rem / 3600, rem % 3600 / 60, rem % 60)
}

/// Remembers each project's last look and every event it raised.
#[derive(Default)]
pub struct Watcher {
    looks: std::collections::HashMap<(PathBuf, String), Look>,
    seen: std::collections::HashSet<String>,
    events: Vec<Event>,
    next_id: u64,
}

impl Watcher {
    /// Look at every project of every workspace once. A project seen for the first time (also at the
    /// start) only gives its first look: what is already true then is not raised.
    pub fn scan(&mut self, workspaces: &[(PathBuf, String)], notify_on: &dyn Fn(&str) -> bool) -> Vec<Event> {
        let mut new = Vec::new();
        for (ws, name) in workspaces {
            let projects = ws.join("projects");
            if !projects.is_dir() {
                continue;
            }
            for p in records::project_names(&projects) {
                let now = look(&projects.join(&p));
                let k = (ws.clone(), p.clone());
                if let Some(prev) = self.looks.get(&k) {
                    for (kind, key) in changes(prev, &now) {
                        let seen = |k: &str| self.seen.contains(&format!("{}|{}|decision|{}", ws.to_string_lossy(), p, k));
                        if kind == "decision" && key.starts_with("phase:") && now.drafts.iter().all(|d| seen(&format!("draft:{d}"))) {
                            // /fix saves the draft first and sets the phase to waiting later: one decision, already raised.
                            continue;
                        }
                        let full = format!("{}|{}|{}|{}", ws.to_string_lossy(), p, kind, key);
                        if !self.seen.insert(full) {
                            continue;
                        }
                        self.next_id += 1;
                        new.push(Event {
                            id: self.next_id, at: now_iso(), workspace: ws.clone(), workspace_name: name.clone(), project: p.clone(),
                            kind, key, text: event_text(kind, &p, now.permission), notify: notify_on(kind),
                        });
                    }
                }
                self.looks.insert(k, now);
            }
        }
        self.events.extend(new.iter().cloned());
        if self.events.len() > KEEP_EVENTS {
            let cut = self.events.len() - KEEP_EVENTS;
            self.events.drain(..cut);
        }
        new
    }

    /// Every event kept, newest first.
    pub fn events_json(&self) -> Value {
        json!({"events": self.events.iter().rev().map(|e| e.to_json()).collect::<Vec<_>>()})
    }
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

    fn copy(src: &Path, dst: &Path) {
        std::fs::create_dir_all(dst).unwrap();
        for e in std::fs::read_dir(src).unwrap() {
            let e = e.unwrap();
            let to = dst.join(e.file_name());
            if e.path().is_dir() {
                copy(&e.path(), &to)
            } else {
                std::fs::copy(e.path(), &to).unwrap();
            }
        }
    }

    fn set_status(pdir: &Path, phase: &str, updated: &str) {
        let v = json!({"phase": phase, "updated": updated, "task": "T"});
        std::fs::write(pdir.join("state").join("status.json"), v.to_string()).unwrap();
    }

    fn append(path: &Path, v: Value) {
        use std::io::Write;
        let mut f = std::fs::OpenOptions::new().create(true).append(true).open(path).unwrap();
        writeln!(f, "{}", v).unwrap();
    }

    #[test]
    fn one_event_per_change_none_at_start_none_twice() {
        let tmp = tempfile::tempdir().unwrap();
        let ws = tmp.path().join("ws");
        copy(&fixtures(), &ws);
        let list = vec![(ws.clone(), "ws".to_string())];
        let mut w = Watcher::default();
        let on = |_: &str| true;
        assert!(w.scan(&list, &on).is_empty(), "states already true at the start are not raised");
        assert!(w.scan(&list, &on).is_empty());
        let p = |n: &str| ws.join("projects").join(n);
        append(&p("api-client").join("state").join("activity.jsonl"),
               json!({"ts": "2026-10-15T10:00:00+02:00", "kind": "waiting", "text": "Waiting for your permission in Claude Code", "tool_use_id": "t77"}));
        set_status(&p("data-pipeline"), "stuck", "2026-10-15T10:01:00+02:00");
        let draft = p("notes-app").join("state").join("drafts").join("fix-9");
        std::fs::create_dir_all(&draft).unwrap();
        std::fs::write(draft.join("meta.json"), json!({"id": "fix-9", "issue": "x"}).to_string()).unwrap();
        set_status(&p("notes-app"), "waiting", "2026-10-15T10:02:00+02:00");
        std::fs::write(p("image-classifier").join("state").join("review.json"), json!({"verdict": "pass"}).to_string()).unwrap();
        set_status(&p("image-classifier"), "done", "2026-10-15T10:03:00+02:00");
        append(&p("example-done").join("state").join("check_history.jsonl"),
               json!({"ran_at": "2026-10-15T10:04:00+02:00", "passed": false, "n_pass": 1, "n_total": 2}));
        let mut got: Vec<(String, &str)> = w.scan(&list, &on).iter().map(|e| (e.project.clone(), e.kind)).collect();
        got.sort();
        assert_eq!(got, [("api-client".to_string(), "waiting"), ("data-pipeline".into(), "stuck"), ("example-done".into(), "failing"),
                         ("image-classifier".into(), "finished"), ("notes-app".into(), "decision")]);
        assert!(w.scan(&list, &on).is_empty(), "nothing twice");
        // Back and forth with the same key is not raised again; a new change is.
        set_status(&p("data-pipeline"), "implementing", "2026-10-15T10:05:00+02:00");
        w.scan(&list, &on);
        set_status(&p("data-pipeline"), "stuck", "2026-10-15T10:01:00+02:00");
        assert!(w.scan(&list, &on).is_empty(), "the same stuck (same time) is not raised twice");
        set_status(&p("data-pipeline"), "implementing", "2026-10-15T10:06:00+02:00");
        w.scan(&list, &on);
        set_status(&p("data-pipeline"), "stuck", "2026-10-15T10:07:00+02:00");
        let off = |k: &str| k != "stuck";
        assert_eq!(w.scan(&list, &off).iter().map(|e| (e.kind, e.notify)).collect::<Vec<_>>(), [("stuck", false)],
                   "a kind switched off is listed without a notification");
        let all = w.events_json();
        assert_eq!(all["events"].as_array().unwrap().len(), 6);
        assert_eq!(all["events"][0]["kind"], "stuck", "newest first");
        assert_eq!(all["events"][0]["text"], "data-pipeline is stuck and needs your help");
    }

    #[test]
    fn waits_that_do_not_need_you_and_answered_waits_raise_nothing() {
        let prev = Look { phase: "implementing".into(), ..Default::default() };
        let idle_reply = Look { phase: "done".into(), ..Default::default() };
        assert!(changes(&prev, &idle_reply).is_empty());
        let now = Look { phase: "implementing".into(), waiting: Some("t1".into()), permission: true, ..Default::default() };
        assert_eq!(changes(&prev, &now), [("waiting", "step:t1".to_string())]);
        assert!(changes(&now, &now).is_empty());
        assert_eq!(event_text("waiting", "web-scraper", true), "web-scraper is waiting for your permission in Claude Code");
        // A phase that becomes waiting with drafts that were already there: one decision event.
        let a = Look { phase: "implementing".into(), drafts: vec!["fix-1".into()], ..Default::default() };
        let b = Look { phase: "waiting".into(), updated: "u".into(), drafts: vec!["fix-1".into()], ..Default::default() };
        assert_eq!(changes(&a, &b), [("decision", "phase:u".to_string())]);
        // Finished only with a passed review.
        let done_fail = Look { phase: "done".into(), review_pass: false, ..Default::default() };
        assert!(changes(&prev, &done_fail).is_empty());
        assert!(now_iso().ends_with('Z') && now_iso().len() == 20);
    }

    #[test]
    fn a_fix_set_aside_is_one_decision_even_when_the_phase_follows_later() {
        // /fix saves the draft first and sets the phase to waiting only after every issue was tried,
        // usually several looks later: that is still one decision.
        let tmp = tempfile::tempdir().unwrap();
        let ws = tmp.path().join("ws");
        copy(&fixtures(), &ws);
        let list = vec![(ws.clone(), "ws".to_string())];
        let mut w = Watcher::default();
        let on = |_: &str| true;
        w.scan(&list, &on);
        let notes = ws.join("projects").join("notes-app");
        let draft = notes.join("state").join("drafts").join("fix-3");
        std::fs::create_dir_all(&draft).unwrap();
        std::fs::write(draft.join("meta.json"), json!({"id": "fix-3"}).to_string()).unwrap();
        assert_eq!(w.scan(&list, &on).iter().map(|e| e.kind).collect::<Vec<_>>(), ["decision"]);
        w.scan(&list, &on);
        set_status(&notes, "waiting", "2026-10-15T11:00:00+02:00");
        assert!(w.scan(&list, &on).is_empty(), "the phase that follows the draft is the same decision");
        // Drafts that were there before the app looked (no event for them yet) still raise one when
        // the phase becomes waiting: parser has fix-1 from the start.
        let parser = ws.join("projects").join("parser");
        set_status(&parser, "implementing", "2026-10-15T11:01:00+02:00");
        w.scan(&list, &on);
        set_status(&parser, "waiting", "2026-10-15T11:02:00+02:00");
        assert_eq!(w.scan(&list, &on).iter().map(|e| (e.project.as_str(), e.kind)).collect::<Vec<_>>(), [("parser", "decision")]);
        // The same id saved again later (after "continue", or fix-1 of the next /fix run) is a new decision, once.
        std::fs::remove_dir_all(&draft).unwrap();
        set_status(&notes, "implementing", "2026-10-15T12:00:00+02:00");
        w.scan(&list, &on);
        std::fs::create_dir_all(&draft).unwrap();
        std::fs::write(draft.join("meta.json"), json!({"id": "fix-3", "created": "2026-10-15T12:30:00+02:00", "rounds": 2}).to_string()).unwrap();
        assert_eq!(w.scan(&list, &on).iter().map(|e| e.kind).collect::<Vec<_>>(), ["decision"], "a draft saved again is a new decision");
        set_status(&notes, "waiting", "2026-10-15T12:31:00+02:00");
        assert!(w.scan(&list, &on).is_empty(), "and its phase change is the same decision");
        // Saved again while the phase stays waiting and the draft set looks the same by id: still new.
        std::fs::write(draft.join("meta.json"), json!({"id": "fix-3", "created": "2026-10-15T13:00:00+02:00", "rounds": 3}).to_string()).unwrap();
        assert_eq!(w.scan(&list, &on).iter().map(|e| e.kind).collect::<Vec<_>>(), ["decision"]);
    }
}
