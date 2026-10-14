"""Every test file runs completely on its own (`python3 tests/<file>.py`), not only through discover:
its `if __name__ == "__main__":` block must come last, after every test class."""
import ast
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def is_main_block(node):
    return isinstance(node, ast.If) and "__main__" in ast.dump(node.test)


class TestFileLayoutTest(unittest.TestCase):
    def test_main_block_comes_last(self):
        for fn in sorted(os.listdir(HERE)):
            if not (fn.startswith("test_") and fn.endswith(".py")):
                continue
            with open(os.path.join(HERE, fn)) as f:
                body = ast.parse(f.read()).body
            mains = [i for i, node in enumerate(body) if is_main_block(node)]
            after = [n.name for n in body[mains[0] + 1:] if isinstance(n, ast.ClassDef)] if mains else []
            self.assertEqual(after, [], "%s: test classes after the __main__ block are skipped when run directly" % fn)


if __name__ == "__main__":
    unittest.main()
