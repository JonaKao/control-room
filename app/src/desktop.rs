//! The desktop app: one window showing the page, served by the core through a custom protocol
//! (`app://`, `http://app.localhost` on Windows), so the app opens no network port.

use std::path::PathBuf;
use std::sync::Arc;

use tauri::http::{header, Request, Response, StatusCode};
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

use crate::aaf::{Aaf, PythonRunner};
use crate::api::{is_write_path, Resp, MAX_BODY, WRITE_HEADER};
use crate::{fallback_aaf, workspaces, Core};

pub const TITLE: &str = "Agent Control Room";

/// Command-line options of the app: `control-room [--root DIR] [--config DIR]`.
pub struct Options {
    pub root: Option<PathBuf>,
    pub config: PathBuf,
    /// Start in the tray without showing the window (how the login entry starts it).
    pub hidden: bool,
}

/// Size, position and maximised state are remembered; whether the window shows is the app's call.
fn state_flags() -> tauri_plugin_window_state::StateFlags {
    tauri_plugin_window_state::StateFlags::all() & !tauri_plugin_window_state::StateFlags::VISIBLE
}

fn to_response(r: Resp) -> Response<Vec<u8>> {
    Response::builder()
        .status(StatusCode::from_u16(r.status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR))
        .header(header::CONTENT_TYPE, r.ctype)
        .header(header::CACHE_CONTROL, "no-store")
        .body(r.body)
        .unwrap()
}

fn has_header(req: &Request<Vec<u8>>) -> bool {
    req.headers().get(WRITE_HEADER.0).and_then(|v| v.to_str().ok()) == Some(WRITE_HEADER.1)
}

/// "Choose a folder…": the system folder picker; the chosen folder is added and shown.
fn pick_folder(app: &tauri::AppHandle, core: &Core) -> Resp {
    use tauri_plugin_dialog::DialogExt;
    let Some(folder) = app.dialog().file().set_title("Choose your workspace folder").blocking_pick_folder() else {
        return Resp::json(&serde_json::json!({"ok": false, "cancelled": true}), 200);
    };
    let path = match folder.into_path() {
        Ok(p) => p,
        Err(_) => return Resp::json(&serde_json::json!({"ok": false, "message": "That folder cannot be used."}), 400),
    };
    match core.workspaces.add(&path, None) {
        Ok(_) => {
            let mut w = core.workspaces_json();
            w["ok"] = serde_json::json!(true);
            Resp::json(&w, 200)
        }
        Err(message) => Resp::json(&serde_json::json!({"ok": false, "message": message}), 400),
    }
}

/// A request from the window. The window is the only thing that can reach this protocol, but
/// writes still need the page's header, as over HTTP.
pub fn answer(core: &Core, req: &Request<Vec<u8>>) -> Resp {
    let path = req.uri().path().to_string();
    let query = req.uri().query().unwrap_or("").to_string();
    match req.method().as_str() {
        "GET" => core.get(&path, &query),
        "POST" => {
            if !is_write_path(&path) {
                return Resp::not_found();
            }
            if !has_header(req) {
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

/// Show the window (also when it is hidden in the tray or minimised) and bring it to the front.
pub fn show_main(app: &tauri::AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.unminimize();
        let _ = w.set_focus();
    }
}

/// Save the window's size and position, then end the app ("Quit" in the tray).
pub fn quit(app: &tauri::AppHandle) {
    use tauri_plugin_window_state::AppHandleExt;
    let _ = app.save_window_state(state_flags());
    app.exit(0);
}

type Icons = (tauri::image::Image<'static>, tauri::image::Image<'static>);

/// The base icon, and its version with a dot (the "needs you" colour) in the top right corner.
fn tray_icons() -> Icons {
    let base = tauri::image::Image::from_bytes(include_bytes!("../icons/32x32.png")).expect("tray icon");
    let (w, h) = (base.width(), base.height());
    let mut rgba = base.rgba().to_vec();
    let (cx, cy, r) = (w as f32 * 0.76, h as f32 * 0.24, w as f32 * 0.24);
    for y in 0..h {
        for x in 0..w {
            let d = ((x as f32 + 0.5 - cx).powi(2) + (y as f32 + 0.5 - cy).powi(2)).sqrt();
            let i = ((y * w + x) * 4) as usize;
            if d <= r {
                rgba[i..i + 4].copy_from_slice(&[245, 158, 11, 255]); // amber: stands out on light and dark taskbars
            } else if d <= r + 1.5 {
                rgba[i..i + 4].copy_from_slice(&[17, 24, 39, 255]); // a dark rim keeps it apart from the icon
            }
        }
    }
    (base.to_owned(), tauri::image::Image::new_owned(rgba, w, h))
}

/// What the tray shows now, kept for the test hook.
type TrayShared = Arc<std::sync::Mutex<crate::watch::TrayModel>>;

fn build_menu(app: &tauri::AppHandle, m: &crate::watch::TrayModel) -> tauri::Result<tauri::menu::Menu<tauri::Wry>> {
    use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
    let menu = Menu::new(app)?;
    for (k, (id, label)) in m.items.iter().enumerate() {
        if id == crate::watch::QUIT || (k == 1 && id.starts_with(crate::watch::WS_PREFIX)) {
            menu.append(&PredefinedMenuItem::separator(app)?)?;
        }
        menu.append(&MenuItem::with_id(app, id.as_str(), label.as_str(), true, None::<&str>)?)?;
    }
    Ok(menu)
}

/// A tray menu entry was chosen (or the test hook chose one).
fn tray_choice(app: &tauri::AppHandle, core: &Core, id: &str) {
    if id == crate::watch::QUIT {
        quit(app);
        return;
    }
    if let Some(i) = id.strip_prefix(crate::watch::WS_PREFIX).and_then(|i| i.parse::<usize>().ok()) {
        if let Some(e) = core.workspaces.list().get(i) {
            let _ = core.workspaces.select(&e.path);
        }
    }
    let a = app.clone();
    let _ = app.run_on_main_thread(move || show_main(&a));
}

/// Recount every workspace and update the tray when anything changed. Runs every 5 s.
fn refresh_tray(app: &tauri::AppHandle, core: &Core, shared: &TrayShared, icons: &Icons) {
    let m = crate::watch::tray_model(&crate::watch::counts(&core.workspaces));
    if *shared.lock().unwrap() == m {
        return;
    }
    *shared.lock().unwrap() = m.clone();
    let app2 = app.clone();
    let icon = if m.dot { icons.1.clone() } else { icons.0.clone() };
    let _ = app.run_on_main_thread(move || {
        if let Some(tray) = app2.tray_by_id("main") {
            if let Ok(menu) = build_menu(&app2, &m) {
                let _ = tray.set_menu(Some(menu));
            }
            let _ = tray.set_icon(Some(icon));
            let _ = tray.set_tooltip(Some(crate::watch::tooltip(&m)));
        }
    });
}

/// Only one app per settings folder. The first one holds `instance.lock`; a second start leaves
/// `show-request` there for the first one to show its window, and ends. Returns the held lock.
fn single_instance(config: &std::path::Path) -> Option<std::fs::File> {
    let _ = std::fs::create_dir_all(config);
    let file = std::fs::OpenOptions::new().create(true).truncate(false).write(true).open(config.join("instance.lock")).ok()?;
    if file.try_lock().is_ok() {
        let _ = std::fs::remove_file(config.join("show-request"));
        return Some(file);
    }
    #[cfg(windows)]
    unsafe {
        // Let the running app take the foreground: Windows only allows that to the app the person started.
        windows_sys::Win32::UI::WindowsAndMessaging::AllowSetForegroundWindow(u32::MAX);
    }
    let _ = std::fs::write(config.join("show-request"), b"show");
    std::process::exit(0);
}

/// Start when I log in: the autostart plugin's own status, and switching it.
fn autostart(app: &tauri::AppHandle, on: Option<bool>) -> Result<bool, String> {
    use tauri_plugin_autostart::ManagerExt;
    let l = app.autolaunch();
    match on {
        Some(true) => l.enable().map_err(|e| e.to_string())?,
        Some(false) => l.disable().map_err(|e| e.to_string())?,
        None => {}
    }
    l.is_enabled().map_err(|e| e.to_string())
}

/// Settings in the window also hold "Start when I log in" (the app's own, so not in `serve`).
fn settings(app: &tauri::AppHandle, core: &Core, req: &Request<Vec<u8>>) -> Resp {
    if req.method() == "POST" {
        let body: serde_json::Value = serde_json::from_slice(req.body()).unwrap_or(serde_json::json!({}));
        if let Some(on) = body.get("start_at_login").and_then(|v| v.as_bool()) {
            if let Err(e) = autostart(app, Some(on)) {
                return Resp::json(&serde_json::json!({"ok": false, "message": format!("Could not change it: {e}")}), 500);
            }
        }
    }
    let r = answer(core, req);
    let mut v = r.json_value();
    if !v.is_object() {
        return r;
    }
    v["start_at_login"] = autostart(app, None).map(serde_json::Value::Bool).unwrap_or(serde_json::Value::Null);
    Resp::json(&v, r.status)
}

/// Test hooks, only in debug builds (what the checks run): the tray's state, and choosing a tray entry.
#[cfg(debug_assertions)]
fn debug_hook(app: &tauri::AppHandle, core: &Core, shared: &TrayShared, req: &Request<Vec<u8>>) -> Option<Resp> {
    match (req.method().as_str(), req.uri().path()) {
        ("GET", "/api/debug/tray") => Some(Resp::json(&crate::watch::tray_json(&shared.lock().unwrap()), 200)),
        ("POST", "/api/debug/tray") if has_header(req) => {
            let body: serde_json::Value = serde_json::from_slice(req.body()).unwrap_or_default();
            let id = body.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string();
            if id == crate::watch::QUIT {
                let app = app.clone(); // answer first, then quit
                std::thread::spawn(move || {
                    std::thread::sleep(std::time::Duration::from_millis(200));
                    quit(&app);
                });
            } else {
                tray_choice(app, core, &id);
            }
            Some(Resp::json(&serde_json::json!({"ok": true}), 200))
        }
        _ => None,
    }
}
#[cfg(not(debug_assertions))]
fn debug_hook(_: &tauri::AppHandle, _: &Core, _: &TrayShared, _: &Request<Vec<u8>>) -> Option<Resp> {
    None
}

pub fn run(opts: Options) {
    let lock = single_instance(&opts.config);
    let settings_file = workspaces::load_settings(&opts.config);
    let runner = PythonRunner::new(workspaces::python_path(&settings_file));
    let mut core = Core::with_workspaces(opts.root.clone(), Aaf::new(Box::new(runner), None, fallback_aaf()), opts.config.clone());
    core.can_pick = true;
    let core = Arc::new(core);
    let shared: TrayShared = Arc::new(std::sync::Mutex::new(Default::default()));
    let (proto_core, proto_shared) = (core.clone(), shared.clone());
    let (setup_core, setup_shared) = (core.clone(), shared.clone());
    let config = opts.config.clone();
    let hidden = opts.hidden;
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_window_state::Builder::default()
            .with_filename(config.join("window-state.json").to_string_lossy())
            .with_state_flags(state_flags())
            .build())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_autostart::init(tauri_plugin_autostart::MacosLauncher::LaunchAgent, Some(vec!["--hidden"])))
        .register_asynchronous_uri_scheme_protocol("app", move |ctx, req, responder| {
            let (core, shared) = (proto_core.clone(), proto_shared.clone());
            let app = ctx.app_handle().clone();
            std::thread::spawn(move || {
                let path = req.uri().path().to_string();
                let r = if let Some(r) = debug_hook(&app, &core, &shared, &req) {
                    r
                } else if req.method() == "POST" && path == "/api/workspaces/pick" && has_header(&req) {
                    pick_folder(&app, &core)
                } else if path == "/api/settings" && (req.method() == "GET" || has_header(&req)) {
                    settings(&app, &core, &req)
                } else {
                    answer(&core, &req)
                };
                responder.respond(to_response(r))
            });
        })
        .on_window_event(|window, event| {
            // Closing the window keeps the app running in the tray; "Quit" in the tray ends it.
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .setup(move |app| {
            let url = WebviewUrl::CustomProtocol("app://localhost/".parse().unwrap());
            WebviewWindowBuilder::new(app, "main", url)
                .title(TITLE)
                .inner_size(1280.0, 800.0)
                .min_inner_size(390.0, 500.0)
                .data_directory(config.join("webview"))
                .visible(!hidden)
                .build()?;
            let icons = tray_icons();
            let menu_core = setup_core.clone();
            let menu = build_menu(app.handle(), &crate::watch::tray_model(&[]))?;
            tauri::tray::TrayIconBuilder::with_id("main")
                .icon(icons.0.clone())
                .tooltip(TITLE)
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(move |app, event| tray_choice(app, &menu_core, event.id().as_ref()))
                .on_tray_icon_event(|tray, event| {
                    if let tauri::tray::TrayIconEvent::Click {
                        button: tauri::tray::MouseButton::Left,
                        button_state: tauri::tray::MouseButtonState::Up,
                        ..
                    } = event
                    {
                        show_main(tray.app_handle());
                    }
                })
                .build(app)?;
            // Every 5 s: recount the tray. Every 0.3 s: has a second start asked for the window?
            let (app_h, core_t, shared_t, config_t) = (app.handle().clone(), setup_core.clone(), setup_shared.clone(), config.clone());
            std::thread::spawn(move || {
                let mut last: Option<std::time::Instant> = None;
                loop {
                    if last.map(|t| t.elapsed() >= std::time::Duration::from_secs(5)).unwrap_or(true) {
                        refresh_tray(&app_h, &core_t, &shared_t, &icons);
                        last = Some(std::time::Instant::now());
                    }
                    let req = config_t.join("show-request");
                    if req.exists() {
                        let _ = std::fs::remove_file(&req);
                        let a = app_h.clone();
                        let _ = app_h.run_on_main_thread(move || show_main(&a));
                    }
                    std::thread::sleep(std::time::Duration::from_millis(300));
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("the app could not start");
    app.run(move |_app, _event| {
        let _ = &lock; // held for as long as the app runs
    });
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
