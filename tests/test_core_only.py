"""The checks and tests run against the Rust core (`control-room serve`), not server.py, and moving
them there removed no assertion.

Assertions are counted per file as before the move (feature 2): lines with `self.assert...`,
`problems.append`, `problems +=`, `bad.append`, `bad +=`. A test that now names a Rust unit test
(`assertRustPassed("mod::tests::name")` or `rust_test("mod::tests::name")`) also counts that Rust
test's own assertions, since that is where the assertion went."""
import os
import re
import unittest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Counted on the files as they were before feature 2 (commit 2f12b8e).
BEFORE = {
    "tests/test_api.py": 110, "tests/test_git.py": 61,
    "checks/activity.py": 55, "checks/change_map.py": 40, "checks/colour_blind.py": 27, "checks/estimate.py": 29,
    "checks/git_section.py": 41, "checks/glance.py": 30, "checks/layout.py": 42, "checks/render.py": 6,
    "checks/timeline.py": 38, "checks/track_record.py": 57,
}
# Only the parity check may still start server.py, to compare against it (until feature 10).
MAY_IMPORT_SERVER = {"checks/parity.py"}
ASSERTION = re.compile(r"self\.assert|problems\.append|bad\.append|bad \+=|problems \+=")
NAMED = re.compile(r"""(?:assertRustPassed|rust_test)\(\s*["']([\w:]+)["']""")


def read(rel):
    with open(os.path.join(PROJECT, rel), encoding="utf-8") as f:
        return f.read()


def rust_asserts(name):
    """How many assert lines the Rust unit test `mod::tests::fn` has (0 if it does not exist)."""
    mod, fn = name.split("::")[0], name.split("::")[-1]
    path = os.path.join(PROJECT, "app", "src", mod + ".rs")
    if not os.path.isfile(path):
        return 0
    lines = read(os.path.join("app", "src", mod + ".rs")).splitlines()
    count, inside = 0, False
    for line in lines:
        if re.match(r"\s*(pub )?(async )?fn %s\(" % re.escape(fn), line):
            inside = True
            continue
        if inside:
            if re.match(r"^    }\s*$", line):
                return count
            count += len(re.findall(r"\bassert(_eq|_ne)?!", line))
    return count


def count(rel):
    text = read(rel)
    own = sum(1 for line in text.splitlines() if ASSERTION.search(line))
    return own + sum(rust_asserts(n) for n in NAMED.findall(text))


class CoreOnlyTest(unittest.TestCase):
    def test_nothing_imports_server_py(self):
        for folder in ("checks", "tests"):
            for fn in sorted(os.listdir(os.path.join(PROJECT, folder))):
                rel = folder + "/" + fn
                if fn.endswith(".py") and rel not in MAY_IMPORT_SERVER:
                    self.assertIsNone(re.search(r"^\s*(import server\b|from server import)", read(rel), re.M),
                                      "%s still imports server.py; start the core with checks/app_server.py" % rel)

    def test_page_checks_start_the_core(self):
        for rel in BEFORE:
            if rel.startswith("checks/"):
                self.assertTrue("app_server.Served(" in read(rel), "%s does not start control-room serve" % rel)

    def test_no_assertion_lost_in_the_move(self):
        for rel, before in BEFORE.items():
            self.assertGreaterEqual(count(rel), before, "%s has fewer assertions than before the move" % rel)

    def test_named_rust_tests_exist(self):
        for rel in BEFORE:
            for name in NAMED.findall(read(rel)):
                self.assertGreater(rust_asserts(name), 0, "%s names %s, which has no assertions or does not exist" % (rel, name))

    def test_the_counter_counts(self):
        self.assertEqual(rust_asserts("activity::tests::quiet_records_are_not_steps"), 1)
        self.assertEqual(rust_asserts("activity::tests::no_such_test"), 0)


if __name__ == "__main__":
    unittest.main()
