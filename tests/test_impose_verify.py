"""Impose verifier — four-layer post-condition checks."""

from __future__ import annotations

import io

import pikepdf
from pikepdf import Array, Name, String

from compile_pdf_impose.engine import apply_plan
from compile_pdf_impose.layout_schema import Cell, Gutter, ImposePlan, Sheet
from compile_pdf_impose.verify import verify_impose


def _plan(**overrides) -> ImposePlan:
    return ImposePlan(
        sheet=Sheet(width_pt=1782, height_pt=1700),
        cell=Cell(width_pt=612, height_pt=792),
        gutter=Gutter(x_pt=12, y_pt=12),
        **overrides,
    )


def test_verify_passes_on_clean_apply(four_page_content_pdf: bytes) -> None:
    plan = _plan()
    result = apply_plan(four_page_content_pdf, plan)
    v = verify_impose(
        input_bytes=four_page_content_pdf,
        output_bytes=result.output_bytes,
        plan=plan,
        expected_sheets=result.sheets_written,
    )
    assert v.passed, v.failures


def test_verify_layer1_detects_wrong_sheet_count(four_page_content_pdf: bytes) -> None:
    plan = _plan()
    result = apply_plan(four_page_content_pdf, plan)
    v = verify_impose(
        input_bytes=four_page_content_pdf,
        output_bytes=result.output_bytes,
        plan=plan,
        expected_sheets=99,  # lie about the sheet count
    )
    assert not v.layer1_schema
    assert any("sheet count mismatch" in f for f in v.failures)


def test_verify_layer1_detects_wrong_mediabox(four_page_content_pdf: bytes) -> None:
    plan = _plan()
    result = apply_plan(four_page_content_pdf, plan)
    pdf = pikepdf.open(io.BytesIO(result.output_bytes))
    pdf.pages[0].obj[Name.MediaBox] = Array([0, 0, 100, 100])
    out = io.BytesIO()
    pdf.save(out, deterministic_id=True, linearize=False)
    pdf.close()
    tampered = out.getvalue()
    v = verify_impose(
        input_bytes=four_page_content_pdf,
        output_bytes=tampered,
        plan=plan,
        expected_sheets=result.sheets_written,
    )
    assert not v.layer1_schema
    assert any("MediaBox mismatch" in f for f in v.failures)


def test_verify_layer3_detects_metadata_leak(four_page_content_pdf: bytes) -> None:
    plan = _plan()
    result = apply_plan(four_page_content_pdf, plan)
    pdf = pikepdf.open(io.BytesIO(result.output_bytes))
    pdf.docinfo[Name.Title] = String("leaked")
    out = io.BytesIO()
    pdf.save(out, deterministic_id=True, linearize=False)
    pdf.close()
    tampered = out.getvalue()
    v = verify_impose(
        input_bytes=four_page_content_pdf,
        output_bytes=tampered,
        plan=plan,
        expected_sheets=result.sheets_written,
    )
    assert not v.layer3_unchanged


def test_verify_layer5_detects_form_xobject_swap(four_page_content_pdf: bytes) -> None:
    """Replace a Form XObject's content with garbage — L5 should catch it."""
    plan = _plan()
    result = apply_plan(four_page_content_pdf, plan)
    pdf = pikepdf.open(io.BytesIO(result.output_bytes))
    xobjs = pdf.pages[0].obj[Name.Resources][Name.XObject]
    # Find the first form xobject and corrupt it.
    first_name = next(iter(xobjs.keys()))
    form = xobjs[first_name]
    form.write(b"q garbage Q")
    out = io.BytesIO()
    pdf.save(out, deterministic_id=True, linearize=False)
    pdf.close()
    tampered = out.getvalue()
    v = verify_impose(
        input_bytes=four_page_content_pdf,
        output_bytes=tampered,
        plan=plan,
        expected_sheets=result.sheets_written,
    )
    assert not v.layer5_cell_extract
    assert any("L5" in f for f in v.failures)


def test_verify_layer2_skip_when_replay_disabled(four_page_content_pdf: bytes) -> None:
    plan = _plan()
    result = apply_plan(four_page_content_pdf, plan)
    v = verify_impose(
        input_bytes=four_page_content_pdf,
        output_bytes=result.output_bytes,
        plan=plan,
        expected_sheets=result.sheets_written,
        determinism_replay=False,
    )
    assert v.layer2_determinism
