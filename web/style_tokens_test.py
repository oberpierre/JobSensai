"""Fails the build when a stylesheet under web/src/ writes a literal a design
token already exists for, including inside an @media prelude, where a custom
property cannot appear and a Sass variable stands in for one instead.
"""

import re
import tempfile
import unittest
from pathlib import Path

SRC_ROOT = Path(__file__).parent / "src"

# The count under src/ as of writing. A bare non-zero check is satisfied by one
# surviving file, so the floor is pinned to what the tree actually holds instead.
MINIMUM_STYLESHEETS_IN_TREE = 15

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
# The prelude between "@media" and its opening brace. A prelude ends with a
# brace rather than a semicolon, so DECLARATION_RE never matches inside one.
MEDIA_PRELUDE_RE = re.compile(r"@media\s*(?P<condition>[^{]*)\{")
VAR_RE = re.compile(r"var\(--[\w-]+\)")
COLOR_RE = re.compile(r"oklch\(|#[0-9a-fA-F]{3,8}\b|rgba?\(")
PX_RE = re.compile(r"\d+(?:\.\d+)?px")

# The properties a size, weight, line height or tracking value can hide behind,
# including the "font" shorthand this codebase writes exclusively.
FONT_PROPS = {"font", "font-size", "font-weight", "line-height", "letter-spacing"}

# A dimmed element takes the colour token named for that treatment. `opacity`
# fades borders and anything non-textual with it, and its value sits on no scale
# this design system defines.
DIMMING_PROPS = {"opacity"}


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
        if prop in DIMMING_PROPS:
            violations.append(
                f"{path}: `{prop}: {value};` dims with {prop} rather than taking"
                " the colour token named for a disabled or not-crawled treatment"
            )
        if path.name not in FILES_EXEMPT_FROM_PX_CHECK:
            for px in PX_RE.finditer(bare):
                if px.group(0) != "1px":
                    violations.append(
                        f"{path}: `{prop}: {value};` writes a px literal"
                        " outside _tokens.scss, _layout.scss and one-pixel rules"
                    )
    if path.name not in FILES_EXEMPT_FROM_PX_CHECK:
        for prelude in MEDIA_PRELUDE_RE.finditer(text):
            condition = prelude.group("condition").strip()
            if PX_RE.search(condition):
                violations.append(
                    f"{path}: `@media {condition}` writes a raw px length in its"
                    " prelude, where a custom property cannot appear"
                )
    return violations


def check_stylesheets(root: Path) -> list[str]:
    """Returns the violations under root. Raises if root holds too few stylesheets
    to check, catching a glob or path that stopped matching before it goes green
    on nothing."""
    stylesheets = sorted(root.rglob("*.scss"))
    if len(stylesheets) < MINIMUM_STYLESHEETS_IN_TREE:
        raise AssertionError(
            f"found {len(stylesheets)} stylesheet(s) under {root}, fewer than the "
            f"{MINIMUM_STYLESHEETS_IN_TREE} the tree holds"
        )
    violations = []
    for path in stylesheets:
        violations.extend(find_violations(path))
    return violations


class TestStylesheetsUseTokens(unittest.TestCase):
    def test_no_scss_file_writes_a_literal_a_token_exists_for(self):
        self.assertEqual(check_stylesheets(SRC_ROOT), [])

    def test_a_root_with_no_stylesheets_fails_rather_than_passing_silently(self):
        with (
            tempfile.TemporaryDirectory() as empty_dir,
            self.assertRaises(AssertionError),
        ):
            check_stylesheets(Path(empty_dir))


if __name__ == "__main__":
    unittest.main()
