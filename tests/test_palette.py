"""Contrast floors as tests. The palette is an accessibility contract, so a future edit
fails here instead of shipping quietly.

WHAT THIS DOES NOT CHECK
------------------------
Stated up front, because the list below reads like a complete audit and is not one.

* It checks the pairings enumerated in APPROVED, not every pairing the two surfaces
  render. A colour combination introduced without a line here is unmeasured, and this
  file will not notice. `test_no_button_rule_repaints_the_tabs_or_the_ghost` is a narrow
  guard against one instance of that class -- the one that actually shipped -- not a
  general answer.
* Nothing here reads a rendering. The page assertions parse CSS text, so a rule that is
  present but overridden, or a colour composited by opacity, is invisible to them.
  Closing that needs a browser this project has deliberately not taken on.
* Contrast is one accessibility concern. Nothing here says anything about focus order
  or hit-target size.
* The two state-announcement tests are SPELLING checks and nothing more. They assert that
  `aria-selected` and three `role="status"` attributes are written in the page. They do
  not verify that anything is announced, that a live region fires when its text changes,
  or that the announcement is the right one. Only a screen reader on the device answers
  that, and the on-device pass is Task 14.

The palette parity hole that used to be listed here is closed:
`test_the_two_surfaces_spell_the_same_palette` binds every shared token. It was not
hypothetical -- ACCENT_PRESS is never used anywhere in ui.py, so the "button label,
hover" row below measures a Python constant that only the page renders.
"""
import re
from importlib import resources

import pytest

from photo_ferry import ui

AA_TEXT = 4.5      # normal-size text
AA_LARGE = 3.0     # >=18.66px at weight 700, or >=24px
AA_NONTEXT = 3.0   # boundaries of interactive components


def _lin(c):
    c = c / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lum(colour):
    h = colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(fg, bg):
    a, b = _lum(fg), _lum(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def _page_css():
    return (resources.files("photo_ferry")
            .joinpath("static/upload.html").read_text(encoding="utf-8"))


CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
STYLE_BLOCK = re.compile(r"<style>(.*?)</style>", re.S)
ROOT_BLOCK = re.compile(r":root\s*\{([^}]*)\}")


def _page_stylesheet():
    """The <style> block with CSS comments removed.

    Every parser in this file reads through here rather than through _page_css(), so that
    none of them can be satisfied by prose. Both halves matter and both were found by
    mutation rather than reasoning. Without the <style> scoping, the rule regex chews
    through the page's JavaScript and reports function bodies as selectors. Without
    comment stripping, the prose in this file's own explanatory comments -- which
    necessarily quotes `button:hover` and `.tab.active` -- is parsed as CSS. That is the
    "a comment satisfies the gate" failure this repo has already patched twice, in
    test_version._upload_html and in test_protected_identifiers.
    """
    block = STYLE_BLOCK.search(_page_css())
    assert block, "could not find the <style> block in upload.html"
    return CSS_COMMENT.sub("", block.group(1))


def _root_declarations():
    """The body of the `:root` rule, comments already stripped."""
    block = ROOT_BLOCK.search(_page_stylesheet())
    assert block, "could not find the :root block in upload.html's stylesheet"
    return block.group(1)


def _page_token(name):
    """The hex behind one `:root` custom property in upload.html.

    Read from the page rather than restated here, so the tab-bar rows below measure the
    colour the phone actually renders. Asserting instead of skipping: a token that has
    been renamed, moved out of `:root`, or left behind only in a comment must fail
    loudly, because the alternative is these rows quietly measuring a value nothing
    paints any more.

    Anchored to the `:root` body for that reason. The first version searched the whole
    raw file, so renaming a token failed correctly but MOVING one out of `:root` passed
    silently -- the docstring promised a guarantee the regex did not deliver.
    """
    match = re.search(rf"--{name}:\s*(#[0-9A-Fa-f]{{6}})\s*;", _root_declarations())
    assert match, f"upload.html has no --{name} hex token in :root"
    return match.group(1)


# The tab bar is the phone page's only surface with no counterpart in the Tk window, so
# these two come out of the stylesheet rather than out of `ui`.
TAB_TRACK = _page_token("surface-2")   # the .tabs container
TAB_PILL = _page_token("surface")      # .tab.active, which is --surface

APPROVED = [
    ("primary text on base",        ui.TEXT,      ui.BG,           AA_TEXT),
    ("primary text on elevated",    ui.TEXT,      ui.SURFACE,      AA_TEXT),
    ("secondary on base",           ui.TEXT_2,    ui.BG,           AA_TEXT),
    ("secondary on elevated",       ui.TEXT_2,    ui.SURFACE,      AA_TEXT),
    ("muted on base",               ui.MUTED,     ui.BG,           AA_TEXT),
    ("danger on base",              ui.DANGER,    ui.BG,           AA_TEXT),
    # Nothing renders this one today: every danger surface on both screens sits on --bg.
    # Kept as a standing permission for the elevated case rather than deleted, but it is
    # a measurement of an unused pairing and should not be read as coverage.
    ("danger on elevated",          ui.DANGER,    ui.SURFACE,      AA_TEXT),
    ("button label, default",       ui.ON_ACCENT, ui.ACCENT,       AA_LARGE),
    ("button label, hover",         ui.ON_ACCENT, ui.ACCENT_PRESS, AA_LARGE),
    ("outline on base",             ui.OUTLINE,   ui.BG,           AA_NONTEXT),
    ("outline on elevated",         ui.OUTLINE,   ui.SURFACE,      AA_NONTEXT),
    ("accent boundary on base",     ui.ACCENT,    ui.BG,           AA_NONTEXT),
    ("accent boundary on elevated", ui.ACCENT,    ui.SURFACE,      AA_NONTEXT),
    # The pairing code is the one place accent carries glyphs rather than a fill. At
    # 30pt bold it is unambiguously large text, so the 3:1 floor is the right one; the
    # row is here because test_accent_is_never_body_text is easily misread as "accent is
    # never any text", and the exception should be visible rather than inferred.
    ("pairing code on base",        ui.ACCENT,    ui.BG,           AA_LARGE),
    # --- Tab bar (phone page only) -------------------------------------------------
    # These surfaces did not exist when the list above was first drawn up, and the tab
    # bar went unmeasured as a result. The inactive label was the live defect: it is
    # 15px at weight 600 -- normal text -- and was painted --muted, which is 4.02:1 on
    # the track.
    ("inactive tab label on track", ui.TEXT_2,    TAB_TRACK,       AA_TEXT),
    ("active tab label on pill",    ui.TEXT,      TAB_PILL,        AA_TEXT),
    # The active pill's fill is only 1.41:1 against its track, and no DARKER track can
    # lift it: --surface against pure black is 1.82:1. A lighter one could -- 3:1 needs
    # luminance >= 0.22273 and --outline is already 0.28918 -- but a track brighter than
    # the pill inverts the elevation reading, which was the original defect. So the ring,
    # not the fill, marks the selected tab, and these are the floors it has to clear.
    ("active tab ring on track",    ui.OUTLINE,   TAB_TRACK,       AA_NONTEXT),
    ("active tab ring on pill",     ui.OUTLINE,   TAB_PILL,        AA_NONTEXT),
    # --surface-2 is also the thumbnail well, whose placeholder icon is --muted.
    ("thumb icon on track",         ui.MUTED,     TAB_TRACK,       AA_NONTEXT),
    # Press feedback on a tab is the label brightening, not a fill change. See the
    # nav.tabs rule in upload.html for why no compliant press FILL exists that does not
    # also render a pressed tab brighter than the selected one.
    ("pressed tab label on track",  ui.TEXT,      TAB_TRACK,       AA_TEXT),
    # --- Rules that had no colour of their own and fell through to the UA ------------
    # The fallback grid's download link, and the PIN field's placeholder.
    ("fallback link on base",       ui.TEXT,      ui.BG,           AA_TEXT),
    ("placeholder on elevated",     ui.TEXT_2,    ui.SURFACE,      AA_TEXT),
]


def test_every_approved_pairing_meets_its_floor():
    failures = [
        f"{label}: {contrast(fg, bg):.2f}:1 below {floor}"
        for label, fg, bg, floor in APPROVED
        if contrast(fg, bg) < floor
    ]
    assert not failures, "; ".join(failures)


def test_forbidden_pairings_stay_forbidden():
    """Keeps the reasons in the codebase rather than in a commit message someone has to
    go and find."""
    # Warm white on the orange is 2.92:1. This is why button labels are navy.
    assert contrast(ui.TEXT, ui.ACCENT) < AA_LARGE
    # Muted on elevated is 4.02:1, under the normal-text floor, so TEXT_2 is used there.
    assert contrast(ui.MUTED, ui.SURFACE) < AA_TEXT
    # The hairline is decorative at 1.57:1; it can never carry an interactive boundary.
    assert contrast(ui.HAIRLINE, ui.BG) < AA_NONTEXT


def test_accent_would_fail_as_body_text():
    """Accent is buttons, focus rings and highlights only -- but note what this checks.

    It measures that the accent CANNOT legally be body text; nothing here scans either
    surface for a usage. The old name claimed the stronger property. Usage is held by
    review and by the comments at each accent site, not by this assertion.
    """
    assert contrast(ui.ACCENT, ui.BG) < AA_TEXT
    assert contrast(ui.ACCENT, ui.SURFACE) < AA_TEXT


LARGE_TEXT_PX = 18.66          # WCAG large text: >=18.66px at weight 700, or >=24px
BUTTON_RULE = re.compile(r"\bbutton\s*\{([^}]*)\}")


def _phone_button_type():
    """Read the base button rule out of the page's own stylesheet."""
    rule = BUTTON_RULE.search(_page_stylesheet())
    assert rule, "could not find the base `button` rule in upload.html"
    size = re.search(r"font-size:\s*([\d.]+)px", rule.group(1))
    weight = re.search(r"font-weight:\s*(\d+)", rule.group(1))
    assert size and weight, (
        "the base button rule must state font-size in px and a numeric font-weight"
    )
    return float(size.group(1)), int(weight.group(1))


def test_button_label_type_keeps_the_accent_legal():
    """The navy-on-orange label is 4.09:1 (3.42:1 on hover), under the 4.5 normal-text
    floor and clearing only the 3:1 LARGE-text floor. The label's size and weight are
    therefore load-bearing for contrast rather than a matter of taste: shrinking or
    lightening it silently drops both button states below their floor.

    The phone page is checked by parsing its own stylesheet, deliberately strictly. If
    the rule is restructured so the pattern stops matching, this fails rather than
    passing quietly, and whoever restructured it has to re-establish the guarantee.
    """
    size_px, weight = _phone_button_type()
    assert weight >= 700, f"button weight {weight} drops the label below large text"
    assert size_px >= LARGE_TEXT_PX, f"button {size_px}px is under {LARGE_TEXT_PX}px"

    # Tk states type in points, where the same threshold is 14pt bold.
    assert ui.BUTTON_FONT_PT >= 14
    assert ui.BUTTON_FONT_WEIGHT == "bold"


ACTIVE_TAB_RULE = re.compile(r"\.tab\.active\s*\{([^}]*)\}")


def test_the_selected_tab_is_not_marked_by_fill_alone():
    """The two "active tab ring" rows in APPROVED measure a ring; this checks it exists.

    Without it those rows are the failure this project keeps repeating -- a floor cleared
    by a colour nothing renders. The active pill is --surface and its track is
    --surface-2, which measure 1.41:1 apart, and that is not a ceiling of this particular
    pair: --surface against pure black is 1.82:1, so no DARKER track can lift
    the fill difference to the 3:1 non-text floor from BELOW. A lighter track would clear
    it (3:1 needs luminance >= 0.22273; --outline is 0.28918 and would give 3.73:1), and
    is rejected on design grounds rather than measurement: a track brighter than the pill
    reverses the elevation the pill exists to state. Within that choice the inset
    --outline ring is the only thing carrying the selected state at a compliant ratio.

    Deliberately strict about where the ring is spelled. If .tab.active is restructured
    so this stops matching, it fails rather than passing quietly, and whoever moved it
    has to re-establish the guarantee. What it does NOT verify is that the ring is
    visible: it reads the rule text, not a rendering, so a later `box-shadow: none` on a
    more specific selector would sail past.
    """
    rule = ACTIVE_TAB_RULE.search(_page_stylesheet())
    assert rule, "could not find the `.tab.active` rule in upload.html"
    body = rule.group(1)
    assert "box-shadow" in body and "var(--outline)" in body, (
        "`.tab.active` no longer carries an --outline ring, so the selected tab is back "
        "to a 1.41:1 fill difference against its track and nothing else"
    )


# Non-greedy to the first closing brace in column 0, which is how every top-level
# function in this page's one flat script ends.
SHOW_TAB_BODY = re.compile(r"function\s+showTab\s*\([^)]*\)\s*\{(.*?)\n\}", re.S)


def test_aria_selected_is_declared_and_maintained():
    """The non-visual half of the same guarantee, scoped so prose cannot satisfy it.

    The first version of this counted `aria-selected` anywhere in the file and asked for
    4. There are 7, and 3 of them are in comments -- including the comment that claims to
    guard the drift -- so deleting BOTH setAttribute calls left 5 and still passed. Count
    the markup attribute and the showTab body separately, and fail loudly if showTab
    cannot be found at all rather than silently checking nothing.

    Still a spelling check: it proves the calls are written, not that they run.
    """
    page = _page_css()
    assert page.count('aria-selected="') == 2, (
        "expected exactly two aria-selected attributes in the tab markup, one per tab; "
        f"found {page.count('aria-selected=')}"
    )
    body = SHOW_TAB_BODY.search(page)
    assert body, "could not find the showTab() body in upload.html"
    maintained = re.findall(r'setAttribute\(\s*"aria-selected"', body.group(1))
    assert len(maintained) == 2, (
        "showTab() must set aria-selected for both tabs in the same place it toggles "
        f"the .active class, or the two drift; found {len(maintained)} call(s)"
    )


# Every token the two surfaces are supposed to share. --surface-2 is deliberately absent:
# the recessed track exists only on the phone, and ui.py would carry a dead constant.
SHARED_TOKENS = [
    ("bg", "BG"), ("surface", "SURFACE"), ("hairline", "HAIRLINE"),
    ("outline", "OUTLINE"), ("text", "TEXT"), ("text-2", "TEXT_2"),
    ("muted", "MUTED"), ("accent", "ACCENT"), ("accent-press", "ACCENT_PRESS"),
    ("on-accent", "ON_ACCENT"), ("danger", "DANGER"),
]


@pytest.mark.parametrize("css_token,py_name", SHARED_TOKENS)
def test_the_two_surfaces_spell_the_same_palette(css_token, py_name):
    """`ui` and `upload.html` carry independent copies of the palette; bind them.

    This closes a hole that was already producing a dead measurement rather than a
    hypothetical one. ACCENT_PRESS is defined in ui.py and used nowhere in it -- the Tk
    window has no press state -- so the "button label, hover" row in APPROVED measures a
    Python constant that only the page paints. Most rows have that shape to some degree:
    they are read from `ui` and stand in for a surface the phone renders from its own
    file. Without this, editing one file's hexes and not the other's leaves every
    assertion in this module green while the two screens diverge.

    The same rule tests/test_batching.py states for its own duplicated constants: a guard
    that goes quiet when its target is renamed is worse than no guard. `_page_token`
    asserts rather than skips for that reason.

    Compared case-insensitively -- #17324D and #17324d are the same colour, and a case
    difference is not a defect worth a red suite.
    """
    assert _page_token(css_token).lower() == getattr(ui, py_name).lower(), (
        f"--{css_token} in upload.html and ui.{py_name} have drifted apart; the two "
        "surfaces are meant to be one palette. Fix whichever is wrong -- do not relax "
        "this."
    )


CSS_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
# `button` as an element selector only. The trailing class excludes `.` and `#` so that
# `button.ghost` and `button.tab` -- already scoped to a class no tab carries, or to the
# tabs themselves -- are not read as the bare element form this guards against.
BARE_BUTTON = re.compile(r"(?<![\w.#-])button(?![\w\-.#])")


# Both exclusions the accent press fill must carry, with what each one is protecting.
REQUIRED_EXCLUSIONS = {
    ":not(.tab)": "the tab bar (inactive label drops to 2.36:1; the active pill's "
                  "--outline ring collapses to 1.24:1)",
    ":not(.ghost)": "the ghost button (flips to the solid accent fill it is defined "
                    "as not having)",
}


def test_no_button_rule_repaints_the_tabs_or_the_ghost():
    """The tabs and the ghost are <button>s, so a bare `button:hover` rule matches them.

    This is the exact defect that shipped: `button:hover:not(:disabled)` is (0,2,1) --
    `:not()` takes its argument's specificity -- which beats `.tab` (0,1,0) and
    `.tab.active` (0,2,0). Only `background` was overridden, so an inactive tab hovered
    was --text-2 on --accent-press at 2.36:1, and the active pill's --outline ring
    collapsed to 1.24:1. On iOS Safari :hover latches on tap, so tapping a direction tab
    -- the page's primary gesture -- left it there until the user tapped elsewhere.

    The fix is a `:not()` exclusion, which is a MATCHING guarantee and therefore immune
    to any later specificity change. This asserts both exclusions are still spelled.

    :not(.ghost) is checked for a reason the tab case does not need. The tab press rule
    is (0,4,2) and outranks the (0,4,1) accent rule, so the tabs keep a specificity
    backstop even if their exclusion is dropped. The ghost press rule is (0,3,1), BELOW
    the accent rule, so it wins by the exclusion and nothing else -- delete :not(.ghost)
    and the ghost silently goes orange with no cascade left to catch it. Same class of
    defect as the tab case, one rung more fragile, and that is why both are asserted
    here rather than only the one that shipped broken.

    Splits the selector LIST on commas and judges each one alone. The first version did
    not, and a mutation proved it worthless: the accent rule is two comma-separated
    selectors, so stripping an exclusion from the `:hover` half left the `:active` half's
    copy in the same string and the substring check still found one. The exact defect
    under test went undetected while every test in this file passed. Do not collapse this
    back to a whole-string check.

    Narrow by construction, and worth saying so: it looks only at fill-changing
    interactive rules whose selector starts from the bare element. A tab or ghost
    repainted from some other selector, or by a property other than background, walks
    straight past it.
    """
    offenders = []
    for selector_list, body in CSS_RULE.findall(_page_stylesheet()):
        if "background" not in body:
            continue
        for selector in selector_list.split(","):
            selector = selector.strip()
            if selector.startswith("@"):
                continue
            if not BARE_BUTTON.search(selector):
                continue
            if ":hover" not in selector and ":active" not in selector:
                continue
            for exclusion, protects in REQUIRED_EXCLUSIONS.items():
                if exclusion not in selector:
                    offenders.append(
                        f"{selector}\n      needs {exclusion} -- protects {protects}"
                    )
    assert not offenders, (
        "these rules repaint a control that is not meant to take the accent fill:\n  "
        + "\n  ".join(offenders)
    )


# The three message elements that carry state no other control announces. Two are static
# markup; the third is built per batch card in batchCard().
LIVE_REGION_IDS = ("pin-msg", "receive-msg")


def test_status_messages_declare_a_live_region():
    """Asserts the role="status" attributes are SPELLED. It does not test announcement.

    Worth being blunt about the gap, because the name of this test could be read as more
    than it does. `role="status"` implies aria-live="polite" and aria-atomic="true", which
    is the right pairing for all three of these -- the text is written in, the element is
    never focused, and nothing else signals the change. Whether a screen reader actually
    announces it depends on the region existing before the write, on the engine, and on
    the user's settings, none of which a regex can see.

    Why it is here at all: WCAG 2.1 SC 4.1.3 Status Messages is Level AA, the level this
    file encodes everywhere else, and the page had no live region of any kind. It also
    props up an argument made in upload.html -- the disabled button is allowed to sit at
    1.77:1 because the adjacent .msg restates its state, and that restatement is only
    reaching a sighted user unless the .msg is a live region.
    """
    page = _page_css()
    missing = [
        element_id for element_id in LIVE_REGION_IDS
        if not re.search(rf'id="{element_id}"[^>]*role="status"', page)
    ]
    assert not missing, (
        f"these message elements lost role=\"status\": {missing}. They carry state "
        "nothing else announces -- a wrong pairing code, or the outbox being empty."
    )
    # The per-card status element is created in batchCard(), so it is checked as a call
    # rather than as an attribute.
    assert page.count('setAttribute("role", "status")') == 1, (
        "batchCard() must set role=status on the per-card status element, which carries "
        "prepare progress, the couldn't-load error and the fallback instruction"
    )
