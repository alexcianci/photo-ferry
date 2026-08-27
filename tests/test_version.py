"""Keeps the version literals in step, and gates the 0.2.0 tag on the feature landing.

Three version strings are maintained by hand and nothing binds them: `version` in
pyproject.toml, `photo_ferry.__version__`, and the `Server:` header in
`photo_ferry.server`. Nothing in the package reads `__version__`, so a half-finished
bump would ship without a single test noticing. The first test binds all three.

It reads pyproject.toml off disk with tomllib, not importlib.metadata. Those are not the
same string: distribution metadata is frozen at `pip install -e` time, so against a stale
editable install, bumping pyproject alone -- the exact half-finished bump this test exists
to catch -- compared 0.2.0 against 0.2.0 and passed. There is no CI here, so that stale
install is the only environment this test ever runs in. tomllib is stdlib on the
`requires-python = ">=3.12"` already declared, so this costs no dependency, which matters:
"stdlib plus one pure-Python dependency" is the product claim.

Asking importlib.metadata is still worth doing, but it answers a different question --
"did you forget to reinstall?" -- so it is a separate test with its own remedy, where it
cannot stand in for the pyproject comparison.

The last three tests are the assertable half of the 0.2.0 release gate. The README
already describes two-way transfer, so a 0.2.0 tag publishes a promise this repo cannot
keep until the whole path exists.

The gate originally asked whether `photo_ferry.outbox` was importable, and Phase 2
answered that -- which retired it silently, with nothing failing to say so. Worse, it
retired early: `find_spec` resolves against the file on disk under an editable install,
so the gate went quiet the moment outbox.py was written, before it was ever committed.
Server routes were not a shipped feature either: while nothing in the desktop app offered
a file and nothing on the phone asked for one, the outbox was reachable and permanently
empty. So the gate was rebuilt to ask instead for the two surfaces that turn those routes
into a feature -- the send intake caller in ui.py (Phase 3, Task 8) and the receive tab in
upload.html (Phase 4, Task 10). Both have since landed, the receive tab on 2026-08-27, so
the gate is permanently silent again; the difference this time is that a test says so out
loud instead of the silence passing unremarked. Both surfaces are asserted against source
on disk, with whole-line comments stripped, for the same reason as
tests/test_protected_identifiers.py -- a comment naming the seam must not be able to
satisfy the assertion that the seam exists.

That second silence is by design: every artifact the gate can see is now present. What it
can never see is the on-device run, which leaves nothing in the repo and is deliberately
neither asserted here nor faked with a marker file. That half stays a human check, and now
that Phase 4 has landed it is the only thing left between a green suite and a tag that
should not exist yet.
"""
import importlib.metadata
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import photo_ferry
from photo_ferry import server

_THIS = sys.modules[__name__]
_REPO_ROOT = Path(__file__).resolve().parent.parent
_GATED_VERSION = "0.2.0"
# The two surfaces that make the outbox a feature rather than a pair of unreachable
# routes. Both are the literal the plan's own code introduces, so landing Task 8 and
# Task 10 as written satisfies this gate without anyone having to remember it exists.
_SEND_INTAKE_CALL = "self.outbox.add("      # ui.py, Phase 3 Task 8
_RECEIVE_TAB_LABEL = "Get from PC"          # upload.html, Phase 4 Task 10
# Stripped in order, first match wins. These two cannot overlap, but keep any addition
# ordered longest-first so a shorter prefix never strips part of a longer one.
_TAG_PREFIXES = ("release-", "v")


def _pyproject_version() -> str:
    """The `version` in pyproject.toml as it is on disk right now."""
    text = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)["project"]["version"]


def test_version_literals_do_not_drift():
    assert _pyproject_version() == photo_ferry.__version__, (
        "Version drift: pyproject.toml and photo_ferry.__version__ disagree.\n"
        "Both are maintained by hand and nothing binds them at runtime. Bump the one\n"
        "that was missed -- this is a source edit, not a reinstall."
    )

    # The header deliberately carries major.minor only, never the patch level: it
    # follows the old iPhonePhotoDrop/0.1 convention and keeps the patch level off the
    # wire. Assert that relationship rather than pinning a fourth literal, so a 0.2.1
    # bump is still a two-line change and nobody is tempted to interpolate the whole
    # version into the header.
    major, minor = photo_ferry.__version__.split(".")[:2]
    assert server._Handler.server_version == f"PhotoFerry/{major}.{minor}"


def test_installed_distribution_is_not_stale():
    """Separate from the drift test on purpose: the remedy here is a reinstall.

    "photo-ferry" with a hyphen is the distribution name; "photo_ferry" is the import
    package. Distribution metadata is a snapshot taken at `pip install -e` time, so this
    goes red when the source tree has moved on from the installed dist -- a real fault,
    but not version drift. Keeping it out of the test above means it can never stand in
    for that comparison, or send someone editing a version literal to fix a stale venv.
    """
    try:
        installed = importlib.metadata.version("photo-ferry")
    except importlib.metadata.PackageNotFoundError:
        pytest.skip("photo-ferry is not installed; run `pip install -e .[dev]`")
    assert installed == _pyproject_version(), (
        f"Stale editable install: the installed photo-ferry is {installed}, but\n"
        f"pyproject.toml says {_pyproject_version()}. Nothing is wrong with the source\n"
        "tree -- re-run `pip install -e .[dev]`. Do not edit a version literal to\n"
        "silence this."
    )


def _gates_0_2_0(tag: str) -> bool:
    """True for any spelling of a 0.2.0 tag, release candidates included.

    Matching the bare `v0.2.0` and `0.2.0` was not enough. `v0.2.0-rc1` and
    `release-0.2.0` sailed straight through, and an rc tag is the likeliest accident:
    origin is public, GitHub surfaces an rc as a pre-release, and the tree it publishes
    carries the same README advertising PC-to-camera-roll transfer. So normalise the
    prefix, then gate the whole 0.2.0 line -- `0.2.0rc1` and `0.2.0+build` included.
    `v0.2.10` and `v0.20.0` are different releases and are deliberately left alone.
    """
    for prefix in _TAG_PREFIXES:
        if tag.startswith(prefix):
            tag = tag[len(prefix):]
            break
    return tag.startswith(_GATED_VERSION)


def _repo_tags() -> list[str]:
    """Tags in this work tree, or skip if git cannot answer."""
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH")
    try:
        proc = subprocess.run(
            ["git", "tag", "--list"],
            cwd=_REPO_ROOT, capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f"could not run git: {exc}")
    if proc.returncode != 0:
        pytest.skip("not a git work tree")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _ui_code() -> str:
    """ui.py with whole-line `#` comments dropped, so a comment cannot satisfy the gate."""
    text = (_REPO_ROOT / "src" / "photo_ferry" / "ui.py").read_text(encoding="utf-8")
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def _upload_html() -> str:
    """upload.html with HTML comments dropped, for the same reason as _ui_code."""
    text = (_REPO_ROOT / "src" / "photo_ferry" / "static" / "upload.html").read_text(
        encoding="utf-8"
    )
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def _missing_surfaces() -> list[str]:
    """Which halves of the two-way feature are still absent from the source on disk.

    Deliberately not `find_spec` and not the server routes. Both of those were already
    true while the feature was unusable -- see the module docstring.
    """
    missing = []
    if _SEND_INTAKE_CALL not in _ui_code():
        missing.append(
            f"the send intake caller in ui.py (no {_SEND_INTAKE_CALL!r}; Phase 3, Task 8)"
        )
    if _RECEIVE_TAB_LABEL not in _upload_html():
        missing.append(
            f"the receive tab in upload.html (no {_RECEIVE_TAB_LABEL!r}; Phase 4, Task 10)"
        )
    return missing


def test_0_2_0_is_not_tagged_before_the_feature_is_shippable():
    tagged = sorted(tag for tag in _repo_tags() if _gates_0_2_0(tag))
    if not tagged:
        return  # No 0.2.0 tag yet, so there is nothing to gate.
    missing = _missing_surfaces()
    assert not missing, (
        f"Release gate: {tagged} is tagged, but the two-way feature is not shippable.\n"
        + "".join(f"  Missing: {m}\n" for m in missing)
        + "The README already advertises PC-to-camera-roll transfer, and this is a\n"
        "public repo with a Sponsor button, so tagging 0.2.0 publishes a feature a user\n"
        "cannot reach. The Phase 2 server routes alone do not count: nothing offers a\n"
        "file and nothing asks for one, so the outbox is reachable and always empty.\n"
        "Delete the tag, or land the missing surfaces first. Note that even a fully\n"
        "green suite does not clear this release -- the on-device run leaves no artifact\n"
        "here and stays a human check."
    )


def test_both_surfaces_are_present_and_the_gate_has_retired():
    """The gate retired here: with both surfaces on disk it can never fire again.

    Phase 4 Task 10 landed the receive tab in upload.html on 2026-08-27, joining the
    send intake caller Task 8 put in ui.py. `_missing_surfaces()` has returned [] ever
    since, so the release gate is permanently silent -- by design, and recorded here
    deliberately rather than discovered later. Its predecessor, the find_spec check,
    retired unannounced the moment outbox.py was written; this test is the fix for that,
    so it inverts rather than disappears. It now pins the two surfaces as present instead
    of counting the ones still missing, and goes red if either is refactored back out.

    What the retirement does NOT mean is that 0.2.0 is clearable. The on-device run has
    still not happened, and it is mechanized nowhere -- not in this file, not in CI
    (there is none), and deliberately not behind a marker file, because an artifact a
    script can write is an artifact a script can write with no iPhone in the room. Phase
    4 Task 14 is that run. Until it is done, a fully green suite means the source tree is
    consistent, not that the release is shippable -- and nothing mechanical stops a 0.2.0
    tag any more, so the judgement is now entirely a human one.
    """
    assert _SEND_INTAKE_CALL in _ui_code(), (
        f"{_SEND_INTAKE_CALL!r} vanished from ui.py -- Outbox.add has no caller again,\n"
        "so nothing on the desktop side offers a file and both routes are reachable and\n"
        "permanently empty. Restore the send intake, or this half of 0.2.0 does not exist."
    )
    assert _RECEIVE_TAB_LABEL in _upload_html(), (
        f"{_RECEIVE_TAB_LABEL!r} vanished from upload.html -- the receive tab is gone\n"
        "from the phone page, so nothing on the phone can ask the PC for a file and the\n"
        "outbox is unreachable from the only client that exists."
    )
    assert _missing_surfaces() == [], (
        "the gate still reports a missing surface that the two assertions above did\n"
        f"not catch: {_missing_surfaces()}. _missing_surfaces() and this test have\n"
        "drifted apart -- fix them together; they are meant to read the same two literals."
    )


def test_the_receive_tab_label_appears_exactly_once_in_upload_html():
    """Catches an accidental second occurrence of the label, and only that.

    `_upload_html()` strips HTML comments and nothing else -- not `//` comments, not
    JavaScript string literals -- so a second occurrence anywhere in the page keeps
    `_missing_surfaces()` quiet even after the real tab button is deleted. The page has
    always carried the label exactly once, but only because whoever touched it was
    careful. Task 12 added several new user-facing strings to the receive flow, which is
    exactly the change that makes a second one appear by accident, so the care is written
    down here instead of assumed.

    What this does NOT do, stated plainly because the alternative is a docstring that
    overclaims: it does not stop prose from satisfying the release gate. Delete the tab
    button and add the phrase once somewhere else -- a status message, a comment -- and
    the count is still 1, this passes, and `_missing_surfaces()` reports a surface that no
    longer exists. Guarding that needs the assertion anchored to the element carrying the
    receive tab's id rather than to a bare count, which reworks a gate that has already
    retired and pulls the surrounding tests into the change. Deferred deliberately.

    Counting rather than substring-matching does remove the vacuous pass: if
    `_upload_html()` is ever restructured so it can no longer read the page, it returns
    something with zero occurrences and this fails, where a plain `in` check would have to
    be read to notice it was testing nothing.
    """
    found = _upload_html().count(_RECEIVE_TAB_LABEL)
    assert found == 1, (
        f"{_RECEIVE_TAB_LABEL!r} appears {found} time(s) in upload.html; it must appear\n"
        "exactly once, on the receive tab button itself.\n"
        "Zero means the tab is gone and the release gate has lost the only surface it\n"
        "can see on the phone side. Two or more is worse, because nothing goes red: the\n"
        "gate matches a bare substring against a page from which only HTML comments have\n"
        "been stripped, so a status message, a `//` comment or a JavaScript string\n"
        "carrying the same words would satisfy it after the button had been deleted --\n"
        "the gate would then be reading prose and reporting a feature.\n"
        "Reword the new occurrence; do not relax this count."
    )


def test_release_gate_fires_while_either_surface_is_missing(monkeypatch):
    """The gate must fail today, and with either half alone. Proven by injecting a tag
    rather than creating one: this repo must not carry a 0.2.0 tag, not even briefly."""
    monkeypatch.setattr(_THIS, "_repo_tags", lambda: ["v0.2.0"])
    have_ui = f"        {_SEND_INTAKE_CALL}paths)"
    have_html = f"<button class='tab'>{_RECEIVE_TAB_LABEL}</button>"
    # Absent surfaces are literals too, not the live source read off disk. They used to
    # be `_ui_code()` and `_upload_html()`, which worked only while both surfaces really
    # were missing -- so landing Task 8's intake caller turned the "receive tab only"
    # row below into both-surfaces-present, where the gate correctly stays silent and
    # the pytest.raises failed with DID NOT RAISE. A scenario table that reads the tree
    # it is testing stops being a table of scenarios the moment the tree moves. Watching
    # the real tree is the job of test_both_surfaces_are_present_and_the_gate_has_retired.
    no_ui = "class ReceiverWindow:\n    def offer(self, paths):\n        pass\n"
    no_html = "<button class='tab'>Send to PC</button>"

    for ui_text, html_text, label in (
        (no_ui, no_html, "neither surface"),
        (have_ui, no_html, "intake only"),
        (no_ui, have_html, "receive tab only"),
    ):
        monkeypatch.setattr(_THIS, "_ui_code", lambda t=ui_text: t)
        monkeypatch.setattr(_THIS, "_upload_html", lambda t=html_text: t)
        with pytest.raises(AssertionError, match="not shippable"):
            test_0_2_0_is_not_tagged_before_the_feature_is_shippable()


def test_release_gate_goes_green_once_both_surfaces_exist(monkeypatch):
    """And it must stop firing when Phase 4 lands, or it is a gate nobody can ever pass."""
    monkeypatch.setattr(_THIS, "_repo_tags", lambda: ["v0.2.0"])
    monkeypatch.setattr(_THIS, "_ui_code", lambda: f"        {_SEND_INTAKE_CALL}paths)")
    monkeypatch.setattr(
        _THIS, "_upload_html", lambda: f"<button class='tab'>{_RECEIVE_TAB_LABEL}</button>"
    )
    test_0_2_0_is_not_tagged_before_the_feature_is_shippable()
