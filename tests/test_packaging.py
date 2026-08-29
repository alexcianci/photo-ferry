import tomllib
from pathlib import Path


def test_runtime_dependencies_stay_pure_python():
    """Photo Ferry ships stdlib plus one pure-Python package, and that is a product
    claim rather than an implementation detail. Adding a compiled dependency (a Tcl
    extension, a wheel with a binary) is a decision to make deliberately, so it has to
    fail here first."""
    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["dependencies"] == ["segno==1.6.1"], (
        f"dependencies is now {data['project']['dependencies']!r}, not just segno.\n"
        "\"Stdlib plus one pure-Python dependency\" is a product claim, not an\n"
        "implementation detail -- this test is what makes breaking it deliberate\n"
        "instead of accidental.\n"
        "\n"
        "Two different things land here, and they have opposite remedies:\n"
        "  - A package was added. Ask whether it is pure-Python, and whether you\n"
        "    meant to give up the single-dependency claim -- a compiled dependency\n"
        "    (a Tcl extension, a wheel with a binary) is exactly what this guard\n"
        "    exists to catch. If you did mean it, update this list deliberately and\n"
        "    update the README's claim to match.\n"
        "  - segno itself was version-bumped. Update the literal here to match --\n"
        "    and also requirements.txt, which carries a second copy of the segno\n"
        "    pin, so a bump that only touches pyproject.toml leaves the two files\n"
        "    disagreeing.\n"
        "\n"
        "Do not edit the expected list here just to silence this without making\n"
        "that decision first."
    )


def test_every_window_icon_asset_ships_and_is_the_size_it_claims():
    """The title bar icon is the one users see every session, and nothing else notices
    when it breaks.

    `_set_window_icon` catches every exception, so a renamed or missing asset costs the
    icon silently -- the window simply comes up with Tk's default and no error is raised
    anywhere. The sizes matter as much as the presence: the whole point of shipping 16,
    32 and 48 alongside the 512 is that the window manager CHOOSES one per slot instead
    of resampling the big one down, which is what produced a smudged title bar.

    This does not check that the icon renders, only that every declared asset exists,
    parses as a PNG, and is square at its declared size. It is also the only test that
    would notice `static/*.png` being dropped from package-data in pyproject.toml.
    """
    import struct

    from photo_ferry.ui import ReceiverWindow

    root = Path(__file__).resolve().parents[1] / "src" / "photo_ferry"
    for name in ReceiverWindow.ICON_ASSETS:
        path = root / name
        assert path.is_file(), (
            f"{name} is declared in ReceiverWindow.ICON_ASSETS but is not on disk.\n"
            "_set_window_icon swallows the failure, so the app would launch with no\n"
            "icon and say nothing."
        )
        data = path.read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{name} is not a PNG"
        width, height = struct.unpack(">II", data[16:24])
        assert width == height, f"{name} is {width}x{height}; icons must be square"
        if name != "static/app-icon.png":
            declared = int(name.rsplit("-", 1)[1].split(".")[0])
            assert width == declared, (
                f"{name} claims {declared}px in its filename but is {width}px.\n"
                "The filename is what ICON_ASSETS selects on, so a mismatch means the\n"
                "window manager is handed a size it did not ask for."
            )
