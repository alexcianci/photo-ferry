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

The last test is the assertable half of the 0.2.0 release gate. The README already
describes two-way transfer, which does not exist until the Phase 2 outbox lands, so a
0.2.0 tag would publish a promise this repo cannot keep. The gate's other half -- that
an on-device run has passed -- leaves no artifact in the repo, so it is deliberately
not asserted here and not faked with a marker file. It stays a human check.
"""
import importlib.metadata
import importlib.util
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

import photo_ferry
from photo_ferry import server

_REPO_ROOT = Path(__file__).resolve().parent.parent
_GATED_VERSION = "0.2.0"
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


def test_0_2_0_is_not_tagged_before_the_outbox_exists():
    tagged = sorted(tag for tag in _repo_tags() if _gates_0_2_0(tag))
    if not tagged:
        return  # No 0.2.0 tag yet, so there is nothing to gate.
    assert importlib.util.find_spec("photo_ferry.outbox") is not None, (
        f"Release gate: {tagged} is tagged, but photo_ferry.outbox is missing.\n"
        "The README already advertises PC-to-camera-roll transfer, and this is a public\n"
        "repo, so tagging 0.2.0 publishes a feature that does not exist yet. 0.2.0 must\n"
        "not be tagged until Phase 2 through Phase 4 are complete and the on-device run\n"
        "has passed. Delete the tag, or land the outbox first."
    )
