"""Fails the build when a stylesheet under web/src/ writes a literal a design
token already exists for.
"""

import re
import unittest
from pathlib import Path

SRC_ROOT = Path(__file__).parent / "src"

# _tokens.scss is where every literal is declared by name in the first place.
# _layout.scss's container widths are px by a documented decision, distinct from
# every other pixel value a component might write.
FILES_EXEMPT_FROM_ALL_CHECKS = {"_tokens.scss"}
FILES_EXEMPT_FROM_PX_CHECK = {"_layout.scss"}

# A declaration, however it wraps across lines: "prop: value;" with no "{" in
# between, which is what tells a nested selector like "&:disabled {" apart from
# an actual property.
DECLARATION_RE = re.compile(
    r"^[ \t]*(?P<prop>[a-zA-Z-]+)\s*:\s*(?P<value>[^;{]*);", re.MULTILINE
)
VAR_RE = re.compile(r"var\(--[\w-]+\)")
COLOR_RE = re.compile(r"oklch\(|#[0-9a-fA-F]{3,8}\b|rgba?\(")
PX_RE = re.compile(r"\d+(?:\.\d+)?px")

# The properties a size, weight, line height or tracking value can hide behind,
# including the "font" shorthand this codebase writes exclusively.
FONT_PROPS = {"font", "font-size", "font-weight", "line-height", "letter-spacing"}


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"(?m)//.*$", "", text)


def find_violations(path: Path) -> list[str]:
    if path.name in FILES_EXEMPT_FROM_ALL_CHECKS:
        return []
    text = _strip_comments(path.read_text())
    violations = []
    for match in DECLARATION_RE.finditer(text):
        prop = match.group("prop")
        value = match.group("value").strip()
        bare = VAR_RE.sub("", value)
        if COLOR_RE.search(bare):
            violations.append(f"{path}: `{prop}: {value};` writes a colour literal")
        if prop in FONT_PROPS and re.search(r"\d", bare):
            violations.append(f"{path}: `{prop}: {value};` writes a literal {prop}")
        if path.name not in FILES_EXEMPT_FROM_PX_CHECK:
            for px in PX_RE.finditer(bare):
                if px.group(0) != "1px":
                    violations.append(
                        f"{path}: `{prop}: {value};` writes a px literal"
                        " outside _tokens.scss, _layout.scss and one-pixel rules"
                    )
    return violations


class TestStylesheetsUseTokens(unittest.TestCase):
    def test_no_scss_file_writes_a_literal_a_token_exists_for(self):
        violations = []
        for path in sorted(SRC_ROOT.rglob("*.scss")):
            violations.extend(find_violations(path))
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
