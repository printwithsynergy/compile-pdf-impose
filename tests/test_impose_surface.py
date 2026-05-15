"""Surface test: impose producer must re-export codex_pdf.geom tile_grid family."""

from __future__ import annotations


def test_impose_module_reexports_tile_grid_family() -> None:
    from compile_pdf import impose

    for symbol in ("TileGrid", "TileResult", "CellPlacement", "tile_grid"):
        assert hasattr(impose, symbol), f"impose must re-export {symbol}"
        assert symbol in impose.__all__


def test_impose_symbols_match_canonical_imports() -> None:
    from codex_pdf import geom as codex_geom

    from compile_pdf import impose

    assert impose.TileGrid is codex_geom.TileGrid
    assert impose.TileResult is codex_geom.TileResult
    assert impose.CellPlacement is codex_geom.CellPlacement
    assert impose.tile_grid is codex_geom.tile_grid
