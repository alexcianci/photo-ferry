"""Every function the phone page calls by name must exist somewhere the browser can find.

`src/photo_ferry/static/upload.html` is the entire phone-facing UI: one static file, read
once at import by `photo_ferry.server` and written straight to the socket. No template
layer, no build step, no JS toolchain, and none is being added. So nothing between the
bytes on disk and the browser ever looks at that JavaScript. Its only reader is a phone,
and the only report it files is a control that silently does nothing when tapped.

That has now shipped twice. A batch card went out with a button calling `loadOutbox()`
while no `loadOutbox` existed; later `action.onclick = () => prepareBatch(...)` went out
while `prepareBatch` was undefined. Both were found by reading the page, not by anything
automated. Both read as perfectly ordinary code at the call site -- the name is spelled
right, the arguments are right, and the only thing wrong is that nothing answers to it.

A review proposed this check when the second one was fixed, and it was deliberately
deferred: it would have been red on exactly those two identifiers, and a new guard that
is born failing gets disabled rather than obeyed. Both are defined now, so it goes green
today and stays green only while every call in the page still resolves.

Not to be confused with `tests/test_protected_identifiers.py`, which is a rename tripwire
for product-name strings baked into users' machines. Different concern, different failure,
no overlap; do not merge them.

WHAT THIS DOES NOT CATCH
------------------------
Stated up front, because a guard whose limits are discoverable only by reading its regexes
will be trusted for things it never checked. This is a regex scan of JavaScript from a
stdlib-only Python project with no JS parser available, and it is worth having only as long
as nobody mistakes it for a linter.

Every entry below was measured rather than reasoned about, but the list is the gaps that
have come up -- it is not a proof of completeness. An earlier draft of this paragraph said
"in full" and was wrong by four entries, which is the same overclaiming this file exists to
argue against. If you find another gap, add it here rather than assuming the list is closed.

  * Method calls, which are most of the page's calls. `foo.bar()` is skipped whole:
    neither `bar` nor the receiver `foo` is examined. Resolving `bar` needs types;
    checking `foo` needs real scope analysis of every local, parameter and destructured
    binding, and each name that analysis missed would be a false red on innocent code.
    Only bare `name(...)` calls are checked.
  * Dynamically built names: `window[key]()`, `obj[key]()`, anything assembled at runtime.
  * Scope, which is flattened. Every binding anywhere in the file resolves a call anywhere
    else, so a call to a name declared only inside some other function passes here and
    throws in the browser. The page is one flat script with every function at top level,
    so this costs little today; it would cost more if that changed.
  * Order. This checks existence, not reachability at the moment of the call. Function
    declarations hoist and `showTab` is genuinely called ~100 lines above its own
    definition, so requiring declaration-before-use would be wrong. The price is that
    `const f = () => {}` called above its own line passes here and throws on the phone.
  * Arity, argument types, `this`, or whether the function does the right thing. Only that
    the name exists.
  * Anything outside the `<script>` block -- a call in an HTML `on*=` attribute is
    invisible to this. The page has none today; every handler is bound from JavaScript.
  * Bindings this file's extractor does not model: the second and later declarators of a
    `const a = 1, b = 2;` statement, destructuring patterns, and imported names (there is
    no module syntax in the page -- it is one inline script -- so nothing extracts one).
    A call to any of those reports as unresolved. That is a false red, which is the safe
    direction -- loud, and the message says what to do -- but it is a real cost.
  * Class declarations. Nothing extracts a name from `class Foo {}`, so `new Foo()` reports
    as unresolved. Measured. The page has no classes.
  * Parameter lists containing parentheses. The parameter patterns are guarded with
    `[^()]*` to keep them away from nested parens, so `function g(a, b = h())` loses the
    WHOLE list -- `a` as well as `b`, not merely the parameter with the call in it -- and a
    call to either reports as unresolved. Measured.
  * Object-literal shorthand. `{ doThing() {} }` and `{ get size() {} }` are read as calls
    to `doThing` and `size`, which nothing declares, so both report as unresolved. Measured.
    The page uses neither form.
  * A regex literal that desyncs the scanner and then RESYNCS. This is the one gap known to
    fail green rather than red; it has its own paragraph at the end of this docstring,
    because a silent pass is a different kind of problem from a false red.

Comments and string literals ARE handled, by a small character scanner rather than by
regex, and that is deliberate: `_upload_html()` in `tests/test_version.py` strips HTML
comments and nothing else, and this page's `//` comments are dense with prose naming its
own functions (`showTab() calls loadOutbox`, `.then().catch()`, `status.after() inserts`).
Scanning those as code would mean a deleted function stayed "called" by its own obituary.
Template-literal interpolations are kept, because they contain real calls the page depends
on -- `${humanSize(file.size)}` and `` `/outbox/${encodeURIComponent(...)}` ``.

The scanner does not recognise regular-expression literals; the page contains none. If one
is added that contains a quote or a comment marker, the scanner will desync: it reads the
regex's contents as a string or a comment and carries on from there. The terminal-state
assertion in `_strip_noncode` is the net for that, and it is a good net rather than a proof
-- it catches a desync that runs to the end of the file, and MISSES one that resyncs on a
later stray quote.

That second case is the only way this file is known to fail green, and this page is exactly
the shape that produces it: its `//` comments are English prose, dense with apostrophes.
Measured, on this scanner:

    if (/'/.test(s)) { gone(); }
    // the page's helper
    function ok(){}
    ok();

The apostrophe in "page's" closes the string that the regex's own quote opened. The scan
resyncs, reports exactly one call -- `ok` -- finds it resolved, and returns green. `gone()`
was swallowed whole and nothing anywhere goes red. Closing this means recognising regex
literals, which needs the preceding-token rule because `/` is also division; that is a real
change to the scanner and it has not been made. What stands in for it is that the page has
never contained a regex literal, and that this paragraph is here so adding one is a decision
rather than an accident.
"""
import re
import sys
from pathlib import Path

_THIS = sys.modules[__name__]
_REPO_ROOT = Path(__file__).resolve().parent.parent
_UPLOAD_HTML = _REPO_ROOT / "src" / "photo_ferry" / "static" / "upload.html"

# A JavaScript identifier, near enough: the page is hand-written ASCII and always will be,
# since it is served to one browser and edited by hand. `$` is in here because the page's
# own DOM helper is literally named `$`, and a scan that could not see `$("pick")` would
# miss the single most-called name on the page.
_IDENT = r"[A-Za-z_$][A-Za-z0-9_$]*"

# Words that can be followed by `(` without being a call. Without this the scan reports
# `if`, `for` and `while` as undefined functions on every run, and whoever is reading the
# failure at 2am learns to ignore it. `new` is here so `new (expr)()` is not counted, but
# note `new File(...)` still is: the constructor name is checked like any other call.
_RESERVED = frozenset("""
    async await break case catch class const continue debugger default delete do else
    export extends finally for function if import in instanceof let new of return super
    switch this throw try typeof var void while with yield
""".split())

# Browser globals the page genuinely calls, each with the reason it is here. Enumerated one
# by one, never pattern-matched: a whitelist that admits "anything capitalised" or "anything
# the browser might have" makes this file pass by not looking, which is the same failure as
# a regex that matches nothing. `test_the_browser_global_whitelist_stays_minimal` keeps it
# honest from the other side by refusing entries the page has stopped calling.
#
# Deliberately absent: `document`, `navigator`, `URL`, `Math`, `JSON`, `console`,
# `setTimeout`. The page uses several of those, but only as the receiver of a dotted call
# (`URL.createObjectURL(...)`), and this scan does not look at dotted calls at all -- see
# the module docstring. Listing them would suggest a check that is not happening.
_BROWSER_GLOBALS = {
    "fetch": "every request the page makes: /auth, /upload, /outbox, /outbox/<id>",
    "encodeURIComponent": "the X-Filename header, and the outbox id in the fetch path",
    "String": "String(r.status), building the message for a thrown Error",
    "Error": "new Error(String(r.status)) on a non-ok response",
    "File": "new File([blob], name, {type}) for the files handed to navigator.share",
}

# Identifiers that must come out of the scan resolved, on pain of the whole scan being
# declared broken. This is the defence against the quiet failure this file is most exposed
# to: a regex that matches nothing, or that stops matching after someone restructures the
# page, and then reports success because it found no unresolved calls among no calls at
# all. Two of these names are the two that actually shipped broken.
_KNOWN_GOOD_CALLS = (
    "prepareBatch",
    "loadOutbox",
    "buildBatches",
    "humanSize",
    "showTab",
    "saveIndividually",
    "shareBatch",
)

# Floors, not exact counts. The page is edited often and an exact count would be a
# tripwire for ordinary work; these are set near half of what the page carries today
# (79 call sites, 19 distinct names, 71 declarations, measured 2026-08-27), which is far
# enough below to survive real edits and far enough above zero to catch an extractor that
# has quietly stopped extracting. If a legitimate edit takes the page under one of these,
# lower it in the same change and say so -- do not delete the assertion.
#
# What they detect is a STOPPED extractor, not a degraded one, and 40-of-79 is not a 49%
# safety margin: a mutation sweep found that silently dropping up to ~10% of the script from
# the tail passes every test in this file. Head and middle swallows are caught, but mostly by
# the resolve test going red rather than by these floors. `_KNOWN_GOOD_CALLS` below is the
# stronger tripwire of the two, because it pins named call sites rather than a total.
#
# The counts above are dated, not "current": this page is edited by tasks that have no
# reason to open this file, so the figures rot on their own. They are commentary -- nothing
# asserts them -- so a stale one misleads a reader without failing anything. Re-derive with
# `_scan()` before relying on one, and re-date it here in the same change.
_MIN_CALL_SITES = 40
_MIN_DISTINCT_CALLS = 12
_MIN_DECLARATIONS = 35


def _page_text() -> str:
    return _UPLOAD_HTML.read_text(encoding="utf-8")


def _script_block(text: str) -> tuple[str, int]:
    """The page's one inline script, and the offset it starts at (for file line numbers).

    Exactly one `<script>` must match, with no attributes. Zero means the page no longer
    has inline JavaScript and this whole file is either broken or obsolete. Two means half
    the page's calls are being scanned and half are not, which is precisely the silent
    partial pass this file exists to avoid. An attribute means either a `src=` pointing at
    JavaScript that is not in this file -- there is no build step, so that would be a real
    architectural change -- or a `type=`/`defer` whose effect on this scan nobody has
    thought about yet. All three are failures rather than skips.
    """
    found = list(re.finditer(r"<script([^>]*)>(.*?)</script\s*>", text, re.S | re.I))
    assert len(found) == 1, (
        f"Expected exactly one `<script>...</script>` in\n{_UPLOAD_HTML}\nbut found "
        f"{len(found)}.\n"
        "This guard checks that every function the page calls exists, and it can only do\n"
        "that while it can find the page's JavaScript.\n"
        "Zero: the inline script is gone. Either the phone UI has been restructured (in\n"
        "which case teach this file where the JavaScript lives now) or this file is\n"
        "obsolete and should be deleted with a reason.\n"
        "Two or more: a second script block was added and only one is being scanned, so\n"
        "half the page's calls are silently unchecked. Widen _script_block to scan them\n"
        "all -- deliberately, and adjust the floors -- rather than leaving it looking at\n"
        "one of them and reporting on the page."
    )
    attrs, body = found[0].group(1), found[0].group(2)
    assert not attrs.strip(), (
        f"The page's <script> tag now carries attributes: <script{attrs}>.\n"
        "It has always been a bare inline <script>, and this guard assumes that: it reads\n"
        "the element's own text as the page's complete JavaScript.\n"
        "If this is a `src=`, the JavaScript is no longer in upload.html, this scan is now\n"
        "reading an empty string, and the whole approach here needs revisiting -- note\n"
        "that a separate JS file would also mean a second static asset to ship, which the\n"
        "one-file design deliberately avoids.\n"
        "If it is a `type=` or `defer`, decide what it means for this scan and then allow\n"
        "it here explicitly."
    )
    # The script body's own offset in the page, taken from the match rather than searched
    # for again, so the line numbers in a failure point at upload.html and not at an
    # identical-looking earlier substring.
    return body, found[0].start(2)


def _strip_noncode(js: str) -> str:
    """Blank out comments and string bodies, keep template interpolations, same length.

    A character scanner and not a regex, for two reasons that are not stylistic. First,
    this page's `//` comments talk about its own functions constantly -- "showTab() calls
    loadOutbox", "See prepareBatch for why the two halves cannot be one" -- so scanning
    comments as code means a function deleted from the page stays "called" by the prose
    describing it, and a rename goes green on both halves being wrong. Second, template
    literals cannot simply be blanked: `${humanSize(file.size)}` and
    `/outbox/${encodeURIComponent(batch[i].id)}` are real calls, and the second is the
    only call to `encodeURIComponent` on the receive path.

    Replacements are one character per character, and newlines survive as newlines, so
    every offset in the result still maps to the same offset -- and the same line -- in the
    original file. That is what lets a failure name a line number the reader can open.

    Raises rather than returning a half-scan if it ends anywhere but in code or a `//`
    comment: an unterminated string, block comment or template means the scanner lost sync,
    and the most likely cause is a regex literal (see the module docstring) whose contents
    it read as code or as a string. A desynced scan produces garbage identifiers or, far
    worse, swallows the rest of the file and finds nothing wrong with it -- though note
    that a desync which resyncs escapes this check entirely, which the module docstring
    covers and this assertion cannot.
    """
    out = []
    mode = "code"
    interp = []          # one brace-depth counter per open `${ ... }`, innermost last
    i, n = 0, len(js)

    def blank(ch: str) -> str:
        # Newlines are kept so line numbers survive; everything else becomes a space.
        return "\n" if ch == "\n" else " "

    while i < n:
        ch = js[i]
        nxt = js[i + 1] if i + 1 < n else ""
        if mode == "code":
            if ch == "/" and nxt == "/":
                mode, out, i = "line", out + ["  "], i + 2
                continue
            if ch == "/" and nxt == "*":
                mode, out, i = "block", out + ["  "], i + 2
                continue
            if ch == "'":
                mode, out, i = "sq", out + [" "], i + 1
                continue
            if ch == '"':
                mode, out, i = "dq", out + [" "], i + 1
                continue
            if ch == "`":
                mode, out, i = "tpl", out + [" "], i + 1
                continue
            if interp and ch == "{":
                interp[-1] += 1
            elif interp and ch == "}":
                if interp[-1] == 0:
                    interp.pop()
                    mode, out, i = "tpl", out + [" "], i + 1
                    continue
                interp[-1] -= 1
            out.append(ch)
            i += 1
            continue
        if mode == "line":
            if ch == "\n":
                mode = "code"
                out.append("\n")
            else:
                out.append(" ")
            i += 1
            continue
        if mode == "block":
            if ch == "*" and nxt == "/":
                mode, out, i = "code", out + ["  "], i + 2
                continue
            out.append(blank(ch))
            i += 1
            continue
        if mode in ("sq", "dq"):
            if ch == "\\":
                out.append("  " if i + 1 < n else " ")
                i += 2
                continue
            if (ch == "'" and mode == "sq") or (ch == '"' and mode == "dq"):
                mode, out, i = "code", out + [" "], i + 1
                continue
            out.append(blank(ch))
            i += 1
            continue
        # mode == "tpl"
        if ch == "\\":
            out.append("  " if i + 1 < n else " ")
            i += 2
            continue
        if ch == "$" and nxt == "{":
            # Into the interpolation, which is real code and is kept as such. The counter
            # tracks brace depth so an object literal inside `${...}` does not end it.
            interp.append(0)
            mode, out, i = "code", out + ["  "], i + 2
            continue
        if ch == "`":
            mode, out, i = "code", out + [" "], i + 1
            continue
        out.append(blank(ch))
        i += 1

    # `line` is accepted alongside `code`: a `//` comment is terminated by the end of the
    # file exactly as validly as by a newline, so a script whose last line is a comment with
    # no trailing newline is well-formed, not desynced. It cannot arise from the page's
    # current `\n</script>` formatting, but a reflow or a minifier would produce it, and a
    # hard red blaming regex literals is the wrong thing to hand that reader. Every other
    # state stays a failure: an unterminated string, block comment or template is real.
    assert mode in ("code", "line") and not interp, (
        f"The comment/string scanner ran off the end of the page's JavaScript: it finished\n"
        f"in state {mode!r} with {len(interp)} unclosed template interpolation(s), meaning\n"
        "it never got back to code -- an unterminated string, block comment or template.\n"
        "It lost sync with the file, so everything it reports about which functions are\n"
        "called is now guesswork -- and the dangerous direction is that it swallowed the\n"
        "rest of the page and found nothing wrong.\n"
        "The known cause is a regular-expression literal. This scanner does not recognise\n"
        "one, and the page has never contained one; a regex holding a quote (say a\n"
        "character class with an apostrophe in it) or a `//` sequence will read as a string\n"
        "or a comment and eat the file from there. If a regex literal has just been added,\n"
        "either move it into a string and `new RegExp(...)`, or teach this scanner to\n"
        "recognise regex literals -- which needs the preceding-token rule, because `/` is\n"
        "also division. Do not delete this assertion: it is the only thing standing between\n"
        "a desynced scan and a green test."
    )
    return "".join(out)


def _declared_names(code: str) -> set[str]:
    """Every name the page binds, as best this can be read without a parser.

    Function declarations, the first declarator of each `const`/`let`/`var` (which covers
    `for (const item of ...)` too), function and arrow parameters, and `catch` bindings.

    Scope is flattened on purpose: this returns one set for the whole page, so a name
    bound inside one function will satisfy a call inside another. Modelling scope properly
    needs a parser. The page is one flat script whose functions are all top level, so what
    is lost is small -- and it is lost in the direction of a missed defect, not a false
    alarm, which for a guard that has to survive being trusted is the right way round.
    """
    names = set()
    names.update(re.findall(rf"\bfunction\s*\*?\s*({_IDENT})\s*\(", code))
    names.update(re.findall(rf"\b(?:const|let|var)\s+({_IDENT})", code))
    names.update(re.findall(rf"\bcatch\s*\(\s*({_IDENT})", code))
    # Parameters. Function headers first, then arrows: `(a, b) =>` and the bare `x =>`
    # form. `[^()]*` keeps these patterns away from nested parens, and the cost is bigger
    # than it looks: one parenthesis anywhere in the list fails the whole match, so
    # `function g(a, b = h())` collects NEITHER `a` NOR `b`. Measured, not assumed. Missed
    # bindings, never wrong ones -- a call to one reports unresolved, which is a false red
    # and the safe direction -- but the module docstring lists it because a false red on
    # innocent code is still a cost someone has to pay.
    param_lists = re.findall(rf"\bfunction\s*\*?\s*(?:{_IDENT})?\s*\(([^()]*)\)", code)
    param_lists += re.findall(r"\(([^()]*)\)\s*=>", code)
    for group in param_lists:
        for token in group.split(","):
            token = token.strip().lstrip(".")
            if re.fullmatch(_IDENT, token):
                names.add(token)
    names.update(re.findall(rf"(?<![\w$.])({_IDENT})\s*=>", code))
    return names - _RESERVED


def _called_names(code: str, script_start: int, page: str) -> list[tuple[str, int]]:
    """Every bare `name(` in the page's JavaScript, with the upload.html line it sits on.

    Bare only. A call is skipped when the identifier is preceded -- across whitespace and
    newlines, so multi-line `.then()` chains are covered -- by `.` or `?.`, because that
    is a property and this scan cannot resolve properties. It is also skipped when preceded
    by the word `function` -- with or without a generator `*` between -- because that is the
    declaration itself rather than a call. Without the `*` tolerance `function* gen(){}`
    counts its own declaration as a call site; harmless, since the name is declared too and
    so always resolves, but it pads the count the floors are read against.
    """
    calls = []
    for match in re.finditer(rf"(?<![\w$])({_IDENT})\s*\(", code):
        name = match.group(1)
        if name in _RESERVED:
            continue
        before = code[: match.start()].rstrip()
        if before.endswith(".") or before.endswith("?."):
            continue
        if re.search(r"\bfunction\s*\*?$", before):
            continue
        line = page.count("\n", 0, script_start + match.start()) + 1
        calls.append((name, line))
    return calls


def _scan() -> tuple[list[tuple[str, int]], set[str]]:
    """(calls, declared names) for the page as it stands on disk."""
    page = _page_text()
    body, start = _script_block(page)
    code = _strip_noncode(body)
    return _called_names(code, start, page), _declared_names(code)


def test_the_call_scan_still_reads_the_page():
    """Proves the extraction works before anything is concluded from what it found.

    This is the failure mode that matters most here, and it is not the one the file is
    named for. A regex scan of JavaScript that stops matching -- because the page was
    reformatted, because the script tag moved, because someone changed how handlers are
    bound -- finds no unresolved calls, because it finds no calls, and reports the page
    healthy forever after. Nothing in the result distinguishes "everything resolves" from
    "nothing was looked at". So the counts and the known-good names are asserted first and
    separately, and this test going red means the scan broke, not that the page did.

    The known-good list is not decoration. `prepareBatch` and `loadOutbox` are the two
    identifiers that actually shipped as calls to functions that did not exist; if the
    scan can no longer see those two call sites, it cannot see the defect it was written
    for.
    """
    calls, declared = _scan()
    names = {name for name, _ in calls}

    assert len(calls) >= _MIN_CALL_SITES, (
        f"The scan found only {len(calls)} call site(s) in upload.html; it expects at\n"
        f"least {_MIN_CALL_SITES} and the page carried 79 when last measured (2026-08-27).\n"
        "This is almost certainly the extraction breaking, not the page shrinking by\n"
        "half. Check, in order: is the `<script>` block still being found; does\n"
        "_strip_noncode still return code rather than blanks; did the page adopt a\n"
        "spelling _called_names does not recognise.\n"
        "If the page really did lose that many calls, lower the floor in this file in the\n"
        "same change and say why. Never delete the floor: without it, an extractor that\n"
        "matches nothing passes this suite silently, which is the exact hole this test is\n"
        "here to plug."
    )
    assert len(names) >= _MIN_DISTINCT_CALLS, (
        f"The scan found {len(names)} distinct called name(s), expected at least\n"
        f"{_MIN_DISTINCT_CALLS}. Found: {sorted(names)}\n"
        "A healthy scan of this page finds around 19. See the call-site floor above for\n"
        "what to check; the same causes produce both."
    )
    assert len(declared) >= _MIN_DECLARATIONS, (
        f"The scan found {len(declared)} declared name(s) in upload.html, expected at\n"
        f"least {_MIN_DECLARATIONS}.\n"
        "This half breaking is worse than the call half breaking, because it fails in the\n"
        "direction of noise: with no declarations found, every call in the page reports as\n"
        "unresolved and the real failure gets read as a broken page. Check _declared_names\n"
        "against how the page now spells its functions and its `const`s."
    )

    missing = [name for name in _KNOWN_GOOD_CALLS if name not in names]
    assert not missing, (
        f"The scan no longer sees these called: {missing}\n"
        f"It found: {sorted(names)}\n"
        "These are functions the page has and calls. If they are no longer being seen as\n"
        "calls, the scan has a blind spot it did not have before, and every real dangling\n"
        "call in that same blind spot is now invisible too.\n"
        "If one of these was genuinely renamed or removed from the page, update this list\n"
        "in the same change -- but read the diff first, because `prepareBatch` and\n"
        "`loadOutbox` are on it precisely because each has already shipped once as a call\n"
        "to a function that did not exist."
    )


def test_every_identifier_the_page_calls_resolves():
    """The guard itself: no bare call in upload.html names something that does not exist.

    A dangling call is invisible until a user taps the control. There is no console being
    watched, no error reporting, and no way for the PC to know -- the phone just does
    nothing, and the person holding it concludes the feature is broken, which it is.

    Only bare `name(...)` calls, and resolution is existence anywhere in the page plus a
    short whitelist of browser globals. The module docstring lists what that leaves out;
    read it before trusting this for more than it does.
    """
    calls, declared = _scan()
    known = declared | set(_BROWSER_GLOBALS)
    unresolved = sorted({(name, line) for name, line in calls if name not in known})
    assert not unresolved, (
        "upload.html calls "
        + ", ".join(f"`{name}()` at line {line}" for name, line in unresolved)
        + ",\nand nothing in the page declares those names.\n"
        "\n"
        "On the phone this is a control that does nothing when tapped: the page throws a\n"
        "ReferenceError into a console nobody is looking at, the handler stops there, and\n"
        "there is no other symptom. It has shipped twice -- a Prepare button bound to an\n"
        "undefined `prepareBatch`, and a card calling `loadOutbox` before it existed --\n"
        "and both times it was caught by someone reading the file.\n"
        "\n"
        "Three things this can be, in order of likelihood:\n"
        "  1. A real dangling call. Define the function, or fix the spelling. This is the\n"
        "     case this test exists for, and the fix belongs in upload.html.\n"
        "  2. A rename that missed a call site. Same fix, same place.\n"
        "  3. A binding this file's extractor cannot see -- the second declarator of a\n"
        "     `const a = 1, b = 2;`, a destructured parameter, an import. Those are known\n"
        "     gaps, listed in the module docstring. Widen `_declared_names` deliberately;\n"
        "     do not widen `_BROWSER_GLOBALS` to make the name go away, and do not add the\n"
        "     name to the whitelist unless it really is a browser global the page calls.\n"
        "\n"
        "If it is a browser global that is genuinely new to the page, add it to\n"
        "_BROWSER_GLOBALS with the one-line reason the page needs it -- the whitelist is\n"
        "enumerated on purpose, and a broad allowance would let the next real dangling\n"
        "call through."
    )


def test_the_browser_global_whitelist_stays_minimal():
    """Every whitelisted global must actually be called by the page, or it comes out.

    A whitelist is an allowance to stop checking, and allowances outlive their reasons: a
    name added for one call site stays after that call site is deleted, and then covers a
    future typo that happens to collide with it. The cost of keeping it honest is that
    removing the page's last `String(...)` turns this red -- a one-line fix in this file,
    with the message saying so. That is the cheaper direction, because the other one is a
    whitelist that grows by accretion until it is doing the passing.

    This does not police whether an entry is really a browser global rather than something
    the page ought to define; nothing here can tell those apart. It only refuses entries
    the page has stopped using.
    """
    calls, _ = _scan()
    names = {name for name, _ in calls}
    unused = sorted(set(_BROWSER_GLOBALS) - names)
    assert not unused, (
        f"_BROWSER_GLOBALS whitelists {unused}, which upload.html no longer calls.\n"
        "Delete the entry (or entries) from _BROWSER_GLOBALS in\n"
        f"{Path(__file__).name}. It is a dead allowance: it does nothing for the page and\n"
        "would silently resolve a future call of that name -- including a typo that landed\n"
        "on it -- instead of failing.\n"
        "If the call went away because the scan stopped seeing it rather than because the\n"
        "page stopped making it, test_the_call_scan_still_reads_the_page should be red\n"
        "too; fix that one first, since this failure is then a symptom."
    )


def _point_at(monkeypatch, tmp_path, script_body: str, *, wrapper: str | None = None) -> None:
    """Aim the guard at a stand-in page instead of the real one.

    Same device as `tests/test_batching.py`: proving a tripwire fires must never require
    putting a broken page in front of a user, not even for the length of one test run, and
    must never depend on the real page carrying a defect on purpose.
    """
    page = wrapper if wrapper is not None else (
        "<!doctype html>\n<body>\n<script>\n" + script_body + "\n</script>\n</body>\n"
    )
    fake = tmp_path / "upload.html"
    fake.write_text(page, encoding="utf-8")
    monkeypatch.setattr(_THIS, "_UPLOAD_HTML", fake)


_GOOD_SNIPPET = "function go() { return 1; }\ngo();\n"


def test_the_guard_fails_rather_than_going_quiet(monkeypatch, tmp_path):
    """Six ways this could stop watching, each proven to go red, and red for its own reason.

    Every row pins a fragment of the message it expects rather than accepting any
    AssertionError. Accepting any would let one broken helper -- one that raised on every
    input -- satisfy all six rows at once, and the table would then report six scenarios
    covered while covering none. That trap is not hypothetical: it is the shape of the
    bug this whole file guards against, one level up.
    """
    cases = (
        # (test to run, page/script, what is being broken, fragment of the right message)
        (test_every_identifier_the_page_calls_resolves,
         dict(script_body="function go() { return 1; }\ngone();\n"),
         "a call to a function nothing defines",
         "`gone()` at line"),
        (test_every_identifier_the_page_calls_resolves,
         dict(script_body="const label = `${ humanSizeMissing(1) }`;\n"),
         "a dangling call inside a template interpolation",
         "`humanSizeMissing()` at line"),
        (test_the_call_scan_still_reads_the_page,
         dict(script_body="// go(); prepareBatch(); loadOutbox();\nconst x = 1;\n"),
         # Pins the FLOOR firing on a scan that found no calls, and only that: with
         # _strip_noncode replaced by identity this row still passes, because three
         # comment-borne calls are under the floor of 40 either way. Comment blanking is
         # pinned instead by the green table's `// loadOutbox() is described here` row.
         "the call-site floor firing on a scan that found nothing",
         "call site(s) in upload.html"),
        (test_the_call_scan_still_reads_the_page,
         dict(wrapper="<!doctype html>\n<body>\n<p>no script here</p>\n</body>\n"),
         "the script block gone, so nothing at all is scanned",
         "but found 0."),
        (test_the_call_scan_still_reads_the_page,
         dict(wrapper="<!doctype html>\n<body>\n<script>\n" + _GOOD_SNIPPET
              + "\n</script>\n<script>\nfunction two() {}\n</script>\n</body>\n"),
         "a second script block, half the page unscanned",
         "but found 2."),
        (test_the_call_scan_still_reads_the_page,
         dict(script_body="const stuck = 'never closed;\ngo();\n"),
         "an unterminated string, i.e. the scanner losing sync",
         "ran off the end of the page's JavaScript"),
    )
    for test, page_kwargs, why, expected in cases:
        _point_at(monkeypatch, tmp_path, page_kwargs.pop("script_body", ""), **page_kwargs)
        try:
            test()
        except AssertionError as exc:
            assert expected in str(exc), (
                f"The guard fired on {why}, but not for that reason: the message was\n"
                f"expected to contain {expected!r} and instead said:\n{exc}\n"
                "A row that passes on the wrong failure is not testing the scenario it\n"
                "names. Fix the helper, or fix the fragment -- but do not loosen this back\n"
                "to catching any AssertionError at all."
            )
            continue
        raise AssertionError(
            f"The guard stayed green with {why}. It is no longer watching anything, so a\n"
            "call to a function that does not exist can now ship to the phone unnoticed --\n"
            "which is the whole fault this file exists to prevent, and which has already\n"
            "shipped twice. Fix the helper, not this test."
        )


def test_the_guard_accepts_the_shapes_the_page_actually_uses(monkeypatch, tmp_path):
    """The other half: green on legitimate code, so the red above means something.

    A guard that fires on everything is as useless as one that fires on nothing, and it is
    the more likely outcome of a regex scan of a language it cannot parse. Each row here is
    a spelling the real page uses, reduced to its smallest form: hoisted calls, arrow
    functions held in a `const`, a call inside a template interpolation, a parameter
    invoked as a callback, and `new` on a whitelisted global. If one of these starts
    failing, the page will start failing on the same shape -- and it will read as a defect
    in the page rather than in this file.
    """
    for snippet, why in (
        ("go();\nfunction go() {}\n",
         "a call above the declaration that hoists to meet it -- showTab does this"),
        ("const helper = () => 1;\nfunction go() { return helper(); }\ngo();\n",
         "an arrow function held in a const, the page's `$` helper in miniature"),
        ("function size(n) { return n; }\nconst s = `x ${size(1)} y`;\n",
         "a call inside a template interpolation, as humanSize is used"),
        ("function run(cb) { return cb(); }\n",
         "a parameter called as a callback"),
        ("const f = new File([], 'a.jpg');\nconst r = fetch('/outbox');\n",
         "whitelisted browser globals, one of them behind `new`"),
        ("// loadOutbox() is described here but not called\nfunction go() {}\ngo();\n",
         "a comment naming a function -- prose must neither satisfy nor trip the scan"),
        ("const msg = 'call nothingAtAll() from a string';\nfunction go() {}\ngo();\n",
         "a string naming a function that does not exist"),
    ):
        _point_at(monkeypatch, tmp_path, snippet)
        try:
            test_every_identifier_the_page_calls_resolves()
        except AssertionError as exc:
            raise AssertionError(
                f"The guard went red on {why}, which is valid code the real page uses:\n"
                f"{snippet}\n"
                f"It said:\n{exc}\n"
                "Fix the extractor in this file. Do NOT 'fix' upload.html to avoid the\n"
                "shape -- a guard that dictates how the page may be written, on grounds it\n"
                "cannot parse it, will be deleted rather than obeyed, and rightly."
            ) from None
