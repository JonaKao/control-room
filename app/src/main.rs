//! `control-room`: the desktop app (a window showing the page, served by the core without a
//! network port), or `control-room serve ...`: the same core over HTTP on 127.0.0.1, with no
//! window, for the checks and GitHub Actions.
//!
//!   control-room [--root <workspace>] [--config DIR] [--hidden]
//!   control-room serve [--root <workspace>] [--port N] [--clock ISO] [--config DIR]
//!
//! Without --root both show the workspaces saved in the settings (a welcome screen when there are none);
//! with it, that workspace is shown first, for this run only.
#![cfg_attr(all(windows, not(debug_assertions)), windows_subsystem = "windows")]

use std::path::PathBuf;
use std::sync::Arc;

use control_room::aaf::{Aaf, PythonRunner};
use control_room::{api, desktop, fallback_aaf, workspaces, Core};

fn usage() -> ! {
    eprintln!("usage: control-room [--root <workspace>] [--config DIR]\n       control-room serve --root <workspace> [--port N] [--clock ISO] [--config DIR]");
    std::process::exit(2);
}

struct Args {
    serve: bool,
    root: Option<PathBuf>,
    port: u16,
    clock: Option<String>,
    config: Option<PathBuf>,
    hidden: bool,
}

fn parse() -> Args {
    let mut args: Vec<String> = std::env::args().skip(1).collect();
    let serve = args.first().map(|s| s == "serve").unwrap_or(false);
    if serve {
        args.remove(0);
    }
    let mut a = Args { serve, root: None, port: 8765, clock: None, config: None, hidden: false };
    let mut it = args.into_iter();
    while let Some(flag) = it.next() {
        let mut val = || it.next().unwrap_or_else(|| usage());
        match flag.as_str() {
            "--root" => a.root = Some(PathBuf::from(val())),
            "--port" if serve => a.port = val().parse().unwrap_or_else(|_| usage()),
            "--clock" if serve => a.clock = Some(val()),
            "--config" => a.config = Some(PathBuf::from(val())),
            "--hidden" if !serve => a.hidden = true,
            _ => usage(),
        }
    }
    a
}

fn main() {
    let a = parse();
    let config = a.config.unwrap_or_else(workspaces::default_config_dir);
    if !a.serve {
        desktop::run(desktop::Options { root: a.root, config, hidden: a.hidden });
        return;
    }
    let settings = workspaces::load_settings(&config);
    let runner = PythonRunner::new(workspaces::python_path(&settings));
    let core = Arc::new(Core::with_workspaces(a.root, Aaf::new(Box::new(runner), a.clock, fallback_aaf()), config));
    // Watch every workspace every 5 s, as the app does, so /api/events works without a window.
    let watcher = core.clone();
    std::thread::spawn(move || loop {
        watcher.watch_once();
        std::thread::sleep(std::time::Duration::from_secs(5));
    });
    let rt = tokio::runtime::Builder::new_multi_thread().enable_all().build().expect("tokio runtime");
    if let Err(e) = rt.block_on(api::serve(core, a.port)) {
        eprintln!("control-room serve: {}", e);
        std::process::exit(1);
    }
}
