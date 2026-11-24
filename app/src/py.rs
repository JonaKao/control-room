//! Small helpers that give JSON values the meaning they had in server.py (Python):
//! truthiness, `str()`, `int()`, `==`, `str.strip()` and text-mode newlines.
//! The records the page shows were written by Python, and the port must read them the same way.

use serde_json::{Map, Value};

/// Python's `bool(x)` for a JSON value.
pub fn truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().map(|f| f != 0.0).unwrap_or(true),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

pub fn opt_truthy(v: Option<&Value>) -> bool {
    v.map(truthy).unwrap_or(false)
}

/// Python's `repr()` of a float, which is also what `str()` gives.
fn float_repr(f: f64) -> String {
    if f.is_nan() {
        return "nan".into();
    }
    if f.is_infinite() {
        return if f > 0.0 { "inf".into() } else { "-inf".into() };
    }
    // serde_json prints the shortest round-trip form like Python; Python adds exponents past 1e16.
    let s = serde_json::to_string(&f).unwrap_or_default();
    if f.fract() == 0.0 && f.abs() < 1e16 && !s.contains('.') && !s.contains('e') {
        format!("{}.0", s)
    } else {
        s
    }
}

fn repr_str(s: &str) -> String {
    let quote = if s.contains('\'') && !s.contains('"') { '"' } else { '\'' };
    let mut out = String::new();
    out.push(quote);
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c == quote => {
                out.push('\\');
                out.push(c)
            }
            c if (c as u32) < 0x20 || c as u32 == 0x7f => out.push_str(&format!("\\x{:02x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push(quote);
    out
}

fn repr(v: &Value) -> String {
    match v {
        Value::String(s) => repr_str(s),
        other => py_str(other),
    }
}

/// Python's `str(x)` for a JSON value (as `json.load` would have made it).
pub fn py_str(v: &Value) -> String {
    match v {
        Value::Null => "None".into(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        Value::Number(n) => {
            if n.is_f64() {
                float_repr(n.as_f64().unwrap_or(0.0))
            } else {
                n.to_string()
            }
        }
        Value::String(s) => s.clone(),
        Value::Array(a) => format!("[{}]", a.iter().map(repr).collect::<Vec<_>>().join(", ")),
        Value::Object(o) => format!(
            "{{{}}}",
            o.iter().map(|(k, v)| format!("{}: {}", repr_str(k), repr(v))).collect::<Vec<_>>().join(", ")
        ),
    }
}

/// `str(d.get(key, default))`.
pub fn get_str(m: &Map<String, Value>, key: &str, default: &str) -> String {
    m.get(key).map(py_str).unwrap_or_else(|| default.to_string())
}

/// Python's `int(x)`; None where Python raises (the callers skip such records).
pub fn py_int(v: &Value) -> Option<i64> {
    match v {
        Value::Bool(b) => Some(*b as i64),
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                Some(i)
            } else {
                let f = n.as_f64()?;
                if f.is_finite() {
                    Some(f.trunc() as i64)
                } else {
                    None
                }
            }
        }
        Value::String(s) => {
            let t = py_strip(s).replace('_', "");
            if t.is_empty() || s.contains("__") {
                return None;
            }
            t.parse::<i64>().ok()
        }
        _ => None,
    }
}

/// Python's `==` between two JSON values (1 == 1.0 == True).
pub fn py_eq(a: &Value, b: &Value) -> bool {
    fn num(v: &Value) -> Option<f64> {
        match v {
            Value::Bool(b) => Some(*b as i64 as f64),
            Value::Number(n) => n.as_f64(),
            _ => None,
        }
    }
    match (a, b) {
        (Value::Array(x), Value::Array(y)) => x.len() == y.len() && x.iter().zip(y).all(|(p, q)| py_eq(p, q)),
        (Value::Object(x), Value::Object(y)) => {
            x.len() == y.len() && x.iter().all(|(k, v)| y.get(k).map(|w| py_eq(v, w)).unwrap_or(false))
        }
        _ => match (num(a), num(b)) {
            (Some(x), Some(y)) => x == y,
            _ => a == b,
        },
    }
}

pub fn opt_eq(a: Option<&Value>, b: Option<&Value>) -> bool {
    py_eq(a.unwrap_or(&Value::Null), b.unwrap_or(&Value::Null))
}

/// Is `v` the string `s`?
pub fn is_str(v: Option<&Value>, s: &str) -> bool {
    matches!(v, Some(Value::String(x)) if x == s)
}

/// Python's `str.isspace()` for one character.
pub fn is_py_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// Python's `str.strip()`.
pub fn py_strip(s: &str) -> &str {
    s.trim_matches(is_py_space)
}

/// Text read the way Python's text mode reads it: "\r\n" and "\r" become "\n".
pub fn universal_newlines(s: &str) -> String {
    if !s.contains('\r') {
        return s.to_string();
    }
    s.replace("\r\n", "\n").replace('\r', "\n")
}

/// The last `n` characters (Python's `s[-n:]`).
pub fn last_chars(s: &str, n: usize) -> String {
    let count = s.chars().count();
    s.chars().skip(count.saturating_sub(n)).collect()
}

/// Python's `round(x, 3)`: the nearest 3-decimal number to the exact value of x.
pub fn round3(x: f64) -> f64 {
    format!("{:.3}", x).parse().unwrap_or(x)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn truthiness_and_str_follow_python() {
        assert!(!truthy(&json!(0)) && !truthy(&json!("")) && !truthy(&json!([])) && !truthy(&json!(null)));
        assert!(truthy(&json!("0")) && truthy(&json!([0])) && truthy(&json!(0.5)));
        assert_eq!(py_str(&json!(null)), "None");
        assert_eq!(py_str(&json!(3)), "3");
        assert_eq!(py_str(&json!(3.0)), "3.0");
        assert_eq!(py_str(&json!(true)), "True");
        assert_eq!(py_str(&json!(["a", 1])), "['a', 1]");
        assert_eq!(py_str(&json!({"k": "it's"})), "{'k': \"it's\"}");
    }

    #[test]
    fn int_eq_strip_round_follow_python() {
        assert_eq!(py_int(&json!(" 12 ")), Some(12));
        assert_eq!(py_int(&json!(3.9)), Some(3));
        assert_eq!(py_int(&json!("3.0")), None);
        assert_eq!(py_int(&json!(true)), Some(1));
        assert_eq!(py_int(&json!([1])), None);
        assert!(py_eq(&json!(1), &json!(1.0)) && py_eq(&json!(true), &json!(1)) && !py_eq(&json!("1"), &json!(1)));
        assert_eq!(py_strip("\u{1f} a \n"), "a");
        assert_eq!(universal_newlines("a\r\nb\rc"), "a\nb\nc");
        assert_eq!(last_chars("äbc", 2), "bc");
        // Python: round(0.0625, 3) == 0.062, round(2/3, 3) == 0.667, round(0.0005, 3) == 0.001 (0.0005 is above .0005)
        assert_eq!(round3(0.0625), 0.062);
        assert_eq!(round3(2.0 / 3.0), 0.667);
        assert_eq!(round3(0.0005), 0.001);
        assert_eq!(round3(0.0015), 0.002);
    }
}
