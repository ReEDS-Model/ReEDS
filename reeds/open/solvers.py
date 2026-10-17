"""Solver plumbing: make HiGHS (from the highspy wheel) visible to pyoptinterface."""
from __future__ import annotations

import glob
import os
import sys


def load_highs() -> None:
    from pyoptinterface import highs
    try:
        if highs.autoload_library():
            return
    except Exception:
        pass
    import highspy
    libs = sorted(glob.glob(os.path.join(os.path.dirname(highspy.__file__), "libhighs.*")))
    libs.append(os.path.join(sys.prefix, "Library", "bin", "highs.dll"))
    for lib in libs:
        if os.path.exists(lib) and highs.load_library(lib):
            return
    raise RuntimeError("Could not load the HiGHS shared library for pyoptinterface")
