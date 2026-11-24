//! The desktop app: one window showing the page, served by the core through a custom protocol
//! (`app://`, `http://app.localhost` on Windows), so the app opens no network port.

use std::path::PathBuf;
use std::sync::Arc;

use tauri::http::{header, Request, Response, StatusCode};
use tauri::{WebviewUrl, WebviewWindowBuilder};

use crate::aaf::{Aaf, PythonRunner};
use crate::api::{post_action, Resp, MAX_BODY, WRITE_HEADER};
use crate::{fallback_aaf, workspaces, Core};

pub const TITLE: &str = "Agent Control Room";

/// Command-line options of the app: `control-room [--root DIR] [--config DIR]`.
pub struct Options {
    pub root: Option<PathBuf>,
    pub config: PathBuf,
}

fn to_response(r: Resp) -> Response<Vec<u8>> {
    Response::builder()
        .status(StatusCode::from_u16(r.status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR))
        .header(header::CONTENT_TYPE, r.ctype)
        .header(header::CACHE_CONTROL, "no-store")
        .body(r.body)
        .unwrap()
}

/// A request from the window. The window is the only thing that can reach this protocol, but
/// writes still need the page's header, as over HTTP.
pub fn answer(core: &Core, req: &Request<Vec<u8>>) -> Resp {
    let path = req.uri().path().to_string();
    let query = req.uri().query().unwrap_or("").to_string();
    match req.method().as_str() {
        "GET" => core.get(&path, &query),
        "POST" => {
            if post_action(&path).is_none() {
                return Resp::not_found();
            }
            let ok = req.headers().get(WRITE_HEADER.0).and_then(|v| v.to_str().ok()) == Some(WRITE_HEADER.1);
            if !ok {
                return Resp::json(&serde_json::json!({"ok": false, "message": "Only the Control Room page may do this."}), 403);
            }
            if req.body().len() > MAX_BODY {
                return Resp::json(&serde_json::json!({"ok": false, "message": "bad request"}), 400);
            }
            core.post(&path, req.body())
        }
        _ => Resp { status: 501, ctype: "text/plain", body: b"Unsupported method".to_vec() },
    }
}

fn default_root() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    crate::aaf::find_workspace(exe.parent()?)
        .or_else(|| crate::aaf::find_workspace(std::path::Path::new(env!("CARGO_MANIFEST_DIR"))))
}

pub fn run(opts: Options) {
    let settings = workspaces::load_settings(&opts.config);
    let runner = PythonRunner::new(workspaces::python_path(&settings));
    // Until workspaces are chosen in the app (feature 4): --root, else the workspace this program
    // runs from or was built in.
    let root = opts.root.clone().or_else(default_root).unwrap_or_else(|| PathBuf::from("."));
    let core = Arc::new(Core::new(root, Aaf::new(Box::new(runner), None, fallback_aaf()), opts.config.clone()));
    let proto_core = core.clone();
    let config = opts.config.clone();
    tauri::Builder::default()
        .plugin(tauri_plugin_window_state::Builder::default()
            .with_filename(config.join("window-state.json").to_string_lossy())
            .build())
        .register_asynchronous_uri_scheme_protocol("app", move |_ctx, req, responder| {
            let core = proto_core.clone();
            std::thread::spawn(move || responder.respond(to_response(answer(&core, &req))));
        })
        .setup(move |app| {
            let url = WebviewUrl::CustomProtocol("app://localhost/".parse().unwrap());
            WebviewWindowBuilder::new(app, "main", url)
                .title(TITLE)
                .inner_size(1280.0, 800.0)
                .min_inner_size(390.0, 500.0)
                .data_directory(config.join("webview"))
                .build()?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("the app could not start");
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::aaf::{Output, Runner};
    use std::path::Path;
    use std::time::Duration;

    struct NoPython;
    impl Runner for NoPython {
        fn python(&self, _a: &[String], _c: &Path, _t: Duration, _e: &[(&str, &str)]) -> Output {
            Output { code: None, out: String::new(), err: String::new() }
        }
    }

    fn core() -> Core {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("..").join("fixtures").join("workspace");
        Core::new(root, Aaf::new(Box::new(NoPython), None, vec![]), std::env::temp_dir())
    }

    fn req(method: &str, uri: &str, header: bool, body: &[u8]) -> Request<Vec<u8>> {
        let mut b = Request::builder().method(method).uri(uri);
        if header {
            b = b.header(WRITE_HEADER.0, WRITE_HEADER.1);
        }
        b.body(body.to_vec()).unwrap()
    }

    #[test]
    fn the_window_gets_the_same_answers() {
        let c = core();
        let page = answer(&c, &req("GET", "http://app.localhost/", false, b""));
        assert_eq!(page.status, 200);
        assert!(String::from_utf8_lossy(&page.body).contains("<title>Agent Control Room</title>"));
        assert_eq!(answer(&c, &req("GET", "http://app.localhost/api/project?name=parser", false, b"")).body,
                   c.get("/api/project", "name=parser").body);
        assert_eq!(answer(&c, &req("GET", "http://app.localhost/api/project?name=..", false, b"")).status, 404);
        assert_eq!(answer(&c, &req("GET", "http://app.localhost/plot?project=example-done&file=C:loss.svg", false, b"")).status, 404);
    }

    #[test]
    fn writes_from_the_window_need_the_header_and_a_small_body() {
        let c = core();
        let body = br#"{"name": "image-classifier"}"#;
        assert_eq!(answer(&c, &req("POST", "http://app.localhost/api/git/pull", false, body)).status, 403);
        assert_eq!(answer(&c, &req("POST", "http://app.localhost/api/git/pull", true, &vec![b' '; MAX_BODY + 1])).status, 400);
        assert_eq!(answer(&c, &req("POST", "http://app.localhost/api/git/reset", true, body)).status, 404);
        // image-classifier is being worked on in the fixtures: Pull is refused, through the window too.
        assert_eq!(answer(&c, &req("POST", "http://app.localhost/api/git/pull", true, body)).status, 409);
        assert_eq!(answer(&c, &req("DELETE", "http://app.localhost/api/git/pull", true, body)).status, 501);
    }
}
