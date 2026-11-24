"""Start the Rust core's `control-room serve` for the checks and tests.

    with app_server.serve(root, clock=NOW) as base:   # base = "http://127.0.0.1:<port>"
        ...

Builds the app once per process (`cargo build`, incremental, so quick when nothing changed),
then runs `control-room serve --root <root> --port 0 [--clock ISO] --config <temporary folder>`,
so a check never touches the real settings. The process ends when the block ends.
"""
import contextlib
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
APP = os.path.join(PROJECT, "app")
EXE = os.path.join(APP, "target", "debug", "control-room" + (".exe" if os.name == "nt" else ""))
_built = False


def cargo():
    found = shutil.which("cargo")
    if found:
        return found
    path = os.path.join(os.path.expanduser("~"), ".cargo", "bin", "cargo" + (".exe" if os.name == "nt" else ""))
    if os.path.isfile(path):
        return path
    raise RuntimeError("cargo not found: install Rust (rustup) to build the app")


def build():
    """Build the app (debug) once per process; return the program's path."""
    global _built
    if not _built:
        proc = subprocess.run([cargo(), "build", "--quiet"], cwd=APP, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            raise RuntimeError("cargo build failed:\n" + proc.stderr[-3000:])
        _built = True
    return EXE


class Served:
    """A running `control-room serve`."""

    def __init__(self, root, clock=None, config=None, extra=(), cwd=None):
        exe = build()
        self.own_config = config is None
        self.config = config or tempfile.mkdtemp(prefix="aaf-config-")
        args = [exe, "serve", "--root", root, "--port", "0", "--config", self.config] + list(extra)
        if clock:
            args += ["--clock", clock]
        self.proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                     encoding="utf-8", errors="replace", cwd=cwd)
        line = self.proc.stdout.readline().strip()
        if not line.startswith("Serving on "):
            err = self.proc.stderr.read() if self.proc.poll() is not None else ""
            self.stop()
            raise RuntimeError("control-room serve did not start: %r %s" % (line, err))
        self.base = line[len("Serving on "):]
        self.port = int(self.base.rsplit(":", 1)[1])

    def stop(self):
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()
        for f in (self.proc.stdout, self.proc.stderr):
            if f:
                f.close()
        if self.own_config:
            shutil.rmtree(self.config, ignore_errors=True)


@contextlib.contextmanager
def serve(root, clock=None, config=None, extra=()):
    s = Served(root, clock=clock, config=config, extra=extra)
    try:
        yield s.base
    finally:
        s.stop()


if __name__ == "__main__":
    with serve(sys.argv[1] if len(sys.argv) > 1 else os.path.join(PROJECT, "fixtures", "workspace")) as base:
        print(base)
        input("Press Enter to stop. ")
