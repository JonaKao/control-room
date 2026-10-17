"""ROADMAP.md keeps the status of the planned features. Once built, an item stays marked done:
a later session must not find finished work listed as "Not started"."""
import os
import re
import unittest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILT = {"1": "Live activity feed", "2": "Task timeline", "3": "Change map", "4": "Track record", "5": "README",
         "6": "Instrument-panel redesign"}


class RoadmapTest(unittest.TestCase):
    def test_built_items_are_marked_done(self):
        with open(os.path.join(PROJECT, "ROADMAP.md")) as f:
            rows = {m.group(1): m.group(0) for m in re.finditer(r"^\| (\d+) \|.*$", f.read(), flags=re.M)}
        for n, name in BUILT.items():
            self.assertIn(n, rows, "roadmap item %s (%s) is missing" % (n, name))
            self.assertIn(name, rows[n], "roadmap item %s should be %s" % (n, name))
            status = rows[n].rstrip(" |").rsplit("|", 1)[-1].strip()
            self.assertRegex(status, r"^Done \(\d{4}-\d{2}-\d{2}\)$", "roadmap item %s (%s) says %r" % (n, name, status))


if __name__ == "__main__":
    unittest.main()
