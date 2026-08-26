"""Tripwire for the four identifiers that must never be renamed.

Each of these four strings is matched at runtime against state that already exists on
users' machines and phones: a local CA sitting in a fixed AppData directory and trusted
on their iPhones, a Pictures subfolder holding every photo they have already imported, a
certificate CommonName the README tells them to look for in Settings, and a Windows
firewall rule an earlier setup run created under that exact DisplayName. None of the four
is derived from the project name, and changing any of them breaks installs already in the
field rather than anything in this repo. `tests/test_config.py` pins two of them --
APP_DIR_NAME and DEST_FOLDER_NAME -- incidentally, through the path helpers, so expect it
red alongside this file; the other two have no coverage anywhere else. This file is the
authoritative one, and the only place the reason is written down.

Two of the four are also duplicated as unbound literals in `setup/setup.ps1`, which a
rename sweep scoped to `*.ps1` would rewrite without touching a line of Python. The last
two tests pin those copies to their Python source of truth.

If you are here because a rename sweep turned this file red: that is what it is for. The
sweep found these strings because they read as stale product names, and they are, on
purpose. Revert the rename; do not update the assertions to match it. The comment at each
declaration says exactly what breaks, and DEST_FOLDER_NAME in particular breaks silently.
"""
import inspect
from pathlib import Path

from photo_ferry import net, paths, tls

_SETUP_PS1 = Path(__file__).resolve().parent.parent / "setup" / "setup.ps1"


def _setup_ps1_code() -> str:
    """setup.ps1 with whole-line `#` comments dropped.

    The guard comments beside those lines necessarily quote the very literals asserted
    below, so searching the raw text would let the comment satisfy the assertion while
    the code above it had been renamed -- the tripwire passing precisely when it should
    fire. Measured: it did. Only code is searched.
    """
    lines = _SETUP_PS1.read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.lstrip().startswith("#"))


def _firewall_rule_default() -> str:
    return inspect.signature(net.firewall_rule_present).parameters["rule_name"].default


def test_app_dir_name_is_unchanged():
    """AppData directory holding the CA that phones have already trusted."""
    assert paths.APP_DIR_NAME == "iPhonePhotoDrop"


def test_dest_folder_name_is_unchanged():
    """Pictures subfolder users' existing imported media already sits in."""
    assert paths.DEST_FOLDER_NAME == "iPhone Drop"


def test_ca_common_name_is_unchanged():
    """CommonName of the CA users have installed and trusted on their phones."""
    assert tls.CA_COMMON_NAME == "Photo Drop Local CA"


def test_firewall_rule_display_name_is_unchanged():
    """DisplayName of the inbound rule setup.ps1 created on existing installs."""
    # Read the default off the signature rather than calling the function: it shells out
    # to PowerShell, which is slow, needs a live host, and answers about this machine
    # rather than about the source.
    assert _firewall_rule_default() == "iPhone Photo Drop"


# The two below assert against the *quoted* literal rather than the whole assignment
# line, so reformatting or renaming the PowerShell variable cannot fail them spuriously.
# What they do catch is the realistic fault: a rename sweep over `*.ps1` rewriting the
# string itself. Each compares against the Python constant rather than restating the
# literal, so the copy is pinned to its source of truth and not to a second duplicate.


def test_setup_ps1_app_data_dir_is_unchanged():
    """setup.ps1's own copy of the AppData directory name, used for key hardening."""
    assert f'"{paths.APP_DIR_NAME}"' in _setup_ps1_code(), (
        f'setup/setup.ps1 no longer contains the literal "{paths.APP_DIR_NAME}".\n'
        "This one degrades security silently. tls.setup() runs through Python and writes\n"
        "the private keys to paths.app_data_dir(), which is unaffected by the rename. The\n"
        "hardening loop then tests Test-Path against the renamed $appData, finds nothing,\n"
        "and skips -- so icacls never runs, ca-key.pem and key.pem keep their inherited\n"
        "ACLs instead of being restricted to the current user, and setup reports success.\n"
        "Revert the rename; keep it identical to paths.APP_DIR_NAME."
    )


def test_setup_ps1_firewall_rule_name_is_unchanged():
    """setup.ps1's own copy of the firewall DisplayName, used to skip re-adding it."""
    rule_name = _firewall_rule_default()
    assert f'"{rule_name}"' in _setup_ps1_code(), (
        f'setup/setup.ps1 no longer contains the literal "{rule_name}".\n'
        "setup.ps1 would then create the rule under the new DisplayName, while ui.py\n"
        "calls net.firewall_rule_present() with no argument and probes the old one. The\n"
        "rule works, and the UI reports it missing. On an existing install the original\n"
        "rule also stays behind, and this script can no longer see it to skip re-adding.\n"
        "Revert the rename; keep it identical to the rule_name default in photo_ferry.net."
    )
