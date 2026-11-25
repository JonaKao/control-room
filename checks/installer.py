"""Installer: `python3 build.py` made a Windows installer for the current version, set up the way the
spec asks (Windows only; elsewhere this check says it was skipped).

- dist/Agent Control Room_<version>_x64-setup.exe exists for the version in app/tauri.conf.json and
  app/Cargo.toml (the same), and dist/builds.json records it as the newest build;
- each build has a higher version than the one before it;
- the installer installs for this user only, without admin rights (installMode currentUser, and the
  generated NSIS script asks for user level), with a Start-menu entry and a desktop icon;
- every icon in app/icons/ was made from design/icon.svg (not older than it), the .ico holds 16 to
  256 px and the .icns the Mac sizes.
"""
import json
import os
import re
import struct
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(PROJECT, "app")
problems = []


def vt(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def ico_sizes(path):
    with open(path, "rb") as f:
        data = f.read()
    _, kind, count = struct.unpack("<HHH", data[:6])
    return sorted((data[6 + 16 * i] or 256) for i in range(count)) if kind == 1 else []


def icns_types(path):
    with open(path, "rb") as f:
        data = f.read()
    out, i = [], 8
    while i + 8 <= len(data):
        kind, size = data[i:i + 4].decode("latin-1"), struct.unpack(">I", data[i + 4:i + 8])[0]
        out.append(kind)
        i += max(size, 8)
    return out if data[:4] == b"icns" else []


def main():
    if os.name != "nt":
        print("SKIP: the Windows installer is built and checked on Windows")
        return 0
    with open(os.path.join(APP, "tauri.conf.json"), encoding="utf-8") as f:
        conf = json.load(f)
    v = conf["version"]
    with open(os.path.join(APP, "Cargo.toml"), encoding="utf-8") as f:
        cargo_v = re.search(r'(?m)^version = "([^"]+)"', f.read()).group(1)
    if cargo_v != v:
        problems.append("version: tauri.conf.json says %s, Cargo.toml %s" % (v, cargo_v))

    # The installer for this version, and the build record.
    name = "Agent Control Room_%s_x64-setup.exe" % v
    path = os.path.join(PROJECT, "dist", name)
    if not os.path.isfile(path):
        problems.append("dist/%s is missing: run python3 build.py" % name)
    elif os.path.getsize(path) < 1_000_000:
        problems.append("dist/%s is only %d bytes" % (name, os.path.getsize(path)))
    try:
        with open(os.path.join(PROJECT, "dist", "builds.json"), encoding="utf-8") as f:
            builds = json.load(f)
    except (OSError, ValueError):
        builds = []
    if not builds or builds[-1].get("version") != v or builds[-1].get("file") != name:
        problems.append("dist/builds.json does not name %s as the newest build (%r)" % (name, builds[-1:] or None))
    for a, b in zip(builds, builds[1:]):
        if vt(b["version"]) <= vt(a["version"]):
            problems.append("build %s came after %s without a higher version" % (b["version"], a["version"]))

    # Per user, no admin, Start menu and desktop.
    nsis = conf.get("bundle", {}).get("windows", {}).get("nsis", {})
    if nsis.get("installMode") != "currentUser":
        problems.append("the installer is not set to install for this user only (installMode %r)" % nsis.get("installMode"))
    script_path = os.path.join(APP, "target", "release", "nsis", "x64", "installer.nsi")
    script = open(script_path, encoding="utf-8", errors="replace").read() if os.path.isfile(script_path) else ""
    if not script:
        problems.append("the generated installer script is missing (app/target/release/nsis/x64/installer.nsi)")
    else:
        if not re.search(r"RequestExecutionLevel\s+user", script) and "currentUser" not in script:
            problems.append("the installer script does not ask for user level only")
        if not re.search(r'CreateShortcut\s+"\$SMPROGRAMS', script, re.I):
            problems.append("the installer script makes no Start-menu entry")
        # The desktop icon must not depend on a box being ticked on Tauri's finish page: our hook makes it
        # after every install. So: the config names the hook file, the hook makes the $DESKTOP shortcut in
        # NSIS_HOOK_POSTINSTALL, and the generated script includes the file and runs that hook.
        hooks = nsis.get("installerHooks")
        hook_path = os.path.normpath(os.path.join(APP, hooks)) if hooks else ""
        hook_text = open(hook_path, encoding="utf-8").read() if hook_path and os.path.isfile(hook_path) else ""
        post = re.search(r"!macro\s+NSIS_HOOK_POSTINSTALL(.*?)!macroend", hook_text, re.S)
        if not hooks or not hook_text:
            problems.append("the installer has no hook file that makes the desktop icon (bundle.windows.nsis.installerHooks)")
        elif not post or not re.search(r'(?mi)^\s*CreateShortcut\s+"\$DESKTOP', post.group(1)):  # a line of its own, not a comment
            problems.append("the installer hook does not make the desktop icon after install (NSIS_HOOK_POSTINSTALL)")
        elif (not re.search(r'!include\s+"[^"]*%s"' % re.escape(os.path.basename(hook_path)), script)
              or not re.search(r"(?m)^\s*!insertmacro\s+NSIS_HOOK_POSTINSTALL", script)):
            problems.append("the generated installer script does not include and run the desktop-icon hook: rebuild with build.py")

    # Icons from design/icon.svg.
    svg = os.path.join(PROJECT, "design", "icon.svg")
    for rel in conf.get("bundle", {}).get("icon", []):
        p = os.path.join(APP, rel)
        if not os.path.isfile(p):
            problems.append("icon %s is missing" % rel)
        elif os.path.getmtime(p) + 1 < os.path.getmtime(svg):
            problems.append("icon %s is older than design/icon.svg: run python3 build.py --icons" % rel)
    ico = os.path.join(APP, "icons", "icon.ico")
    if os.path.isfile(ico) and not {16, 32, 48, 256} <= set(ico_sizes(ico)):
        problems.append("icon.ico holds %s, expected 16 to 256 px" % ico_sizes(ico))
    icns = os.path.join(APP, "icons", "icon.icns")
    if os.path.isfile(icns) and not {"ic07", "ic08", "ic09", "ic10"} <= set(icns_types(icns)):
        problems.append("icon.icns holds %s, expected the Mac sizes 128 to 1024 px" % icns_types(icns))

    if problems:
        print("FAIL: installer:")
        for p in problems:
            print("  -", p)
        return 1
    print("OK: dist/%s (version %s, %d build(s) so far), per user, Start-menu entry and desktop icon, icons from design/icon.svg"
          % (name, v, len(builds)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
