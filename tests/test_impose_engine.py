"""Impose engine — end-to-end step-and-repeat behavior."""

from __future__ import annotations

import io

import pikepdf
import pytest
from pikepdf import Name

from compile_pdf_impose.engine import ImposePlanError, apply_plan
from compile_pdf_impose.layout_schema import Cell, Gutter, ImposePlan, Sheet


def _plan_2x2(**overrides) -> ImposePlan:
    return ImposePlan(
        sheet=Sheet(width_pt=1782, height_pt=1700),
        cell=Cell(width_pt=612, height_pt=792),
        gutter=Gutter(x_pt=12, y_pt=12),
        **overrides,
    )


def test_single_cell_imposition(two_page_content_pdf: bytes) -> None:
    """Sheet exactly the size of one cell → 1 cell, 2 sheets for 2 pages."""
    plan = ImposePlan(
        sheet=Sheet(width_pt=612, height_pt=792),
        cell=Cell(width_pt=612, height_pt=792),
    )
    result = apply_plan(two_page_content_pdf, plan)
    assert result.cells_per_sheet == 1
    assert result.sheets_written == 2
    assert result.input_pages == 2


def test_2x2_step_and_repeat_one_sheet(four_page_content_pdf: bytes) -> None:
    """4 pages into a 2×2 grid → 1 sheet."""
    plan = _plan_2x2()
    result = apply_plan(four_page_content_pdf, plan)
    assert result.cells_per_sheet == 4
    assert result.sheets_written == 1


def test_repeat_mapping_yields_one_sheet(four_page_content_pdf: bytes) -> None:
    """page_mapping=repeat → only page 0 is referenced, single sheet."""
    plan = _plan_2x2(page_mapping="repeat")
    result = apply_plan(four_page_content_pdf, plan)
    assert result.sheets_written == 1
    out = pikepdf.open(io.BytesIO(result.output_bytes))
    try:
        xobjs = out.pages[0].obj[Name.Resources][Name.XObject]
        # Only /CellSrc0 should be present in repeat mode.
        assert list(xobjs.keys()) == [Name("/CellSrc0")]
    finally:
        out.close()


def test_work_and_turn_doubles_sheets(two_page_content_pdf: bytes) -> None:
    plan = ImposePlan(
        sheet=Sheet(width_pt=1300, height_pt=792),
        cell=Cell(width_pt=612, height_pt=792),
        gutter=Gutter(x_pt=12),
        back_side="work-and-turn",
    )
    result = apply_plan(two_page_content_pdf, plan)
    # 2 input pages, 2 cells per sheet → 1 front + 1 back sheet
    assert result.sheets_written == 2


def test_work_and_tumble_doubles_sheets(two_page_content_pdf: bytes) -> None:
    plan = ImposePlan(
        sheet=Sheet(width_pt=1300, height_pt=792),
        cell=Cell(width_pt=612, height_pt=792),
        gutter=Gutter(x_pt=12),
        back_side="work-and-tumble",
    )
    result = apply_plan(two_page_content_pdf, plan)
    assert result.sheets_written == 2


def test_engine_is_deterministic(four_page_content_pdf: bytes) -> None:
    plan = _plan_2x2(cell_rotation=90, flip_per_row=True)
    a = apply_plan(four_page_content_pdf, plan)
    b = apply_plan(four_page_content_pdf, plan)
    assert a.output_bytes == b.output_bytes
    assert a.pdf_sha256 == b.pdf_sha256


def test_sheet_smaller_than_cell_rejected(two_page_content_pdf: bytes) -> None:
    """Codex tile_grid raises ValueError; engine re-raises as ImposePlanError."""
    plan = ImposePlan(
        sheet=Sheet(width_pt=100, height_pt=100),
        cell=Cell(width_pt=612, height_pt=792),
    )
    with pytest.raises(ImposePlanError, match="codex tile_grid"):
        apply_plan(two_page_content_pdf, plan)


def test_sheet_uses_full_mediabox(four_page_content_pdf: bytes) -> None:
    plan = _plan_2x2()
    result = apply_plan(four_page_content_pdf, plan)
    out = pikepdf.open(io.BytesIO(result.output_bytes))
    try:
        mb = out.pages[0].obj[Name.MediaBox]
        assert [float(x) for x in mb] == [0, 0, plan.sheet.width_pt, plan.sheet.height_pt]
    finally:
        out.close()


def test_input_with_extra_pages_paginates(four_page_content_pdf: bytes) -> None:
    """5 input pages with 4 cells/sheet → 2 sheets (last has 1 occupied cell)."""
    # Build a 5-page PDF inline (fixture is 4-page).
    src = pikepdf.open(io.BytesIO(four_page_content_pdf))
    src.pages.append(
        pikepdf.Page(
            src.make_indirect(
                pikepdf.Dictionary(
                    Type=Name.Page,
                    MediaBox=pikepdf.Array([0, 0, 612, 792]),
                    Resources=pikepdf.Dictionary(),
                    Contents=src.make_stream(b"q 50 50 m 100 100 l S Q  % page-4"),
                )
            )
        )
    )
    buf = io.BytesIO()
    src.save(buf, deterministic_id=True, linearize=False)
    src.close()

    plan = _plan_2x2()
    result = apply_plan(buf.getvalue(), plan)
    assert result.sheets_written == 2
    assert result.input_pages == 5
