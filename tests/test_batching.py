"""Binds the phone page's batch caps to Config, the values they duplicate by necessity.

`src/photo_ferry/static/upload.html` declares `MAX_BATCH_BYTES` and `MAX_BATCH_FILES` as
JavaScript constants, and those are a second, hand-maintained spelling of
`Config.max_batch_bytes` and `Config.max_batch_files`. The page is served as a static
file -- `photo_ferry.server` reads its bytes once at import time and writes them straight
to the socket -- so there is no template layer, and no request-time substitution, through
which the Python values could reach the browser. The duplication is unavoidable.

The drift is not. `ui.py` refuses to re-spell `max_batch_files` for precisely this reason
and is handed the value through `Config` instead: "Canonical value lives in
Config.max_batch_files; never re-spell it here". The JavaScript copy cannot be handed
anything, so it is guarded here rather than eliminated. Guarded, because drift is silent
in both directions -- nothing on the wire carries the limit, so a phone grouping to one
cap while the PC enforces another just behaves oddly, and the fault surfaces as a share
that fails or a transfer split for no visible reason, never as an error naming the cause.

The values are lifted out of the HTML by regex and folded with `ast` over a whitelist of
integer literals and multiplication -- deliberately not `eval`, and not `ast.literal_eval`,
which will not take `300 * 1024 * 1024` at all. That works only because this arithmetic is
spelled identically in JavaScript and Python; anything outside the whitelist -- a name, a
call, a float, a different operator -- fails loudly instead of being quietly approximated,
and a missing or duplicated declaration fails too. A guard that goes quiet when its target
is renamed is worse than no guard.
"""
import ast
import re
import sys
from pathlib import Path

import pytest

from photo_ferry import config

_THIS = sys.modules[__name__]
_REPO_ROOT = Path(__file__).resolve().parent.parent
_UPLOAD_HTML = _REPO_ROOT / "src" / "photo_ferry" / "static" / "upload.html"


def _js_const_source(name: str) -> str:
    """The right-hand side of `const <name> = ...;` in upload.html, exactly as written.

    Exactly one declaration must match. Zero means the constant was renamed or deleted.
    Two or more means the file disagrees with itself about the cap, and there is no way
    to say which value the browser ends up using. Both are failures, never a skip.
    """
    text = _UPLOAD_HTML.read_text(encoding="utf-8")
    found = re.findall(rf"^\s*const\s+{re.escape(name)}\s*=\s*([^;\n]+);", text, re.M)
    assert len(found) == 1, (
        f"Expected exactly one `const {name} = ...;` in\n"
        f"{_UPLOAD_HTML}\n"
        f"but found {len(found)}.\n"
        "This guard keeps that constant in step with Config, and it can only do that\n"
        "while it can find it. If the constant was renamed, rename it here in the same\n"
        "change; if it was deleted, delete this guard too and say why. What must not\n"
        "happen is leaving it unfindable -- the guard would then pass by never comparing\n"
        "anything, which is the one failure mode a tripwire cannot have."
    )
    return found[0].strip()


def _fold_int(node: ast.AST, name: str, source: str) -> int:
    """Fold a whitelisted integer expression: integer literals and `*`, nothing else."""
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        return _fold_int(node.left, name, source) * _fold_int(node.right, name, source)
    raise AssertionError(
        f"Cannot read {name} out of upload.html: it now says `{source}`, which is not a\n"
        "product of plain integer literals. This guard folds literals and `*` and refuses\n"
        "everything else on purpose -- it will not guess at a value and then compare\n"
        "against its own guess. Either write the constant as integer literals multiplied\n"
        "together, the way `300 * 1024 * 1024` is written, or widen the whitelist in\n"
        f"{Path(__file__).name} deliberately."
    )


def _js_const(name: str) -> int:
    """The integer value of a `const` in upload.html, or a loud failure."""
    source = _js_const_source(name)
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError:
        raise AssertionError(
            f"Cannot parse {name} out of upload.html: `{source}` is not an expression\n"
            "Python can read. This guard leans on JavaScript and Python spelling integer\n"
            "arithmetic the same way, and JavaScript-only syntax breaks that -- a BigInt\n"
            "`25n`, for one. Write the constant as integer literals multiplied together,\n"
            "or teach this guard the new spelling."
        ) from None
    return _fold_int(tree.body, name, source)


def _drift_message(js_name: str, cfg_name: str, js_value: int, cfg_value: int) -> str:
    return (
        f"Batch-cap drift: upload.html says {js_name} = {js_value}, while\n"
        f"Config.{cfg_name} is {cfg_value}.\n"
        "\n"
        "Change the JavaScript to match Config. Do not change Config to match the\n"
        "JavaScript. Config is the canonical value: the server and the desktop window are\n"
        "built from it, ui.py is handed max_batch_files rather than re-spelling it, and\n"
        "tests/test_config.py pins its defaults.\n"
        "\n"
        "The page carries a second copy only because it is served as a static file with\n"
        "no template layer -- nothing substitutes a Python value into it at request time,\n"
        "so the number has to be written out twice. That is why the duplication is\n"
        "tolerated. This test is why it is survivable: drift here is silent. Nothing on\n"
        "the wire carries the limit, so the phone would simply group to a cap the PC does\n"
        "not share, and the first sign of it would be a share that fails or a transfer\n"
        "split for no visible reason."
    )


def test_js_batch_caps_match_config():
    cfg = config.default_config()
    js_bytes = _js_const("MAX_BATCH_BYTES")
    assert js_bytes == cfg.max_batch_bytes, _drift_message(
        "MAX_BATCH_BYTES", "max_batch_bytes", js_bytes, cfg.max_batch_bytes
    )
    js_files = _js_const("MAX_BATCH_FILES")
    assert js_files == cfg.max_batch_files, _drift_message(
        "MAX_BATCH_FILES", "max_batch_files", js_files, cfg.max_batch_files
    )


def _point_at(monkeypatch, tmp_path, body: str) -> None:
    """Aim the guard at a stand-in page instead of the real one.

    Proving this tripwire fires never requires putting a wrong cap in front of a user,
    not even for the length of one test run.
    """
    fake = tmp_path / "upload.html"
    fake.write_text(body, encoding="utf-8")
    monkeypatch.setattr(_THIS, "_UPLOAD_HTML", fake)


_GOOD_FILES_LINE = "const MAX_BATCH_FILES = 25;\n"


def test_the_guard_fails_rather_than_going_quiet(monkeypatch, tmp_path):
    """Four ways this tripwire could stop watching, each proven to go red instead.

    Every row pins a fragment of the message it expects, not merely the fact that
    something was raised. Accepting any AssertionError would let one broken extractor --
    one that raised unconditionally, on every input -- satisfy all four rows at once, so
    the table would report four scenarios covered while testing none of them.
    """
    for body, why, expected in (
        (_GOOD_FILES_LINE,
         "MAX_BATCH_BYTES deleted outright",
         "but found 0."),
        ("const MAX_BATCH_BYTES = 300 * 1024 * 1024;\n"
         "const MAX_BATCH_BYTES = 1;\n" + _GOOD_FILES_LINE,
         "two declarations that disagree",
         "but found 2."),
        ("const MAX_BATCH_BYTES = 300 * MB;\n" + _GOOD_FILES_LINE,
         "a name where a literal was",
         "it now says `300 * MB`"),
        ("const MAX_BATCH_BYTES = 300e6;\n" + _GOOD_FILES_LINE,
         "a float where an integer was",
         "it now says `300e6`"),
    ):
        _point_at(monkeypatch, tmp_path, body)
        try:
            test_js_batch_caps_match_config()
        except AssertionError as exc:
            assert expected in str(exc), (
                f"The guard fired on {why}, but not for that reason: the message was\n"
                f"expected to contain {expected!r} and instead said:\n{exc}\n"
                "A row that passes on the wrong failure is not testing the scenario it\n"
                "names. Fix the extractor, or fix the fragment -- but do not loosen this\n"
                "back to catching any AssertionError at all."
            )
            continue
        raise AssertionError(
            f"The guard stayed green with {why}. It is no longer watching anything, so\n"
            "the JavaScript caps can now drift from Config unnoticed -- which is the\n"
            "whole fault this file exists to prevent. Fix the extractor, not this test."
        )


def test_the_guard_catches_a_wrong_value(monkeypatch, tmp_path):
    """And it fires on the fault it actually exists for: a constant found, but wrong."""
    cfg = config.default_config()
    for body, label in (
        (f"const MAX_BATCH_BYTES = 300 * 1024 * 1023;\n"
         f"const MAX_BATCH_FILES = {cfg.max_batch_files};\n", "MAX_BATCH_BYTES"),
        (f"const MAX_BATCH_BYTES = {cfg.max_batch_bytes};\n"
         f"const MAX_BATCH_FILES = {cfg.max_batch_files + 1};\n", "MAX_BATCH_FILES"),
    ):
        _point_at(monkeypatch, tmp_path, body)
        with pytest.raises(AssertionError, match="Change the JavaScript to match Config") as exc:
            test_js_batch_caps_match_config()
        assert label in str(exc.value), (
            f"The guard fired, but its message never names {label} as the constant that\n"
            "drifted. Whoever hits this is told to edit the JavaScript without being told\n"
            "which line, which is most of the value of the message gone."
        )
