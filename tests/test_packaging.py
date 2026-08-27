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
