"""Impose producer — sheet-level step-and-repeat layout.

Per spec §4.1 — consumes ``codex_pdf.geom.tile_grid`` (with the
GEOM_SCHEMA_VERSION 1.1.0 extension for ``cell_rotation``,
``flip_per_row``, ``bleed_handling``, ``CellPlacement``) as the
canonical layout primitive. No Compile-side layout math.

Codex surface consumed:

- :func:`codex_pdf.geom.tile_grid` — the canonical step-and-repeat solver.
- :class:`codex_pdf.geom.TileGrid` — input shape.
- :class:`codex_pdf.geom.TileResult` — output container.
- :class:`codex_pdf.geom.CellPlacement` — per-cell anchor + transform.
"""

from __future__ import annotations

from codex_pdf.geom import CellPlacement, TileGrid, TileResult, tile_grid

IMPOSE_SCHEMA_VERSION = "1.1.0"
"""Schema version for impose-plan documents and the ``POST /v1/impose/apply``
response shape.

1.1.0 (additive): adds the optional ``explicit_placements`` list +
``stagger_mode`` field so sift-pdf's stagger / gang / nest solver output can be
honored by the writer. Backward-compatible — grid plans validate and render
byte-identically to 1.0.0.

Pinned locally here (rather than re-exported from ``compile_pdf_core.version``)
so the impose producer can advance its own schema version independently of the
shared core wheel; ``compile_pdf_core`` will catch up on its next release."""

__all__ = [
    "CellPlacement",
    "IMPOSE_SCHEMA_VERSION",
    "TileGrid",
    "TileResult",
    "tile_grid",
]
