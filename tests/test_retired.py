"""The browser version is retired (feature 10): the app is the only way to the control room, and nothing
in this project or the workspace's own guides still points to the old server."""
import json
import os
import re
import unittest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.path.dirname(os.path.dirname(PROJECT))
OLD = re.compile(r"dashboard/server\.py|Open Dashboard\.command|localhost:8765")


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


class RetiredTest(unittest.TestCase):
    def test_the_browser_version_is_gone(self):
        for path in (os.path.join(PROJECT, "server.py"), os.path.join(WORKSPACE, "dashboard"),
                     os.path.join(WORKSPACE, "Open Dashboard.command"), os.path.join(PROJECT, "checks", "parity.py")):
            self.assertFalse(os.path.exists(path), "%s should be removed" % os.path.relpath(path, WORKSPACE))

    def test_no_check_needs_it(self):
        checks = json.loads(read(PROJECT, "project.json"))["checks"]
        self.assertNotIn("Same answers as before", [c["name"] for c in checks])
        self.assertFalse([c["name"] for c in checks if "parity.py" in c["cmd"] or "server.py" in c["cmd"]])

    def test_guides_point_to_the_app(self):
        for rel in ("README.md", os.path.join("framework", "REFERENCE.md")):
            text = read(WORKSPACE, rel)
            self.assertIsNone(OLD.search(text), "%s still points to the browser version" % rel)
            self.assertIn("Agent Control Room", text, "%s does not name the app" % rel)
            self.assertIn("projects/control-room", text, "%s does not say where the app's guide is" % rel)
        for rel in ("README.md", "control-room.md", "index.html"):
            self.assertIsNone(OLD.search(read(PROJECT, rel)), "%s still points to the browser version" % rel)

    def test_done_names_the_apps_core(self):
        done = read(PROJECT, "DONE.md")
        self.assertIn("The app's core writes no project files itself", done)
        self.assertNotIn("The server writes no project files", done)


if __name__ == "__main__":
    unittest.main()
