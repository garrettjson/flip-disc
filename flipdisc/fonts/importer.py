"""Copy a BDF font into ``assets/text/``, keeping only what text can draw.

Fonts such as X11's cover thousands of characters; this keeps the printable
ASCII ones and leaves the rest of the file as it was, header and copyright
included. Not imported by the server.

    uv run python -m flipdisc.fonts.importer SOURCE.bdf assets/text/x11/5x7.bdf

Then list the new file among a family's sizes in ``assets/text/fonts.toml``.
"""

import argparse
from pathlib import Path

from .bdf import PRINTABLE


def subset_bdf(source: str) -> str:
    """``source`` (a BDF file's text) without the non-printable characters."""
    out: list[str] = []
    char: list[str] | None = None
    kept = 0
    for line in source.splitlines():
        if line.startswith("STARTCHAR"):
            char, code = [], None
        if char is None:
            out.append(line)
            continue
        char.append(line)
        if line.startswith("ENCODING"):
            code = int(line.split()[1])
        if line.startswith("ENDCHAR"):
            if code in PRINTABLE:
                out.extend(char)
                kept += 1
            char = None
    return (
        "\n".join(
            f"CHARS {kept}" if line.startswith("CHARS ") else line for line in out
        )
        + "\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path)
    parser.add_argument("dest", type=Path)
    args = parser.parse_args()
    text = args.source.read_text(encoding="latin-1")
    args.dest.parent.mkdir(parents=True, exist_ok=True)
    args.dest.write_text(subset_bdf(text), encoding="latin-1")


if __name__ == "__main__":
    main()
