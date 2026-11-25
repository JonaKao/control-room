#!/usr/bin/env python3
"""Build the Agent Control Room desktop app and put its installer in dist/.

    python3 build.py           build the release app and copy the installer to dist/
    python3 build.py --icons   only make app/icons/ again from design/icon.svg

What a build does:
1. Makes every icon size in app/icons/ from design/icon.svg when the SVG is newer than the icons
   (drawn by a headless browser: needs Playwright, see checks/render.py).
2. Raises the version by one patch number (app/tauri.conf.json and app/Cargo.toml) when it is not
   higher than the last version built, so every installer has a new version.
3. Runs `cargo tauri build` (the Tauri CLI: `cargo install tauri-cli --version "^2" --locked`).
4. Copies the installer to dist/ (on Windows `Agent Control Room_<version>_x64-setup.exe`) and notes
   the build in dist/builds.json.
"""
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time

PROJECT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(PROJECT, "app")
ICONS = os.path.join(APP, "icons")
SVG = os.path.join(PROJECT, "design", "icon.svg")
DIST = os.path.join(PROJECT, "dist")
CONF = os.path.join(APP, "tauri.conf.json")
CARGO_TOML = os.path.join(APP, "Cargo.toml")
BUILDS = os.path.join(DIST, "builds.json")
PNG_SIZES = {"32x32.png": 32, "64x64.png": 64, "128x128.png": 128, "128x128@2x.png": 256, "icon.png": 512}
ICO_SIZES = (16, 24, 32, 48, 64, 256)
ICNS = (("ic11", 32), ("ic12", 64), ("ic07", 128), ("ic13", 256), ("ic08", 256), ("ic14", 512), ("ic09", 512), ("ic10", 1024))


def cargo():
    found = shutil.which("cargo")
    if found:
        return found
    return os.path.join(os.path.expanduser("~"), ".cargo", "bin", "cargo" + (".exe" if os.name == "nt" else ""))


def render_pngs(sizes):
    """design/icon.svg as PNG bytes at each size (transparent around the rounded square)."""
    from playwright.sync_api import sync_playwright
    with open(SVG, encoding="utf-8") as f:
        svg = f.read()
    out = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for n in sorted(set(sizes)):
            page = browser.new_page(viewport={"width": n, "height": n}, device_scale_factor=1)
            sized = re.sub(r'width="\d+" height="\d+"', 'width="%d" height="%d"' % (n, n), svg, count=1)
            page.set_content('<html><body style="margin:0;background:transparent">%s</body></html>' % sized)
            out[n] = page.screenshot(omit_background=True, clip={"x": 0, "y": 0, "width": n, "height": n})
            page.close()
        browser.close()
    return out


def ico(pngs):
    """A Windows .ico holding PNG images."""
    head = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    entries, data = b"", b""
    for n, png in pngs:
        entries += struct.pack("<BBBBHHII", n % 256, n % 256, 0, 0, 1, 32, len(png), offset + len(data))
        data += png
    return head + entries + data


def icns(parts):
    """A macOS .icns holding PNG images."""
    body = b"".join(kind.encode() + struct.pack(">I", len(png) + 8) + png for kind, png in parts)
    return b"icns" + struct.pack(">I", len(body) + 8) + body


def make_icons():
    pngs = render_pngs(list(PNG_SIZES.values()) + list(ICO_SIZES) + [n for _, n in ICNS])
    os.makedirs(ICONS, exist_ok=True)
    for name, n in PNG_SIZES.items():
        with open(os.path.join(ICONS, name), "wb") as f:
            f.write(pngs[n])
    with open(os.path.join(ICONS, "icon.ico"), "wb") as f:
        f.write(ico([(n, pngs[n]) for n in ICO_SIZES]))
    with open(os.path.join(ICONS, "icon.icns"), "wb") as f:
        f.write(icns([(k, pngs[n]) for k, n in ICNS]))
    print("Icons made from design/icon.svg: %s, icon.ico, icon.icns" % ", ".join(PNG_SIZES))


def icons_stale():
    files = [os.path.join(ICONS, n) for n in list(PNG_SIZES) + ["icon.ico", "icon.icns"]]
    return any(not os.path.isfile(f) or os.path.getmtime(f) < os.path.getmtime(SVG) for f in files)


def version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def read_builds():
    try:
        with open(BUILDS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def current_version():
    with open(CONF, encoding="utf-8") as f:
        return json.load(f)["version"]


def set_version(v):
    with open(CONF, encoding="utf-8") as f:
        text = f.read()
    text = re.sub(r'"version":\s*"[^"]+"', '"version": "%s"' % v, text, count=1)
    with open(CONF, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    with open(CARGO_TOML, encoding="utf-8") as f:
        toml = f.read()
    toml = re.sub(r'(?m)^version = "[^"]+"', 'version = "%s"' % v, toml, count=1)
    with open(CARGO_TOML, "w", encoding="utf-8", newline="\n") as f:
        f.write(toml)


def bump_if_needed():
    """A new installer always gets a version above the last one built."""
    v = current_version()
    builds = read_builds()
    last = max((b["version"] for b in builds), key=version_tuple, default=None)
    if last and version_tuple(v) <= version_tuple(last):
        major, minor, patch = version_tuple(last)
        v = "%d.%d.%d" % (major, minor, patch + 1)
        set_version(v)
        print("Version raised to %s (the last build was %s)" % (v, last))
    return v


def installer_name(v):
    if os.name == "nt":
        return "Agent Control Room_%s_x64-setup.exe" % v
    if sys.platform == "darwin":
        return None  # the .dmg name depends on the machine; found below
    return None


def build():
    if icons_stale():
        make_icons()
    v = bump_if_needed()
    env = dict(os.environ, PATH=os.path.dirname(cargo()) + os.pathsep + os.environ.get("PATH", ""))
    started = time.time()
    proc = subprocess.run([cargo(), "tauri", "build"], cwd=APP, env=env)
    if proc.returncode != 0:
        print("FAIL: cargo tauri build ended with %d" % proc.returncode)
        return 1
    bundle = os.path.join(APP, "target", "release", "bundle")
    if os.name == "nt":
        src = os.path.join(bundle, "nsis", installer_name(v))
    else:
        found = [os.path.join(bundle, "dmg", f) for f in os.listdir(os.path.join(bundle, "dmg")) if f.endswith(".dmg") and v in f]
        src = found[0] if found else ""
    if not os.path.isfile(src):
        print("FAIL: the installer was not made: %s" % src)
        return 1
    os.makedirs(DIST, exist_ok=True)
    dst = os.path.join(DIST, os.path.basename(src))
    shutil.copy2(src, dst)
    builds = read_builds()
    builds.append({"version": v, "file": os.path.basename(dst), "bytes": os.path.getsize(dst),
                   "built": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "seconds": round(time.time() - started)})
    with open(BUILDS, "w", encoding="utf-8") as f:
        json.dump(builds, f, indent=2)
    print("Built %s (%.1f MB) in dist/" % (os.path.basename(dst), os.path.getsize(dst) / 1e6))
    return 0


if __name__ == "__main__":
    if "--icons" in sys.argv[1:]:
        make_icons()
        sys.exit(0)
    sys.exit(build())
