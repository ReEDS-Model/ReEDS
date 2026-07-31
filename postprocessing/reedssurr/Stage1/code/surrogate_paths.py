"""
Central resolver for where trained surrogate model artefacts (``*.joblib``)
live on disk.

Rationale
---------
The ``*.joblib`` model files are large (hundreds of MB) and must NOT live inside
the ReEDS git repository (GitHub rejects >100 MB files and they pollute every
branch switch). Everything *else* a training run produces — ``summary.json``,
``per_output_metrics_*.csv``, parity plots, ``eval/`` diagnostics — stays in the
repo under ``<stage>/outputs/<layer>/`` because it is small and worth versioning.

Only the ``models/`` subfolder is redirected out of the repo to a location such
as OneDrive.

Resolution order for the models root
-------------------------------------
1. Environment variable ``REEDSSURR_MODELS_DIR`` (highest priority — lets a
   teammate on another machine point at their own copy).
2. The built-in default below (the original author's OneDrive project folder).

Layout under the models root mirrors the repo:
    <models_root>/<Stage>/<layer>/models/<model_name>.joblib
e.g.
    <models_root>/Stage1/overall/models/rf.joblib
    <models_root>/Stage2/regional_premerge/models/rf.joblib
"""

from __future__ import annotations

import os
from pathlib import Path

# Default OneDrive location (override with the REEDSSURR_MODELS_DIR env var).
_DEFAULT_MODELS_ROOT = (
    r"C:\Users\ychen10\OneDrive - NREL\Project 18 - ReEDS Surrogate"
    r"\reedssurr_models"
)


def models_root() -> Path:
    """Return the root directory that holds all model artefacts."""
    return Path(os.environ.get("REEDSSURR_MODELS_DIR", _DEFAULT_MODELS_ROOT))


def resolve_models_dir(output_dir: str | os.PathLike) -> Path:
    """Map a repo ``output_dir`` to the external ``models/`` directory.

    ``output_dir`` is the per-layer results directory inside the repo, e.g.
    ``.../reedssurr/Stage1/outputs/overall``. We extract the stage
    (``Stage1`` / ``Stage2``) and the layer (``overall``, ``regional``,
    ``overall_premerge``, ``regional_premerge``) and rebuild the path under
    :func:`models_root`.

    Falls back gracefully: if the expected ``<stage>/outputs/<layer>`` shape is
    not found, we simply return ``<output_dir>/models`` (the legacy in-repo
    location) so nothing breaks in unusual layouts.
    """
    out = Path(output_dir).resolve()
    layer = out.name                       # e.g. 'overall'
    # out.parent is '<stage>/outputs'; its parent is '<stage>'.
    outputs_dir = out.parent
    stage_dir = outputs_dir.parent
    stage = stage_dir.name                 # e.g. 'Stage1'

    if outputs_dir.name.lower() == "outputs" and stage.lower().startswith("stage"):
        return models_root() / stage / layer / "models"

    # Unknown layout — keep artefacts next to the other outputs.
    return out / "models"
