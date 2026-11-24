//! The router: every question the page asks, with server.py's endpoints and JSON shapes.
//! `Core::get` and `Core::post` answer them; `http_router` puts them on 127.0.0.1 for `serve`,
//! with server.py's write guards.

use std::collections::HashMap;
use std::net::{IpAddr, SocketAddr};
use std::sync::{Arc, OnceLock};

use axum::body::{to_bytes, Body};
use axum::extract::{ConnectInfo, Request, State};
use axum::http::{header, HeaderMap, HeaderValue, Method, StatusCode};
use axum::response::Response;
use axum::Router;
use serde_json::{json, Value};

use crate::py::universal_newlines;
use crate::records::{is_plot, plot_type};
use crate::Core;

pub const WRITE_HEADER: (&str, &str) = ("X-AAF-Request", "control-room");
pub const LOCAL_HOSTS: [&str; 4] = ["localhost", "127.0.0.1", "[::1]", "::1"];
pub const MAX_BODY: usize = 4096;

/// The page, built into the program.
pub fn page() -> &'static str {
    static PAGE: OnceLock<String> = OnceLock::new();
    PAGE.get_or_init(|| universal_newlines(include_str!("../../index.html")))
}

/// An answer: status, content type, body.
#[derive(Debug, Clone)]
pub struct Resp {
    pub status: u16,
    pub ctype: &'static str,
    pub body: Vec<u8>,
}

impl Resp {
    pub fn json(v: &Value, status: u16) -> Resp {
        Resp { status, ctype: "application/json", body: serde_json::to_vec(v).unwrap_or_default() }
    }
    pub fn not_found() -> Resp {
        Resp { status: 404, ctype: "text/plain", body: b"not found".to_vec() }
    }
    pub fn json_value(&self) -> Value {
        serde_json::from_slice(&self.body).unwrap_or(Value::Null)
    }
}

/// Python's parse_qs: blank values and fields without "=" are dropped.
pub fn parse_qs(query: &str) -> HashMap<String, Vec<String>> {
    let mut q: HashMap<String, Vec<String>> = HashMap::new();
    for field in query.split('&') {
        if !field.contains('=') {
            continue;
        }
        if let Some((k, v)) = form_urlencoded::parse(field.as_bytes()).next() {
            if !v.is_empty() {
                q.entry(k.into_owned()).or_default().push(v.into_owned());
            }
        }
    }
    q
}

impl Core {
    /// Answer a GET request.
    pub fn get(&self, path: &str, query: &str) -> Resp {
        let q = parse_qs(query);
        let first = |k: &str| q.get(k).and_then(|v| v.first()).cloned();
        let name = first("name").or_else(|| first("project")).unwrap_or_default();
        let known = || self.project_names().contains(&name);
        let unknown = || Resp::json(&json!({"error": "unknown project"}), 404);
        match path {
            "/" | "/index.html" => Resp { status: 200, ctype: "text/html; charset=utf-8", body: page().as_bytes().to_vec() },
            "/api/projects" => {
                let list: Vec<Value> = self.project_names().iter().map(|n| self.summary(n)).collect();
                Resp::json(&Value::Array(list), 200)
            }
            "/api/record" => Resp::json(&self.workspace_record(), 200),
            "/api/project" => {
                if !known() {
                    return unknown();
                }
                Resp::json(&self.detail(&name), 200)
            }
            "/api/git" => {
                if !known() {
                    return unknown();
                }
                Resp::json(&self.aaf.git_info(&self.root(), &name, q.contains_key("fresh")), 200)
            }
            "/api/files" => {
                if !known() {
                    return unknown();
                }
                Resp::json(&self.aaf.git_files(&self.root(), &name, q.contains_key("fresh")), 200)
            }
            "/plot" => {
                let file = first("file").unwrap_or_default();
                if !known() || !plain_file_name(&file) || !is_plot(&file) {
                    return Resp::not_found();
                }
                let path = self.projects_dir().join(&name).join("plots").join(&file);
                if !path.is_file() {
                    return Resp::not_found();
                }
                match std::fs::read(&path) {
                    Ok(b) => Resp { status: 200, ctype: plot_type(&file), body: b },
                    Err(_) => Resp::not_found(),
                }
            }
            _ => Resp::not_found(),
        }
    }

    /// Answer a POST request that already passed the write guard. `body` is at most MAX_BODY bytes.
    pub fn post(&self, path: &str, body: &[u8]) -> Resp {
        let Some(action) = post_action(path) else { return Resp::not_found() };
        let parsed: Option<Value> = if body.is_empty() { Some(json!({})) } else { serde_json::from_slice(body).ok() };
        let Some(parsed) = parsed else {
            return Resp::json(&json!({"ok": false, "message": "bad request"}), 400);
        };
        let name = match parsed.get("name") {
            Some(Value::String(s)) if parsed.is_object() => s.clone(),
            _ => String::new(),
        };
        if !self.project_names().contains(&name) {
            return Resp::json(&json!({"ok": false, "message": "unknown project"}), 404);
        }
        let (code, result) = self.aaf.git_action(&self.root(), &name, action);
        Resp::json(&result, code)
    }
}

/// One plain file name, so joining it to plots/ stays inside plots/: no folder separators, no leading
/// dot, no drive (`C:x.png` would replace the whole path on Windows), nothing but a normal name.
pub fn plain_file_name(file: &str) -> bool {
    use std::path::{Component, Path};
    if file.is_empty() || file.contains(['/', '\\', ':', '\0']) || file.starts_with('.') {
        return false;
    }
    let mut parts = Path::new(file).components();
    matches!((parts.next(), parts.next()), (Some(Component::Normal(n)), None) if n == std::ffi::OsStr::new(file))
}

/// "push" or "pull" for the two write paths, else None.
pub fn post_action(path: &str) -> Option<&'static str> {
    match path {
        "/api/git/push" => Some("push"),
        "/api/git/pull" => Some("pull"),
        _ => None,
    }
}

/// Only the page itself may ask for a change: same machine, our header, our host and origin.
pub fn from_page(peer: IpAddr, headers: &HeaderMap, port: u16) -> bool {
    let local = match peer {
        IpAddr::V4(a) => a.octets() == [127, 0, 0, 1],
        IpAddr::V6(a) => a.is_loopback() || a.to_ipv4_mapped().map(|v| v.octets() == [127, 0, 0, 1]).unwrap_or(false),
    };
    if !local {
        return false;
    }
    let text = |h: &str| headers.get(h).map(|v| v.to_str().map(|s| s.to_string()).ok());
    if text(WRITE_HEADER.0) != Some(Some(WRITE_HEADER.1.to_string())) {
        return false;
    }
    let host = match text("host") {
        Some(Some(h)) => h,
        None => String::new(),
        Some(None) => return false,
    };
    let (h, p) = match host.rsplit_once(':') {
        Some((h, p)) => (h.to_string(), Some(p.to_string())),
        None => (host.clone(), None),
    };
    if !LOCAL_HOSTS.contains(&h.as_str()) || p.map(|p| p != port.to_string()).unwrap_or(false) {
        return false;
    }
    match text("origin") {
        Some(Some(o)) if !o.is_empty() => ["localhost", "127.0.0.1", "[::1]"].iter().any(|h| o == format!("http://{}:{}", h, port)),
        Some(None) => false,
        _ => true,
    }
}

#[derive(Clone)]
pub struct HttpState {
    pub core: Arc<Core>,
    pub port: u16,
}

fn respond(r: Resp, close: bool) -> Response {
    let mut res = Response::new(Body::from(r.body));
    *res.status_mut() = StatusCode::from_u16(r.status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR);
    let h = res.headers_mut();
    h.insert(header::CONTENT_TYPE, HeaderValue::from_static(r.ctype));
    h.insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
    if close {
        h.insert(header::CONNECTION, HeaderValue::from_static("close"));
    }
    res
}

async fn handle(State(st): State<HttpState>, ConnectInfo(peer): ConnectInfo<SocketAddr>, req: Request) -> Response {
    let path = req.uri().path().to_string();
    let query = req.uri().query().unwrap_or("").to_string();
    let core = st.core.clone();
    match *req.method() {
        Method::GET => {
            let r = tokio::task::spawn_blocking(move || core.get(&path, &query)).await;
            respond(r.unwrap_or(Resp { status: 500, ctype: "text/plain", body: b"error".to_vec() }), false)
        }
        Method::POST => {
            if post_action(&path).is_none() {
                return respond(Resp::not_found(), false);
            }
            if !from_page(peer.ip(), req.headers(), st.port) {
                return respond(Resp::json(&json!({"ok": false, "message": "Only the Control Room page on this computer may do this."}), 403), false);
            }
            let length: i64 = match req.headers().get(header::CONTENT_LENGTH) {
                None => 0,
                Some(v) => v.to_str().ok().and_then(|s| s.trim().parse().ok()).unwrap_or(-1),
            };
            if !(0..=MAX_BODY as i64).contains(&length) {
                // Never read an unbounded or negative length.
                return respond(Resp::json(&json!({"ok": false, "message": "bad request"}), 400), true);
            }
            let body = if length == 0 {
                Vec::new()
            } else {
                match to_bytes(req.into_body(), MAX_BODY).await {
                    Ok(b) => b.to_vec(),
                    Err(_) => return respond(Resp::json(&json!({"ok": false, "message": "bad request"}), 400), true),
                }
            };
            let r = tokio::task::spawn_blocking(move || core.post(&path, &body)).await;
            respond(r.unwrap_or(Resp { status: 500, ctype: "text/plain", body: b"error".to_vec() }), false)
        }
        _ => respond(Resp { status: 501, ctype: "text/plain", body: b"Unsupported method".to_vec() }, false),
    }
}

/// The router over HTTP (`control-room serve`).
pub fn http_router(core: Arc<Core>, port: u16) -> Router {
    Router::new().fallback(handle).with_state(HttpState { core, port })
}

/// Serve the router on 127.0.0.1:`port` (0: any free port) until the process ends.
/// Prints "Serving on http://127.0.0.1:<port>" once listening.
pub async fn serve(core: Arc<Core>, port: u16) -> std::io::Result<()> {
    let listener = tokio::net::TcpListener::bind(("127.0.0.1", port)).await?;
    let port = listener.local_addr()?.port();
    println!("Serving on http://127.0.0.1:{}", port);
    use std::io::Write;
    let _ = std::io::stdout().flush();
    axum::serve(listener, http_router(core, port).into_make_service_with_connect_info::<SocketAddr>()).await
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::aaf::{Aaf, Output, Runner};
    use std::path::{Path, PathBuf};
    use std::time::Duration;

    struct NoPython;
    impl Runner for NoPython {
        fn python(&self, _a: &[String], _c: &Path, _t: Duration, _e: &[(&str, &str)]) -> Output {
            Output { code: None, out: String::new(), err: "no python in unit tests".into() }
        }
    }

    fn fixtures() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("..").join("fixtures").join("workspace")
    }

    fn core() -> Core {
        Core::new(fixtures(), Aaf::new(Box::new(NoPython), None, vec![]), std::env::temp_dir())
    }

    fn headers(pairs: &[(&str, &str)]) -> HeaderMap {
        let mut h = HeaderMap::new();
        for (k, v) in pairs {
            h.insert(axum::http::HeaderName::from_bytes(k.as_bytes()).unwrap(), HeaderValue::from_str(v).unwrap());
        }
        h
    }

    #[test]
    fn rejects_path_traversal_and_unknown_projects() {
        let c = core();
        assert_eq!(c.get("/plot", "project=example-done&file=loss.svg").status, 200);
        assert_eq!(c.get("/plot", "project=example-done&file=loss.svg").ctype, "image/svg+xml");
        for q in ["project=example-done&file=../project.json", "project=../..&file=loss.svg",
                  "project=example-done&file=..%2F..%2Fproject.json", "project=example-done&file=..%5Cproject.json",
                  "project=example-done&file=.hidden.png", "project=example-done&file=missing.png",
                  "project=example-done&file=project.json", "project=example-done&file=C:loss.svg",
                  "project=example-done&file=C%3Aloss.svg", "project=example-done&file=C:%5Cx.png",
                  "project=example-done&file=%5C%5Cserver%5Cshare%5Cx.png"] {
            assert_eq!(c.get("/plot", q).status, 404, "{q}");
        }
        for path in ["/api/project", "/api/git", "/api/files"] {
            for name in ["nope", "..", "../..", "example-done/../parser", "..%2Fscheduler", ""] {
                assert_eq!(c.get(path, &format!("name={name}")).status, 404, "{path} {name}");
            }
        }
        assert_eq!(c.get("/api/project", "name=parser").status, 200);
        assert_eq!(c.get("/nothing", "").status, 404);
    }

    #[test]
    fn plot_names_are_one_plain_file_name() {
        for ok in ["loss.svg", "render-a b.png", "x..y.png"] {
            assert!(plain_file_name(ok), "{ok}");
        }
        for bad in ["", ".", "..", "../x.png", "a/x.png", "a\\x.png", "C:x.png", "C:\\x.png", "\\\\srv\\s\\x.png", ".x.png", "x.png\0"] {
            assert!(!plain_file_name(bad), "{bad}");
        }
    }

    #[test]
    fn page_and_lists() {
        let c = core();
        let r = c.get("/", "");
        assert!(r.ctype.starts_with("text/html") && String::from_utf8_lossy(&r.body).contains("<html"));
        assert_eq!(c.get("/api/projects", "").json_value().as_array().unwrap().len(), 9);
        let d = c.get("/api/project", "name=parser").json_value();
        assert_eq!(d["drafts"][0]["id"], "fix-1");
        let empty = c.get("/api/project", "project=brand-new").json_value();
        assert_eq!(empty["activity"], json!([]));
        assert_eq!(empty["summary"]["activity"], Value::Null);
        assert_eq!(c.record("brand-new"), json!({"reviews": [], "reasons": []}));
    }

    #[test]
    fn query_like_python_parse_qs() {
        let q = parse_qs("name=&project=a+b&fresh&x=%2F&name=c&name=d");
        assert_eq!(q.get("name"), Some(&vec!["c".to_string(), "d".to_string()]));
        assert_eq!(q.get("project"), Some(&vec!["a b".to_string()]));
        assert!(!q.contains_key("fresh"));
        assert_eq!(q.get("x"), Some(&vec!["/".to_string()]));
    }

    #[test]
    fn write_guard() {
        let lo: IpAddr = "127.0.0.1".parse().unwrap();
        let ok = [("X-AAF-Request", "control-room"), ("Host", "127.0.0.1:8765")];
        assert!(from_page(lo, &headers(&ok), 8765));
        assert!(from_page("::1".parse().unwrap(), &headers(&[ok[0], ("Host", "[::1]:8765")]), 8765));
        assert!(from_page("::ffff:127.0.0.1".parse().unwrap(), &headers(&[ok[0], ("Host", "localhost")]), 8765));
        assert!(from_page(lo, &headers(&[ok[0], ok[1], ("Origin", "http://localhost:8765")]), 8765));
        assert!(!from_page("192.168.1.5".parse().unwrap(), &headers(&ok), 8765), "another machine");
        assert!(!from_page("127.0.0.2".parse().unwrap(), &headers(&ok), 8765));
        assert!(!from_page(lo, &headers(&[ok[1]]), 8765), "no header");
        assert!(!from_page(lo, &headers(&[("X-AAF-Request", "other"), ok[1]]), 8765));
        assert!(!from_page(lo, &headers(&[ok[0], ("Host", "evil.example")]), 8765));
        assert!(!from_page(lo, &headers(&[ok[0], ("Host", "127.0.0.1:1")]), 8765));
        assert!(!from_page(lo, &headers(&[ok[0], ok[1], ("Origin", "https://evil.example")]), 8765));
        assert!(!from_page(lo, &headers(&[ok[0], ok[1], ("Origin", "http://localhost:1")]), 8765));
    }

    #[test]
    fn post_checks_path_body_and_name() {
        let c = core();
        assert_eq!(c.post("/api/git/reset", b"{\"name\": \"parser\"}").status, 404);
        assert_eq!(c.post("/api/git/push", b"{\"name\": \"../..\"}").status, 404);
        assert_eq!(c.post("/api/git/push", b"{\"name\": 5}").status, 404);
        assert_eq!(c.post("/api/git/push", b"not json").status, 400);
        assert_eq!(c.post("/api/git/push", b"").status, 404);
        // Pull is refused while the agent works (image-classifier is implementing in the fixtures).
        assert_eq!(c.post("/api/git/pull", b"{\"name\": \"image-classifier\"}").status, 409);
    }

    #[tokio::test]
    async fn http_refuses_bad_lengths_and_foreign_writes() {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        let core = Arc::new(core());
        let listener = tokio::net::TcpListener::bind(("127.0.0.1", 0)).await.unwrap();
        let port = listener.local_addr().unwrap().port();
        tokio::spawn(async move {
            axum::serve(listener, http_router(core, port).into_make_service_with_connect_info::<SocketAddr>()).await.unwrap();
        });
        async fn raw(port: u16, text: String) -> String {
            let mut s = tokio::net::TcpStream::connect(("127.0.0.1", port)).await.unwrap();
            s.write_all(text.as_bytes()).await.unwrap();
            let mut buf = vec![0u8; 256];
            let n = tokio::time::timeout(Duration::from_secs(5), s.read(&mut buf)).await.map(|r| r.unwrap_or(0)).unwrap_or(0);
            String::from_utf8_lossy(&buf[..n]).to_string()
        }
        for length in ["-1", "abc", "99999"] {
            let r = raw(port, format!("POST /api/git/push HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nX-AAF-Request: control-room\r\nContent-Type: application/json\r\nContent-Length: {length}\r\n\r\n")).await;
            assert!(r.starts_with("HTTP/1.1 4") || r.starts_with("HTTP/1.0 4"), "Content-Length {length}: {r:?}");
        }
        let r = raw(port, format!("POST /api/git/push HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nContent-Length: 2\r\n\r\n{{}}")).await;
        assert!(r.starts_with("HTTP/1.1 403"), "{r}");
        let r = raw(port, format!("POST /api/git/push HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nX-AAF-Request: control-room\r\nOrigin: https://evil.example\r\nContent-Length: 2\r\n\r\n{{}}")).await;
        assert!(r.starts_with("HTTP/1.1 403"), "{r}");
        let r = raw(port, format!("GET /api/git/push?name=example-done HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n")).await;
        assert!(r.starts_with("HTTP/1.1 404"), "{r}");
        let r = raw(port, format!("OPTIONS /api/git/push HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n")).await;
        assert!(!r.starts_with("HTTP/1.1 204") && r.starts_with("HTTP/1.1 501"), "{r}");
        let r = raw(port, format!("GET /api/projects HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n")).await;
        assert!(r.starts_with("HTTP/1.1 200") && r.to_lowercase().contains("cache-control: no-store"), "{r}");
    }

    #[test]
    fn no_git_command_in_the_source() {
        let src = Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
        let re = regex::Regex::new(r#"Command::new\(\s*"git(\.exe)?"\s*\)"#).unwrap();
        for e in std::fs::read_dir(src).unwrap() {
            let p = e.unwrap().path();
            let text = std::fs::read_to_string(&p).unwrap();
            assert!(!re.is_match(&text), "{} runs git itself", p.display());
        }
    }
}
