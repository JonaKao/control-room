//! Why a review rejected work, sorted into a few themes by the words in its one-line summary,
//! and each project's definition of done (DONE.md) to match the themes to.

use std::collections::{BTreeMap, HashMap};
use std::path::Path;
use std::sync::OnceLock;

use regex::Regex;
use serde_json::{json, Map, Value};

use crate::py::{get_str, py_str, py_strip, truthy};
use crate::records::read_text;

/// Each theme: key, plain label, words that point to it, words of a definition-of-done item that
/// covers it (None: no usual item), and what the human could sharpen when it keeps coming back.
pub const REASONS: [(&str, &str, &str, Option<&str>, &str); 9] = [
    ("progress", "The progress note was not updated",
     r"progress(\.md| note)|what is next|what changed", Some(r"progress"),
     "Say in the definition of done that the progress note must say what changed and what is next."),
    ("weakened", "A test was weakened, skipped or removed",
     r"weaken|skip|loosen|disabl|removed (a |the )?(test|check)|threshold", Some(r"weaken|skipp"),
     "Repeat in the project instructions that tests and thresholds must never be loosened."),
    ("coverage", "The task's success was not covered by a test",
     r"not covered|no (test|check) (for|covers)|untested|by hand|manual", Some(r"covered by a check|manual"),
     "Ask in the definition of done for a check that proves the task, written before the change."),
    ("failing", "Tests failed or were not run",
     r"\b(checks?|tests?) (fail|not run|red|broken)|failing (checks?|tests?)", Some(r"check.*pass"),
     "Ask in the project instructions to run every test before asking for a review."),
    ("bug", "A bug in the change",
     r"\bbug|crash|\bwrong\b|incorrect|regress|\brace\b|leak|exception", None,
     "Describe the tricky cases in the project instructions, or add a test for them."),
    ("screens", "Screenshots or plots were not looked at",
     r"screenshot|\bplots?\b|not (opened|inspected)", Some(r"screenshot|plot"),
     "Ask in the definition of done to open and describe the screenshots or plots."),
    ("wording", "Unclear wording or jargon",
     r"jargon|plain (words|language)|wording|internal (terms?|names?)", Some(r"plain language|wording"),
     "Give examples of the wording you want in the project instructions."),
    ("layout", "Layout problems on small screens",
     r"\bphone|mobile|sideways|overflow|layout", Some(r"phone|sideways"),
     "Name the screen sizes that must work in the definition of done."),
    ("scope", "Part of the task was left out",
     r"missing|not implemented|incomplete|does not (do|meet)|not done", None,
     "Write the task with a list of what must be there when it is done."),
];
pub const OTHER: (&str, &str, &str) =
    ("other", "Other reasons", "Read these summaries: if one keeps coming back, add it to the definition of done.");

struct Theme {
    key: &'static str,
    label: &'static str,
    words: Option<Regex>,
    done_words: Option<Regex>,
    advice: &'static str,
}

fn themes() -> &'static Vec<Theme> {
    static T: OnceLock<Vec<Theme>> = OnceLock::new();
    T.get_or_init(|| {
        let ci = |p: &str| Regex::new(&format!("(?i){}", p)).unwrap();
        let mut v: Vec<Theme> = REASONS
            .iter()
            .map(|(k, l, w, d, a)| Theme { key: k, label: l, words: Some(ci(w)), done_words: d.map(ci), advice: a })
            .collect();
        v.push(Theme { key: OTHER.0, label: OTHER.1, words: None, done_words: None, advice: OTHER.2 });
        v
    })
}

/// The checklist items of a project's definition of done (DONE.md), as plain text.
pub fn done_items(pdir: &Path) -> Vec<String> {
    static RE: OnceLock<Regex> = OnceLock::new();
    let re = RE.get_or_init(|| Regex::new(r"(?m)^\s*[-*]\s+\[[ xX]\]\s+(.+)$").unwrap());
    let md = read_text(&pdir.join("DONE.md"));
    re.captures_iter(&md).map(|c| py_strip(&c[1].replace('`', "")).to_string()).collect()
}

/// Failed reviews grouped by theme, most common first ('other' last). `rows` are review history
/// entries (optionally with 'project'); `items` is the definition of done to match each theme to, or,
/// across projects, `items_by_project` gives each project's (then 'covered_in' names the projects whose
/// definition of done already covers the theme). 'rejections' is the number of failed reviews: one
/// summary can name several themes, so the counts may add up to more.
pub fn review_reasons(
    rows: &[Value],
    items: Option<&[String]>,
    items_by_project: Option<&HashMap<String, Vec<String>>>,
) -> Vec<Value> {
    let mut groups: HashMap<&str, Vec<Map<String, Value>>> = HashMap::new();
    let mut rejections = 0usize;
    for r in rows {
        let Some(r) = r.as_object() else { continue };
        if get_str(r, "verdict", "").to_lowercase() != "fail" {
            continue;
        }
        rejections += 1;
        let text = match r.get("summary") {
            Some(v) if truthy(v) => py_str(v),
            _ => String::new(),
        };
        let mut keys: Vec<&str> = themes()
            .iter()
            .filter(|t| t.words.as_ref().map(|w| w.is_match(&text)).unwrap_or(false))
            .map(|t| t.key)
            .collect();
        if keys.is_empty() {
            keys.push(OTHER.0);
        }
        let mut example = Map::new();
        for k in ["at", "summary", "project"] {
            if let Some(v) = r.get(k) {
                example.insert(k.into(), v.clone());
            }
        }
        for k in keys {
            groups.entry(k).or_default().push(example.clone());
        }
    }
    let mut out: Vec<Value> = Vec::new();
    for t in themes() {
        let Some(ex) = groups.get(t.key) else { continue };
        let covers = |its: Option<&[String]>| -> Option<String> {
            let dw = t.done_words.as_ref()?;
            its?.iter().find(|i| dw.is_match(i)).cloned()
        };
        // sorted({e["project"] ...}): a set of the project values, sorted
        let mut projects: BTreeMap<String, Value> = BTreeMap::new();
        for e in ex {
            if let Some(p) = e.get("project") {
                projects.insert(py_str(p), p.clone());
            }
        }
        let covered: Vec<Value> = projects
            .iter()
            .filter(|(k, _)| covers(items_by_project.and_then(|m| m.get(*k)).map(|v| v.as_slice())).is_some())
            .map(|(_, v)| v.clone())
            .collect();
        let examples: Vec<Value> = ex.iter().rev().map(|e| Value::Object(e.clone())).collect();
        out.push(json!({
            "key": t.key, "label": t.label, "count": ex.len(), "advice": t.advice,
            "done_item": covers(items), "covered_in": covered,
            "projects": projects.values().cloned().collect::<Vec<_>>(),
            "rejections": rejections, "examples": examples,
        }));
    }
    // Stable sort: 'other' last, then most common first.
    out.sort_by_key(|g| (g["key"] == OTHER.0, -(g["count"].as_i64().unwrap_or(0))));
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn groups_failed_reviews_most_common_first_other_last() {
        let rows = vec![json!({"at": "1", "verdict": "fail", "summary": "Strange edge in the parser"}),
                        json!({"at": "2", "verdict": "fail", "summary": "progress.md not updated"}),
                        json!({"at": "3", "verdict": "pass", "summary": "progress.md not updated"}),
                        json!({"at": "4", "verdict": "FAIL", "summary": "Bug: crash on empty input; progress note stale"}),
                        json!({"at": "5", "verdict": "fail", "summary": ""})];
        let got: Vec<(String, i64)> = review_reasons(&rows, None, None).iter()
            .map(|g| (g["key"].as_str().unwrap().to_string(), g["count"].as_i64().unwrap())).collect();
        assert_eq!(got, [("progress".into(), 2), ("bug".into(), 1), ("other".into(), 2)]);
        let progress = &review_reasons(&rows, None, None)[0];
        let at: Vec<&str> = progress["examples"].as_array().unwrap().iter().map(|e| e["at"].as_str().unwrap()).collect();
        assert_eq!(at, ["4", "2"]); // newest first
    }

    #[test]
    fn matches_the_definition_of_done() {
        let items = vec!["Every check passes".to_string(), "`state/progress.md` says what changed".to_string()];
        let rows = vec![json!({"verdict": "fail", "summary": "progress note missing"}), json!({"verdict": "fail", "summary": "a race"})];
        let groups = review_reasons(&rows, Some(&items), None);
        let by = |k: &str| groups.iter().find(|g| g["key"] == k).unwrap().clone();
        assert_eq!(by("progress")["done_item"], "`state/progress.md` says what changed");
        assert_eq!(by("bug")["done_item"], Value::Null);
        assert!(truthy(&by("bug")["advice"]));
    }

    #[test]
    fn overlapping_themes_are_counted_per_rejection() {
        let rows = vec![json!({"verdict": "fail", "summary": "progress note missing and a crash"}), json!({"verdict": "fail", "summary": "a race"})];
        assert_eq!(review_reasons(&rows, None, None)[0]["rejections"], 2);
    }

    #[test]
    fn covered_in_names_projects_whose_definition_covers_the_theme() {
        let rows = vec![json!({"verdict": "fail", "summary": "progress note missing", "project": "b"}),
                        json!({"verdict": "fail", "summary": "progress note stale", "project": "a"})];
        let mut items = HashMap::new();
        items.insert("a".to_string(), vec!["The progress note says what is next".to_string()]);
        items.insert("b".to_string(), vec!["Checks pass".to_string()]);
        let g = &review_reasons(&rows, None, Some(&items))[0];
        assert_eq!(g["projects"], json!(["a", "b"]));
        assert_eq!(g["covered_in"], json!(["a"]));
    }

    #[test]
    fn done_items_read_the_checklist() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join("DONE.md"), "# Done\r\n\r\n- [ ] `state/progress.md` says what\r\n* [x] Checks pass \r\nText\n").unwrap();
        assert_eq!(done_items(dir.path()), ["state/progress.md says what", "Checks pass"]);
    }
}
