"""Impose plan schema — discriminated-union acceptance + JSON Schema export."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from compile_pdf_impose.layout_schema import (
    Cell,
    Gutter,
    ImposePlan,
    MarksZoneSpec,
    Sheet,
    impose_plan_json_schema,
)


def test_minimum_plan_accepted() -> None:
    plan = ImposePlan(
        sheet=Sheet(width_pt=1782, height_pt=1224),
        cell=Cell(width_pt=612, height_pt=792),
    )
    assert plan.schema_version == "1.0.0"
    assert plan.gutter == Gutter()
    assert plan.marks_zone == MarksZoneSpec()
    assert plan.cell_rotation == 0
    assert plan.flip_per_row is False
    assert plan.bleed_handling == "none"
    assert plan.page_mapping == "sequential"
    assert plan.back_side == "none"


def test_full_plan_accepted() -> None:
    plan = ImposePlan(
        sheet=Sheet(width_pt=1782, height_pt=1700),
        cell=Cell(width_pt=612, height_pt=792),
        gutter=Gutter(x_pt=12, y_pt=18),
        marks_zone=MarksZoneSpec(top_pt=18, right_pt=0, bottom_pt=18, left_pt=0),
        cell_rotation=90,
        flip_per_row=True,
        bleed_pt=9.0,
        bleed_handling="extend",
        page_mapping="repeat",
        back_side="work-and-turn",
    )
    assert plan.cell_rotation == 90
    assert plan.bleed_handling == "extend"
    assert plan.back_side == "work-and-turn"


def test_extra_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        ImposePlan(
            sheet=Sheet(width_pt=1, height_pt=1),
            cell=Cell(width_pt=1, height_pt=1),
            bogus=True,  # type: ignore[call-arg]
        )


def test_negative_dimensions_rejected() -> None:
    with pytest.raises(ValidationError):
        Sheet(width_pt=-1, height_pt=792)
    with pytest.raises(ValidationError):
        Cell(width_pt=612, height_pt=-1)


def test_invalid_rotation_rejected() -> None:
    with pytest.raises(ValidationError):
        ImposePlan(
            sheet=Sheet(width_pt=1782, height_pt=1224),
            cell=Cell(width_pt=612, height_pt=792),
            cell_rotation=45,  # type: ignore[arg-type]
        )


def test_invalid_bleed_handling_rejected() -> None:
    with pytest.raises(ValidationError):
        ImposePlan(
            sheet=Sheet(width_pt=1782, height_pt=1224),
            cell=Cell(width_pt=612, height_pt=792),
            bleed_handling="overlap",  # type: ignore[arg-type]
        )


def test_round_trip_json() -> None:
    original = ImposePlan(
        sheet=Sheet(width_pt=1782, height_pt=1700),
        cell=Cell(width_pt=612, height_pt=792),
        gutter=Gutter(x_pt=12, y_pt=12),
        cell_rotation=180,
        back_side="work-and-tumble",
    )
    j = original.model_dump_json()
    restored = ImposePlan.model_validate_json(j)
    assert restored == original


def test_json_schema_exports_with_required_fields() -> None:
    schema = impose_plan_json_schema()
    assert "$defs" in schema
    assert "sheet" in schema["properties"]
    assert "cell" in schema["properties"]
    # Sheet/Cell are required (no defaults)
    assert "sheet" in schema["required"]
    assert "cell" in schema["required"]
