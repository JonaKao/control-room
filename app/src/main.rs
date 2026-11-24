//! `control-room serve --root <workspace> [--port N] [--clock ISO] [--config DIR]`: the core's
//! router over HTTP on 127.0.0.1, with no window (for the checks and GitHub Actions).

use std::path::PathBuf;
use std::sync::Arc;

use control_room::aaf::{Aaf, PythonRunner};
use control_room::{api, fallback_aaf, workspaces, Core};

fn usage() -> ! {
    eprintln!("usage: control-room serve --root <workspace> [--port N] [--clock ISO] [--config DIR]");
    std::process::exit(2);
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.first().map(|s| s.as_str()) != Some("serve") {
        usage();
    }
    let mut root: Option<PathBuf> = None;
    let mut port: u16 = 8765;
    let mut clock: Option<String> = None;
    let mut config: Option<PathBuf> = None;
    let mut it = args.iter().skip(1);
    while let Some(a) = it.next() {
        let mut val = || it.next().cloned().unwrap_or_else(|| usage());
        match a.as_str() {
            "--root" => root = Some(PathBuf::from(val())),
            "--port" => port = val().parse().unwrap_or_else(|_| usage()),
            "--clock" => clock = Some(val()),
            "--config" => config = Some(PathBuf::from(val())),
            _ => usage(),
        }
    }
    let Some(root) = root else { usage() };
    let config = config.unwrap_or_else(workspaces::default_config_dir);
    let settings = workspaces::load_settings(&config);
    let runner = PythonRunner::new(workspaces::python_path(&settings));
    let core = Arc::new(Core::new(root, Aaf::new(Box::new(runner), clock, fallback_aaf()), config));
    let rt = tokio::runtime::Builder::new_multi_thread().enable_all().build().expect("tokio runtime");
    if let Err(e) = rt.block_on(api::serve(core, port)) {
        eprintln!("control-room serve: {}", e);
        std::process::exit(1);
    }
}
