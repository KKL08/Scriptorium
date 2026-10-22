from __future__ import annotations

import difflib


def unified_diff(
    original: str,
    refined: str,
    fromfile: str = "original",
    tofile: str = "refined",
) -> str:
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            refined.splitlines(keepends=True),
            fromfile=fromfile,
            tofile=tofile,
        )
    )
