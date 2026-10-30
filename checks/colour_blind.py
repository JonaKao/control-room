"""Check the colour-blind mode: a second switch in the rail that swaps the seven state colours
(--plan, --change, --test, --review, --polish, --pass, --fail) for a palette people with colour
blindness can tell apart, in the dark and the light theme.

- The switch (#palette) is off by default (the DESIGN.md colours stay), says what it does to a
  screen reader, shows its state (aria-pressed), and is remembered after a reload (aaf.palette).
- With it on, the tokens are the colour-blind ones in DESIGN.md, in both themes, and together with
  either theme choice.
- The palette works: simulated for protanopia, deuteranopia and tritanopia (Machado, Oliveira and
  Fernandes 2009, full severity) and for normal vision, every pair of the seven colours is at least
  MIN_DE apart (CIEDE2000), and each colour has at least 3:1 contrast against the panel. The same
  measurement must flag the default palette (so it is known to see the problem).
- The page uses them: the loop stepper, the live steps and the timeline draw each phase in its
  colour-blind token.
- Every fixture renders without JavaScript errors in the mode, and a phone (390 px) does not scroll
  sideways.
Screenshots: plots/render-colourblind-*.png, including the page as someone with deuteranopia sees
it, with the default colours and with the mode on.
"""
import itertools
import math
import os
import re
import sys
import threading
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT)
sys.path.insert(0, HERE)
import server  # noqa: E402
from layout import FIXTURES, PLOTS, PHASE_TOKEN, TOKENS, open_page, resolved, sync_playwright  # noqa: E402

STATES = ["--plan", "--change", "--test", "--review", "--polish", "--pass", "--fail"]
CB_TOKENS = {  # DESIGN.md "Colour-blind mode", dark then light
    "--plan": ("#919FB8", "#8F908D"), "--change": ("#6FE2DA", "#0B7A8C"), "--test": ("#F2E14A", "#B07F05"),
    "--review": ("#D0ADFF", "#8655FF"), "--polish": ("#F84E9D", "#8E2F55"), "--pass": ("#5084F1", "#1E449A"),
    "--fail": ("#F09862", "#BB1A02"),
}
MIN_DE = 12
MIN_CONTRAST = 3.0
# Linear-RGB matrices, Machado et al. 2009, severity 1.0.
CVD = {
    "protanopia": [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
    "deuteranopia": [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]],
    "tritanopia": [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.303900]],
}


def channels(hexcode):
    h = hexcode.lstrip("#")
    return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]


def linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def seen(hexcode, vision):
    lin = [linear(c) for c in channels(hexcode)]
    if vision == "normal":
        return lin
    return [max(0.0, min(1.0, sum(m * v for m, v in zip(row, lin)))) for row in CVD[vision]]


def lab(lin):
    x = (0.4124 * lin[0] + 0.3576 * lin[1] + 0.1805 * lin[2]) / 0.95047
    y = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    z = (0.0193 * lin[0] + 0.1192 * lin[1] + 0.9505 * lin[2]) / 1.08883
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116  # noqa: E731
    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def ciede2000(p, q):
    (l1, a1, b1), (l2, a2, b2) = p, q
    cbar = (math.hypot(a1, b1) + math.hypot(a2, b2)) / 2
    g = 0.5 * (1 - math.sqrt(cbar ** 7 / (cbar ** 7 + 25 ** 7)))
    a1, a2 = a1 * (1 + g), a2 * (1 + g)
    c1, c2 = math.hypot(a1, b1), math.hypot(a2, b2)
    h1, h2 = math.degrees(math.atan2(b1, a1)) % 360, math.degrees(math.atan2(b2, a2)) % 360
    dh = 0 if c1 * c2 == 0 else (h2 - h1 if abs(h2 - h1) <= 180 else h2 - h1 - 360 if h2 > h1 else h2 - h1 + 360)
    dl, dc = l2 - l1, c2 - c1
    dhh = 2 * math.sqrt(c1 * c2) * math.sin(math.radians(dh / 2))
    lbar, cb = (l1 + l2) / 2, (c1 + c2) / 2
    if c1 * c2 == 0:
        hbar = h1 + h2
    elif abs(h1 - h2) <= 180:
        hbar = (h1 + h2) / 2
    else:
        hbar = (h1 + h2 + 360) / 2 if h1 + h2 < 360 else (h1 + h2 - 360) / 2
    t = (1 - 0.17 * math.cos(math.radians(hbar - 30)) + 0.24 * math.cos(math.radians(2 * hbar))
         + 0.32 * math.cos(math.radians(3 * hbar + 6)) - 0.2 * math.cos(math.radians(4 * hbar - 63)))
    sl = 1 + 0.015 * (lbar - 50) ** 2 / math.sqrt(20 + (lbar - 50) ** 2)
    sc, sh = 1 + 0.045 * cb, 1 + 0.015 * cb * t
    rt = -2 * math.sqrt(cb ** 7 / (cb ** 7 + 25 ** 7)) * math.sin(math.radians(60 * math.exp(-((hbar - 275) / 25) ** 2)))
    return math.sqrt((dl / sl) ** 2 + (dc / sc) ** 2 + (dhh / sh) ** 2 + rt * (dc / sc) * (dhh / sh))


def contrast(a, b):
    lum = lambda h: sum(w * linear(c) for w, c in zip((0.2126, 0.7152, 0.0722), channels(h)))  # noqa: E731
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def palette_problems(pal, panel, label):
    """Pairs of state colours that run together for some vision, and colours too faint on the panel."""
    bad = []
    for vision in ["normal"] + list(CVD):
        seen_as = {k: lab(seen(v, vision)) for k, v in pal.items()}
        for a, b in itertools.combinations(pal, 2):
            d = ciede2000(seen_as[a], seen_as[b])
            if d < MIN_DE:
                bad.append("%s, %s: %s and %s are only %.1f apart (need %d)" % (label, vision, a, b, d, MIN_DE))
    for k, v in pal.items():
        c = contrast(v, panel)
        if c < MIN_CONTRAST:
            bad.append("%s: %s has %.2f:1 against the panel (need %.0f:1)" % (label, k, c, MIN_CONTRAST))
    return bad


def tokens(page, names):
    return page.evaluate("names => { const cs = getComputedStyle(document.documentElement);"
                         " return Object.fromEntries(names.map(n => [n, cs.getPropertyValue(n).trim().toUpperCase()])); }", names)


def pressed(page):
    return page.evaluate("() => { const b = document.querySelector('#palette'); return b && b.getAttribute('aria-pressed'); }")


def check_measurement():
    """The measurement itself: it must catch the default palette and pass the DESIGN.md colour-blind one."""
    bad = []
    for i, theme in enumerate(("dark", "light")):
        default = {k: TOKENS[k][i] for k in STATES}
        if not palette_problems(default, TOKENS["--panel"][i], theme):
            bad.append("measurement: the default %s palette passes, so the simulation does not see the problem" % theme)
        bad += palette_problems({k: CB_TOKENS[k][i] for k in STATES}, TOKENS["--panel"][i], "colour-blind " + theme)
    with open(os.path.join(PROJECT, "design", "DESIGN.md")) as f:
        design = f.read()
    part = design[design.find("## Colour-blind mode"):] if "## Colour-blind mode" in design else ""
    if not part:
        bad.append("DESIGN.md has no 'Colour-blind mode' section")
    for k, (dark, light) in CB_TOKENS.items():
        if not re.search(r"`%s`\s*\|\s*`%s`\s*\|\s*`%s`" % (k, dark, light), part, re.I):
            bad.append("DESIGN.md's colour-blind table does not give %s as %s / %s" % (k, dark, light))
    return bad


def check_switch(browser, base):
    bad = []
    ctx, page, errors = open_page(browser, base, "image-classifier")
    sw = page.query_selector("#palette")
    if not sw:
        ctx.close()
        return ["switch: no colour-blind switch (#palette) in the rail"]
    if not page.query_selector("nav.rail #palette"):
        bad.append("switch: #palette is not in the rail")
    name = (sw.get_attribute("aria-label") or sw.inner_text() or "").lower()
    if "colour-blind" not in name and "color-blind" not in name and "colour blind" not in name:
        bad.append("switch: its label %r does not say it is about colour blindness" % name)
    if sw.get_attribute("aria-pressed") != "false":
        bad.append("switch: aria-pressed is %r by default, not 'false'" % sw.get_attribute("aria-pressed"))
    got = tokens(page, STATES)
    for k in STATES:
        if got[k] != TOKENS[k][0].upper():
            bad.append("switch off: dark %s is %s, not the DESIGN.md default %s" % (k, got[k], TOKENS[k][0]))
    page.click("#palette")
    page.wait_for_timeout(150)
    if pressed(page) != "true":
        bad.append("switch: aria-pressed does not become 'true' when turned on")
    for theme, i in (("dark", 0), ("light", 1)):
        if theme == "light":
            page.click("#theme")
            page.wait_for_timeout(150)
        got = tokens(page, STATES + ["--panel"])
        for k in STATES:
            if got[k] != CB_TOKENS[k][i].upper():
                bad.append("switch on, %s: %s is %s, not the colour-blind %s" % (theme, k, got[k], CB_TOKENS[k][i]))
        if got["--panel"] != TOKENS["--panel"][i].upper():
            bad.append("switch on, %s: the surfaces changed too (--panel %s)" % (theme, got["--panel"]))
    page.reload()
    page.wait_for_selector('[data-section="glance"]')
    page.wait_for_timeout(300)
    if pressed(page) != "true" or tokens(page, ["--pass"])["--pass"] != CB_TOKENS["--pass"][1].upper():
        bad.append("switch: the colour-blind choice is not remembered after a reload")
    page.click("#palette")
    page.wait_for_timeout(150)
    got = tokens(page, STATES)
    for k in STATES:
        if got[k] != TOKENS[k][1].upper():
            bad.append("switch off again, light: %s is %s, not the default %s" % (k, got[k], TOKENS[k][1]))
    bad += ["switch: JavaScript error: %s" % e for e in errors[:3]]
    ctx.close()
    return bad


def check_used(browser, base):
    """Each phase is drawn in its colour-blind token: loop stepper, live steps and timeline."""
    bad = []
    for theme, i in (("dark", 0), ("light", 1)):
        ctx, page, _ = open_page(browser, base, "image-classifier", storage={"aaf.theme": theme, "aaf.palette": "cb"})
        want = {p: resolved(page, t) for p, t in PHASE_TOKEN.items()}
        for p, t in PHASE_TOKEN.items():
            h = CB_TOKENS[t][i].lstrip("#")
            if want[p] != "rgb(%d, %d, %d)" % tuple(int(h[j:j + 2], 16) for j in (0, 2, 4)):
                bad.append("%s: %s resolves to %s, not the colour-blind %s" % (theme, t, want[p], CB_TOKENS[t][i]))
        segs = page.eval_on_selector_all("[data-seg]", "els => els.map(e => [e.dataset.phase, getComputedStyle(e).backgroundColor])")
        if not segs:
            bad.append("%s: no timeline segments to compare" % theme)
        for ph, bg in segs:
            if ph in want and bg != want[ph]:
                bad.append("%s: timeline draws %s in %s, not %s" % (theme, ph, bg, want[ph]))
        node = page.eval_on_selector('[data-viz="loop"] [aria-current="step"] .node', "e => getComputedStyle(e).backgroundColor")
        if node != want["checking"]:
            bad.append("%s: the loop stepper draws testing in %s, not %s" % (theme, node, want["checking"]))
        icons = page.eval_on_selector_all("[data-section=live] [data-kind=edit] .kicon", "els => els.map(e => getComputedStyle(e).backgroundColor)")
        if not icons or any(c != want["implementing"] for c in icons):
            bad.append("%s: 'making a change' steps are not drawn in %s: %s" % (theme, want["implementing"], icons))
        page.screenshot(path=os.path.join(PLOTS, "render-colourblind-desktop-%s.png" % theme))
        ctx.close()
    return bad


def simulate(page, vision):
    """Show the page as someone with this kind of colour blindness sees it (SVG filters work in linear RGB)."""
    m = CVD[vision]
    values = " ".join(" ".join("%g" % v for v in row) + " 0 0" for row in m) + " 0 0 0 1 0"
    page.evaluate("""v => { const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        s.setAttribute('style', 'position:absolute;width:0;height:0');
        s.innerHTML = '<filter id="cvd-sim"><feColorMatrix type="matrix" values="' + v + '"/></filter>';
        document.body.appendChild(s); document.documentElement.style.filter = 'url(#cvd-sim)'; }""", values)
    page.wait_for_timeout(200)


def main():
    server.set_root(FIXTURES)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    base = "http://127.0.0.1:%d" % httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    os.makedirs(PLOTS, exist_ok=True)
    names = sorted(n for n in os.listdir(os.path.join(FIXTURES, "projects")) if not n.startswith("."))
    problems = check_measurement()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        problems += check_switch(browser, base)
        problems += check_used(browser, base)
        for name in names:
            for theme in ("dark", "light"):
                ctx, page, errors = open_page(browser, base, name, storage={"aaf.theme": theme, "aaf.palette": "cb"})
                if pressed(page) != "true":
                    problems.append("%s/%s: the mode is not on with aaf.palette = cb" % (name, theme))
                problems += ["%s/%s: JavaScript error: %s" % (name, theme, e) for e in errors[:3]]
                ctx.close()
            ctx, page, errors = open_page(browser, base, name, w=390, h=844, storage={"aaf.palette": "cb"})
            wide = page.evaluate("document.documentElement.scrollWidth")
            if wide > 390:
                problems.append("%s/phone: the page is %d px wide, it scrolls sideways" % (name, wide))
            if name == "image-classifier":
                page.screenshot(path=os.path.join(PLOTS, "render-colourblind-phone.png"), full_page=True)
            problems += ["%s/phone: JavaScript error: %s" % (name, e) for e in errors[:3]]
            ctx.close()
        for mode, storage in (("default", {}), ("cb", {"aaf.palette": "cb"})):
            ctx, page, _ = open_page(browser, base, "image-classifier", storage=storage)
            simulate(page, "deuteranopia")
            page.screenshot(path=os.path.join(PLOTS, "render-colourblind-deuteranopia-%s.png" % mode))
            ctx.close()
        browser.close()
    httpd.shutdown()
    if problems:
        print("Colour-blind check FAILED (%d):" % len(problems))
        for pr in problems:
            print("  - " + pr)
        sys.exit(1)
    print("Colour-blind check passed: switch off by default, remembered, DESIGN.md colour-blind tokens in both themes; "
          "every pair of the 7 state colours at least %d apart for normal, protan, deutan and tritan vision; "
          "%d fixtures without errors, no sideways scrolling on phones" % (MIN_DE, len(names)))


if __name__ == "__main__":
    main()
