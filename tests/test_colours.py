"""Every colour on the page comes from a token on :root (design/DESIGN.md), so both themes stay in step.
Mask gradients are exempt: there #000 means "fully shown", not a colour."""
import os
import re
import unittest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LITERAL = re.compile(r"#[0-9A-Fa-f]{3,8}\b|\brgba?\(|\bhsla?\(")


def style_without_tokens(html):
    css = html[html.index("<style>"):html.index("</style>")]
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r":root[^{]*\{[^}]*\}", "", css)            # the token blocks
    return re.sub(r"(-webkit-)?mask-image:[^;]*;", "", css)


class ColourTokensTest(unittest.TestCase):
    def test_no_colour_written_outside_the_tokens(self):
        with open(os.path.join(PROJECT, "index.html")) as f:
            css = style_without_tokens(f.read())
        found = sorted({m.group(0) for m in LITERAL.finditer(css)})
        self.assertEqual(found, [], "colours written directly instead of a token: %s" % found)

    def test_the_rule_sees_literals(self):
        sample = "<style>:root { --x: #fff; } a { color: #123456; } b { -webkit-mask-image: linear-gradient(#000, transparent); }</style>"
        self.assertEqual([m.group(0) for m in LITERAL.finditer(style_without_tokens(sample))], ["#123456"])


if __name__ == "__main__":
    unittest.main()
