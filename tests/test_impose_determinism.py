"""Impose determinism — re-running the engine produces byte-identical output."""

from __future__ import annotations

from compile_pdf_impose.engine import apply_plan
from compile_pdf_impose.layout_schema import Cell, Gutter, ImposePlan, Sheet


def test_determinism_simple_2x2(four_page_content_pdf: bytes) -> None:
    plan = ImposePlan(
        sheet=Sheet(width_pt=1782, height_pt=1700),
        cell=Cell(width_pt=612, height_pt=792),
        gutter=Gutter(x_pt=12, y_pt=12),
    )
    a = apply_plan(four_page_content_pdf, plan)
    b = apply_plan(four_page_content_pdf, plan)
    assert a.output_bytes == b.output_bytes


def test_determinism_with_rotation_and_flip(four_page_content_pdf: bytes) -> None:
    plan = ImposePlan(
        sheet=Sheet(width_pt=1782, height_pt=1700),
        cell=Cell(width_pt=612, height_pt=792),
        gutter=Gutter(x_pt=12, y_pt=12),
        cell_rotation=90,
        flip_per_row=True,
    )
    runs = [apply_plan(four_page_content_pdf, plan).pdf_sha256 for _ in range(3)]
    assert len(set(runs)) == 1


def test_determinism_with_back_side(two_page_content_pdf: bytes) -> None:
    plan = ImposePlan(
        sheet=Sheet(width_pt=1300, height_pt=792),
        cell=Cell(width_pt=612, height_pt=792),
        gutter=Gutter(x_pt=12),
        back_side="work-and-turn",
    )
    a = apply_plan(two_page_content_pdf, plan)
    b = apply_plan(two_page_content_pdf, plan)
    assert a.output_bytes == b.output_bytes
