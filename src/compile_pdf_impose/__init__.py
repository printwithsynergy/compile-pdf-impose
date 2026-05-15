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

from compile_pdf_core.version import IMPOSE_SCHEMA_VERSION

__all__ = [
    "CellPlacement",
    "IMPOSE_SCHEMA_VERSION",
    "TileGrid",
    "TileResult",
    "tile_grid",
]
