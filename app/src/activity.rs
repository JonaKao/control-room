//! The steps of the live feed, from the hook's records (framework/hooks/activity.py).
//!
//! Records marked quiet ("done": a step finished) are not steps. A "waiting" step is marked
//! resolved, with what resolved it and when, once a later record shows the human answered:
//! "done" or "error" for the same tool_use_id (the permission was granted and the step ran),
//! "you" (the human sent a message) or the next step by the same agent ("step"). Notes, turn
//! ends, other agents' steps and other steps' errors are no answer. Claude Code logs a permission
//! prompt twice, with and without its tool_use_id, in either order: that is one wait. A wait
//! without an id is resolved along with the waits that have one.

use serde_json::{Map, Value};

use crate::py::{is_str, opt_eq, opt_truthy, py_str};

type Row = Map<String, Value>;

fn permission(r: &Row) -> bool {
    r.get("text").map(py_str).unwrap_or_default().to_lowercase().contains("permission")
}

/// Mark the waits at `idx` (indices into `steps`) as answered and drop them from `pending`.
fn answer(steps: &mut [Row], pending: &mut Vec<usize>, idx: &[usize], how: &str, ts: Option<&Value>) {
    for &i in idx {
        steps[i].insert("resolved".into(), Value::String(how.into()));
        steps[i].insert("resolved_ts".into(), ts.cloned().unwrap_or(Value::Null));
    }
    pending.retain(|p| !idx.contains(p));
}

pub fn activity_steps(rows: Vec<Row>) -> Vec<Row> {
    let mut steps: Vec<Row> = Vec::new();
    let mut pending: Vec<usize> = Vec::new(); // indices into steps, oldest first
    for row in rows {
        let kind = row.get("kind").cloned();
        let tid = row.get("tool_use_id").cloned();
        let ts = row.get("ts").cloned();
        if (is_str(kind.as_ref(), "done") || is_str(kind.as_ref(), "error")) && opt_truthy(tid.as_ref()) {
            let hit: Vec<usize> =
                pending.iter().copied().filter(|&w| opt_eq(steps[w].get("tool_use_id"), tid.as_ref())).collect();
            if !hit.is_empty() {
                let mut all = hit;
                all.extend(pending.iter().copied().filter(|&w| !opt_truthy(steps[w].get("tool_use_id"))));
                let how = kind.as_ref().and_then(|k| k.as_str()).unwrap_or("");
                answer(&mut steps, &mut pending, &all, how, ts.as_ref());
            }
        }
        if opt_truthy(row.get("quiet")) {
            continue;
        }
        if is_str(kind.as_ref(), "waiting") {
            let twin = match pending.last() {
                Some(&p) if !steps.is_empty() && p == steps.len() - 1 && permission(&row) && permission(&steps[p]) => Some(p),
                _ => None,
            };
            if let Some(t) = twin {
                if !opt_truthy(tid.as_ref()) && opt_truthy(steps[t].get("tool_use_id")) {
                    continue; // the notification about the prompt just logged with its id
                }
                if opt_truthy(tid.as_ref()) && !opt_truthy(steps[t].get("tool_use_id")) {
                    steps.pop(); // the notification came first: keep the record with the id
                    pending.pop();
                }
            }
            pending.push(steps.len());
        } else if is_str(kind.as_ref(), "you") {
            let all = pending.clone();
            answer(&mut steps, &mut pending, &all, "you", ts.as_ref());
        } else if !(is_str(kind.as_ref(), "error") || is_str(kind.as_ref(), "note") || is_str(kind.as_ref(), "turn")) {
            let same: Vec<usize> =
                pending.iter().copied().filter(|&w| opt_eq(steps[w].get("subagent"), row.get("subagent"))).collect();
            answer(&mut steps, &mut pending, &same, "step", ts.as_ref());
        }
        steps.push(row);
    }
    steps
}

#[cfg(test)]
mod tests {
    //! Every case of server.py's ActivityStepsTest (tests/test_api.py).
    use super::*;
    use serde_json::json;

    fn rows(v: Value) -> Vec<Row> {
        v.as_array().unwrap().iter().map(|r| r.as_object().unwrap().clone()).collect()
    }
    fn kinds(s: &[Row]) -> Vec<&str> {
        s.iter().map(|r| r["kind"].as_str().unwrap()).collect()
    }

    #[test]
    fn quiet_records_are_not_steps() {
        let out = activity_steps(rows(json!([
            {"ts": "1", "kind": "read", "text": "Reading a", "tool_use_id": "t1"},
            {"ts": "2", "kind": "done", "text": "Finished: reading a", "tool_use_id": "t1", "quiet": true},
            {"ts": "3", "kind": "edit", "text": "Editing a", "tool_use_id": "t2"}])));
        assert_eq!(kinds(&out), ["read", "edit"]);
    }

    #[test]
    fn done_for_the_same_step_resolves_a_permission_wait() {
        let out = activity_steps(rows(json!([
            {"ts": "1", "kind": "command", "text": "Run it", "tool_use_id": "t1"},
            {"ts": "2", "kind": "waiting", "text": "Waiting for your permission in Claude Code", "tool_use_id": "t1"},
            {"ts": "3", "kind": "waiting", "text": "Waiting for your permission in Claude Code"},
            {"ts": "4", "kind": "done", "text": "Finished: run it", "tool_use_id": "t1", "quiet": true}])));
        // The notification without an id is the same prompt, not a second wait.
        assert_eq!(kinds(&out), ["command", "waiting"]);
        assert_eq!(out[1]["tool_use_id"], "t1");
        assert_eq!(out[1]["resolved"], "done");
        assert_eq!(out[1]["resolved_ts"], "4");
    }

    #[test]
    fn a_wait_without_an_id_is_resolved_with_the_waits_before_it() {
        let out = activity_steps(rows(json!([
            {"ts": "1", "kind": "waiting", "text": "Waiting for your permission in Claude Code", "tool_use_id": "t1"},
            {"ts": "2", "kind": "waiting", "text": "Waiting for your reply in Claude Code"},
            {"ts": "3", "kind": "done", "text": "Finished", "tool_use_id": "t1", "quiet": true}])));
        assert_eq!(out.iter().map(|r| r["resolved"].as_str().unwrap()).collect::<Vec<_>>(), ["done", "done"]);
    }

    #[test]
    fn done_for_another_step_does_not_resolve_it() {
        let out = activity_steps(rows(json!([
            {"ts": "1", "kind": "waiting", "text": "Waiting for your permission in Claude Code", "tool_use_id": "t1"},
            {"ts": "2", "kind": "done", "text": "Finished: other", "tool_use_id": "t9", "quiet": true}])));
        assert!(!out.last().unwrap().contains_key("resolved"));
    }

    #[test]
    fn error_reply_and_next_step_resolve_waits() {
        let out = activity_steps(rows(json!([
            {"ts": "1", "kind": "waiting", "text": "Waiting for your permission in Claude Code", "tool_use_id": "t1"},
            {"ts": "2", "kind": "error", "text": "A step did not work: run it", "tool_use_id": "t1", "detail": "exit 1"},
            {"ts": "3", "kind": "waiting", "text": "Waiting for your reply in Claude Code"},
            {"ts": "4", "kind": "you", "text": "You sent a message in Claude Code"},
            {"ts": "5", "kind": "waiting", "text": "Waiting for your reply in Claude Code"},
            {"ts": "6", "kind": "read", "text": "Reading b"}])));
        assert_eq!(kinds(&out), ["waiting", "error", "waiting", "you", "waiting", "read"]);
        let res: Vec<&str> = [0, 2, 4].iter().map(|&i| out[i]["resolved"].as_str().unwrap()).collect();
        assert_eq!(res, ["error", "you", "step"]);
        assert_eq!(out[1]["detail"], "exit 1");
    }

    #[test]
    fn the_duplicate_prompt_counts_once_in_either_order() {
        let out = activity_steps(rows(json!([
            {"ts": "1", "kind": "waiting", "text": "Waiting for your permission in Claude Code"},
            {"ts": "2", "kind": "waiting", "text": "Waiting for your permission in Claude Code", "tool_use_id": "t1"}])));
        assert_eq!(out.len(), 1);
        assert_eq!(out[0]["tool_use_id"], "t1");
    }

    #[test]
    fn notes_turns_and_other_agents_are_no_answer() {
        for later in [json!({"ts": "2", "kind": "turn", "text": "Finished its turn"}),
                      json!({"ts": "2", "kind": "note", "text": "Notification"}),
                      json!({"ts": "2", "kind": "read", "text": "Reading b", "subagent": "reviewer"})] {
            let out = activity_steps(rows(json!([
                {"ts": "1", "kind": "waiting", "text": "Waiting for your permission in Claude Code", "tool_use_id": "t1"}, later.clone()])));
            assert!(!out[0].contains_key("resolved"), "{later}");
        }
        let out = activity_steps(rows(json!([
            {"ts": "1", "kind": "waiting", "text": "Waiting for your reply in Claude Code", "subagent": "reviewer"},
            {"ts": "2", "kind": "read", "text": "Reading b", "subagent": "reviewer"}])));
        assert_eq!(out[0]["resolved"], "step");
    }
}
