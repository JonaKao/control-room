//! Reading a project's records folder (`state/`), its plots and its files, the way server.py did.
//! Nothing here writes.

use std::fs;
use std::io::{Read, Seek, SeekFrom};
use std::path::Path;
use std::sync::OnceLock;

use regex::Regex;
use serde_json::{json, Map, Value};

use crate::activity::activity_steps;
use crate::py::{get_str, opt_truthy, py_int, py_strip, round3, universal_newlines};

pub const ACTIVITY_LAST: usize = 30;
pub const TREND_RUNS: usize = 12;
pub const PLOT_EXT: [&str; 6] = [".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp"];

pub fn name_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$").unwrap())
}

/// A JSON file, or `None` when it is missing or broken.
pub fn read_json(path: &Path) -> Option<Value> {
    let bytes = fs::read(path).ok()?;
    let text = String::from_utf8(bytes).ok()?;
    serde_json::from_str(&text).ok()
}

/// `read_json(path, {}) or {}`: a falsy or missing value becomes an empty object.
pub fn read_json_or_empty(path: &Path) -> Value {
    match read_json(path) {
        Some(v) if crate::py::truthy(&v) => v,
        _ => Value::Object(Map::new()),
    }
}

/// The same, as an object (a non-object is treated as empty).
pub fn read_obj(path: &Path) -> Map<String, Value> {
    match read_json_or_empty(path) {
        Value::Object(m) => m,
        _ => Map::new(),
    }
}

pub fn read_text(path: &Path) -> String {
    match fs::read(path) {
        Ok(b) => universal_newlines(&String::from_utf8_lossy(&b)),
        Err(_) => String::new(),
    }
}

/// Every JSON value of a JSON-lines file (the last `last` if given); broken lines are skipped.
pub fn read_jsonl(path: &Path, last: Option<usize>) -> Vec<Value> {
    let text = read_text(path);
    let mut out: Vec<Value> = Vec::new();
    for line in text.split('\n') {
        let line = py_strip(line);
        if line.is_empty() {
            continue;
        }
        if let Ok(v) = serde_json::from_str::<Value>(line) {
            out.push(v);
        }
    }
    match last {
        Some(n) if n > 0 && out.len() > n => out.split_off(out.len() - n),
        _ => out,
    }
}

/// The newest `last` JSON objects of a log that only grows at the end, without reading all of it.
/// Reads backwards in chunks until enough complete lines are found, but never more than `limit`
/// bytes. Broken lines are skipped.
pub fn read_jsonl_tail_with(path: &Path, last: usize, chunk: u64, limit: usize) -> (Vec<Map<String, Value>>, usize) {
    let mut f = match fs::File::open(path) {
        Ok(f) => f,
        Err(_) => return (Vec::new(), 0),
    };
    let mut pos = match f.seek(SeekFrom::End(0)) {
        Ok(p) => p,
        Err(_) => return (Vec::new(), 0),
    };
    let mut buf: Vec<u8> = Vec::new();
    let mut read_total = 0usize;
    while pos > 0 && buf.iter().filter(|&&b| b == b'\n').count() <= last && buf.len() < limit {
        let step = chunk.min(pos);
        pos -= step;
        if f.seek(SeekFrom::Start(pos)).is_err() {
            return (Vec::new(), read_total);
        }
        let mut part = vec![0u8; step as usize];
        if f.read_exact(&mut part).is_err() {
            return (Vec::new(), read_total);
        }
        read_total += part.len();
        part.extend_from_slice(&buf);
        buf = part;
    }
    let mut lines: Vec<&[u8]> = buf.split(|&b| b == b'\n').collect();
    if pos > 0 && !lines.is_empty() {
        lines.remove(0); // the first line may be cut off
    }
    let mut out = Vec::new();
    for line in lines {
        let line = line.strip_prefix(b"\xef\xbb\xbf".as_slice()).unwrap_or(line);
        if let Ok(Value::Object(m)) = serde_json::from_slice::<Value>(line) {
            out.push(m);
        }
    }
    if out.len() > last {
        out = out.split_off(out.len() - last);
    }
    (out, read_total)
}

pub fn read_jsonl_tail(path: &Path, last: usize) -> Vec<Map<String, Value>> {
    read_jsonl_tail_with(path, last, 65536, 262144).0
}

/// The newest `last` steps of the live feed. The log also holds quiet records, so read more.
pub fn read_activity(path: &Path, last: usize) -> Vec<Map<String, Value>> {
    let mut steps = activity_steps(read_jsonl_tail(path, last * 3 + 10));
    if steps.len() > last {
        steps = steps.split_off(steps.len() - last);
    }
    steps
}

pub fn parse_decisions(md: &str) -> Vec<Value> {
    static SPLIT: OnceLock<Regex> = OnceLock::new();
    static HEAD: OnceLock<Regex> = OnceLock::new();
    let split = SPLIT.get_or_init(|| Regex::new(r"(?m)^## ").unwrap());
    let head_re = HEAD.get_or_init(|| Regex::new(r"^(\d{4}-\d{2}-\d{2}):\s*(.*)").unwrap());
    let mut items = Vec::new();
    for block in split.split(md).skip(1) {
        let (head, body) = match block.find('\n') {
            Some(i) => (&block[..i], &block[i + 1..]),
            None => (block, ""),
        };
        let head = py_strip(head);
        let (date, title) = match head_re.captures(head) {
            Some(c) => (c[1].to_string(), c[2].to_string()),
            None => (String::new(), head.to_string()),
        };
        items.push(json!({"date": date, "title": title, "body": py_strip(body)}));
    }
    items
}

pub fn project_names(projects: &Path) -> Vec<String> {
    let mut out: Vec<String> = match fs::read_dir(projects) {
        Ok(rd) => rd
            .filter_map(|e| e.ok())
            .filter_map(|e| e.file_name().into_string().ok())
            .filter(|n| name_re().is_match(n) && projects.join(n).is_dir())
            .collect(),
        Err(_) => Vec::new(),
    };
    out.sort();
    out
}

pub fn drafts(pdir: &Path) -> Vec<Value> {
    let root = pdir.join("state").join("drafts");
    let mut names: Vec<String> = match fs::read_dir(&root) {
        Ok(rd) => rd.filter_map(|e| e.ok()).filter_map(|e| e.file_name().into_string().ok()).collect(),
        Err(_) => return Vec::new(),
    };
    names.sort();
    names
        .into_iter()
        .filter_map(|d| read_json(&root.join(d).join("meta.json")))
        .filter(crate::py::truthy)
        .collect()
}

/// Share of tests passing in each of the latest test runs, oldest first, for the project list.
pub fn trend(pdir: &Path) -> Vec<Value> {
    let mut out = Vec::new();
    for h in read_jsonl(&pdir.join("state").join("check_history.jsonl"), Some(TREND_RUNS)) {
        let Value::Object(h) = h else { continue };
        let int_or_zero = |k: &str| -> Option<i64> {
            match h.get(k) {
                Some(v) if crate::py::truthy(v) => py_int(v),
                _ => Some(0),
            }
        };
        let Some(total) = int_or_zero("n_total") else { continue };
        if total == 0 {
            out.push(json!(0.0));
            continue;
        }
        let Some(pass) = int_or_zero("n_pass") else { continue };
        out.push(json!(round3(pass as f64 / total as f64)));
    }
    out
}

/// How many of the current plan's steps are done (state/plan.json, written by aaf.py plan), or None.
pub fn plan_progress(pdir: &Path) -> Value {
    let Some(Value::Object(p)) = read_json(&pdir.join("state").join("plan.json")) else { return Value::Null };
    let Some(Value::Array(steps)) = p.get("steps") else { return Value::Null };
    if steps.is_empty() {
        return Value::Null;
    }
    let steps: Vec<&Map<String, Value>> = steps.iter().filter_map(|x| x.as_object()).collect();
    let done = steps.iter().filter(|x| opt_truthy(x.get("done_at"))).count();
    let current = steps
        .iter()
        .find(|x| !opt_truthy(x.get("done_at")))
        .map(|x| get_str(x, "text", ""))
        .unwrap_or_default();
    let list: Vec<Value> = steps
        .iter()
        .take(40)
        .map(|x| json!({"text": get_str(x, "text", ""), "done": opt_truthy(x.get("done_at"))}))
        .collect();
    json!({"done": done, "total": steps.len(), "current": current, "task": get_str(&p, "task", ""), "steps": list})
}

/// The project's summary for the project list (server.py summary()).
pub fn summary(pdir: &Path, name: &str) -> Value {
    let state = pdir.join("state");
    let st = read_obj(&state.join("status.json"));
    let ck = read_obj(&state.join("checks.json"));
    let rv = read_obj(&state.join("review.json"));
    let meta = read_obj(&pdir.join("project.json"));
    let checks: Vec<Value> = match ck.get("checks") {
        Some(Value::Array(a)) => a.clone(),
        _ => Vec::new(),
    };
    let passed = checks.iter().filter(|c| c.as_object().map(|c| opt_truthy(c.get("passed"))).unwrap_or(false)).count();
    let get = |m: &Map<String, Value>, k: &str, d: Value| m.get(k).cloned().unwrap_or(d);
    let activity = read_activity(&state.join("activity.jsonl"), 1).pop().map(Value::Object).unwrap_or(Value::Null);
    json!({
        "name": name,
        "description": get(&meta, "description", json!("")),
        "phase": get(&st, "phase", json!("idle")),
        "task": get(&st, "task", json!("")),
        "updated": get(&st, "updated", json!("")),
        "checks_pass": passed,
        "checks_total": checks.len(),
        "verdict": get(&rv, "verdict", Value::Null),
        "drafts": drafts(pdir).len(),
        "activity": activity,
        "trend": trend(pdir),
        "plan": plan_progress(pdir),
    })
}

/// Python's os.path.getmtime: seconds as a float, built the way CPython builds it.
pub fn mtime_float(path: &Path) -> f64 {
    match fs::metadata(path).and_then(|m| m.modified()) {
        Ok(t) => match t.duration_since(std::time::UNIX_EPOCH) {
            Ok(d) => d.as_secs() as f64 + d.subsec_nanos() as f64 * 1e-9,
            Err(e) => {
                let d = e.duration();
                -(d.as_secs() as f64 + d.subsec_nanos() as f64 * 1e-9)
            }
        },
        Err(_) => 0.0,
    }
}

pub fn is_plot(file: &str) -> bool {
    let lower = file.to_lowercase();
    PLOT_EXT.iter().any(|e| lower.ends_with(e))
}

/// The project's plots, newest first.
pub fn plots(pdir: &Path) -> Vec<Value> {
    let dir = pdir.join("plots");
    let mut out: Vec<(String, f64)> = match fs::read_dir(&dir) {
        Ok(rd) => rd
            .filter_map(|e| e.ok())
            .filter_map(|e| e.file_name().into_string().ok())
            .filter(|f| is_plot(f))
            .map(|f| {
                let m = mtime_float(&dir.join(&f));
                (f, m)
            })
            .collect(),
        Err(_) => Vec::new(),
    };
    out.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    out.into_iter().map(|(f, m)| json!({"file": f, "mtime": m})).collect()
}

/// The content type server.py sent for a plot (Python's mimetypes table).
pub fn plot_type(file: &str) -> &'static str {
    let lower = file.to_lowercase();
    if lower.ends_with(".png") {
        "image/png"
    } else if lower.ends_with(".jpg") || lower.ends_with(".jpeg") {
        "image/jpeg"
    } else if lower.ends_with(".svg") {
        "image/svg+xml"
    } else if lower.ends_with(".gif") {
        "image/gif"
    } else if lower.ends_with(".webp") {
        "image/webp"
    } else {
        "application/octet-stream"
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn write(path: &Path, text: &str) {
        let mut f = fs::File::create(path).unwrap();
        f.write_all(text.as_bytes()).unwrap();
    }

    #[test]
    fn tail_returns_the_newest_entries_in_order() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("activity.jsonl");
        let mut text = String::new();
        for i in 0..20000 {
            text.push_str(&format!("{{\"ts\": \"t\", \"kind\": \"read\", \"text\": \"step {} {}\"}}\n", i, "x".repeat(30)));
        }
        write(&path, &text);
        let rows = read_jsonl_tail(&path, 30);
        assert_eq!(rows.len(), 30);
        assert_eq!(rows[29]["text"].as_str().unwrap().split(' ').nth(1), Some("19999"));
        assert_eq!(rows[0]["text"].as_str().unwrap().split(' ').nth(1), Some("19970"));
    }

    #[test]
    fn tail_reads_only_the_end_of_a_big_file() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("activity.jsonl");
        write(&path, &format!("{}\n{{\"kind\": \"edit\", \"text\": \"last\"}}\n", "x".repeat(2_000_000)));
        let (rows, read) = read_jsonl_tail_with(&path, 30, 65536, 262144);
        assert_eq!(rows.len(), 1);
        assert_eq!(Value::Object(rows[0].clone()), json!({"kind": "edit", "text": "last"}));
        assert!(read < 300_000, "read {} bytes of a 2 MB log to get its last line", read);
    }

    #[test]
    fn tail_skips_broken_lines_and_missing_file() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("activity.jsonl");
        write(&path, "{\"kind\": \"read\"}\nnot json\n[\"a list\"]\n{\"kind\": \"edit\"");
        let rows = read_jsonl_tail(&path, 30);
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0]["kind"], "read");
        assert!(read_jsonl_tail(&dir.path().join("missing.jsonl"), 30).is_empty());
    }

    #[test]
    fn feed_keeps_thirty_steps_however_many_quiet_records() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("activity.jsonl");
        let mut text = String::new();
        for i in 0..100 {
            text.push_str(&format!("{{\"ts\": \"{i}\", \"kind\": \"read\", \"text\": \"step {i}\", \"tool_use_id\": \"t{i}\"}}\n"));
            text.push_str(&format!("{{\"ts\": \"{i}\", \"kind\": \"done\", \"text\": \"done\", \"tool_use_id\": \"t{i}\", \"quiet\": true}}\n"));
        }
        write(&path, &text);
        let rows = read_activity(&path, ACTIVITY_LAST);
        assert_eq!(rows.len(), ACTIVITY_LAST);
        assert_eq!(rows[ACTIVITY_LAST - 1]["text"], "step 99");
        assert!(!rows.iter().any(|r| r.contains_key("quiet")));
    }

    #[test]
    fn jsonl_reads_crlf_and_skips_blank_and_broken_lines() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("h.jsonl");
        write(&path, "{\"a\": 1}\r\n\r\nbroken\n[1]\n{\"a\": 2}\n");
        assert_eq!(read_jsonl(&path, None), vec![json!({"a": 1}), json!([1]), json!({"a": 2})]);
        assert_eq!(read_jsonl(&path, Some(1)), vec![json!({"a": 2})]);
    }

    #[test]
    fn decisions_are_split_by_heading() {
        let md = "# Decisions\n\n## 2026-10-01: Use X\n\nBecause.\n\n## No date here\nbody\n";
        let d = parse_decisions(md);
        assert_eq!(d[0], json!({"date": "2026-10-01", "title": "Use X", "body": "Because."}));
        assert_eq!(d[1], json!({"date": "", "title": "No date here", "body": "body"}));
    }

    #[test]
    fn trend_and_plan_follow_server_py() {
        let dir = tempfile::tempdir().unwrap();
        let state = dir.path().join("state");
        fs::create_dir(&state).unwrap();
        write(&state.join("check_history.jsonl"),
              "{\"n_pass\": 2, \"n_total\": 3}\n{\"n_pass\": 1, \"n_total\": 0}\n{\"n_pass\": \"x\", \"n_total\": 2}\n[1]\n{\"n_pass\": null, \"n_total\": \"4\"}\n");
        assert_eq!(trend(dir.path()), vec![json!(0.667), json!(0.0), json!(0.0)]);
        assert_eq!(plan_progress(dir.path()), Value::Null);
        write(&state.join("plan.json"), "{\"task\": \"T\", \"steps\": [{\"text\": \"a\", \"done_at\": \"x\"}, 3, {\"text\": 5}]}");
        assert_eq!(plan_progress(dir.path()), json!({"done": 1, "total": 2, "current": "5", "task": "T",
            "steps": [{"text": "a", "done": true}, {"text": "5", "done": false}]}));
    }

    #[test]
    fn names_refuse_traversal() {
        assert!(name_re().is_match("web-scraper"));
        for bad in ["..", "../..", ".hidden", "a/b", "a\\b", "", "example-done/../parser"] {
            assert!(!name_re().is_match(bad), "{bad}");
        }
    }
}
