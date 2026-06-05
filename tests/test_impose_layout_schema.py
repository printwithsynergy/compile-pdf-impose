"""Impose plan schema — discriminated-union acceptance + JSON Schema export."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from compile_pdf_impose.layout_schema import (
    Cell,
    ExplicitPlacement,
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


def test_explicit_placements_default_none_and_optional() -> None:
    """``explicit_placements`` + ``stagger_mode`` are additive: omitting them
    keeps the schema's prior (uniform-grid) behaviour exactly."""
    plan = ImposePlan(
        sheet=Sheet(width_pt=1782, height_pt=1224),
        cell=Cell(width_pt=612, height_pt=792),
    )
    assert plan.explicit_placements is None
    assert plan.stagger_mode == "none"


def test_sift_explicit_handoff_dict_validates() -> None:
    """BEHAVIOR-LOCK: the exact dict shape sift-pdf's
    ``handoff.compile._explicit_plan()`` emits must validate against
    ImposePlan. Before the additive ``explicit_placements`` field this dict
    raised on the unknown key (model_config extra='forbid'); it now round-
    trips. This is the cross-repo handoff contract for the stagger / gang /
    nest tiers (sift-pdf STACK note: 'requires compile-pdf explicit_placements')."""
    sift_dict = {
        "schema_version": "1.0.0",
        "sheet": {"width_pt": 1782.0, "height_pt": 1700.0},
        "cell": {"width_pt": 612.0, "height_pt": 792.0},
        "gutter": {"x_pt": 0.0, "y_pt": 0.0},
        "marks_zone": {"top_pt": 0.0, "right_pt": 0.0, "bottom_pt": 0.0, "left_pt": 0.0},
        "cell_rotation": 0,
        "flip_per_row": False,
        "bleed_pt": 0.0,
        "bleed_handling": "none",
        "page_mapping": "sequential",
        "back_side": "none",
        "explicit_placements": [
            {
                "source_ref": "job-a",
                "x0_pt": 0.0,
                "y0_pt": 0.0,
                "x1_pt": 612.0,
                "y1_pt": 792.0,
                "rotation": 0.0,
                "flip_h": False,
                "flip_v": False,
            },
            {
                "source_ref": "job-b",
                "x0_pt": 306.0,
                "y0_pt": 804.0,
                "x1_pt": 918.0,
                "y1_pt": 1596.0,
                "rotation": 90.0,
                "flip_h": True,
                "flip_v": False,
            },
        ],
    }
    plan = ImposePlan.model_validate(sift_dict)
    assert plan.explicit_placements is not None
    assert len(plan.explicit_placements) == 2
    assert plan.explicit_placements[0].source_ref == "job-a"
    assert plan.explicit_placements[1].rotation == 90.0
    assert plan.explicit_placements[1].flip_h is True


def test_explicit_placement_extra_field_rejected() -> None:
    with pytest.raises(ValidationError):
        ExplicitPlacement(
            source_ref="x",
            x0_pt=0,
            y0_pt=0,
            x1_pt=1,
            y1_pt=1,
            bogus=True,  # type: ignore[call-arg]
        )


def test_explicit_placements_round_trip_json() -> None:
    original = ImposePlan(
        sheet=Sheet(width_pt=1782, height_pt=1700),
        cell=Cell(width_pt=612, height_pt=792),
        stagger_mode="half-drop-y",
        explicit_placements=[
            ExplicitPlacement(source_ref="a", x0_pt=0, y0_pt=0, x1_pt=612, y1_pt=792),
        ],
    )
    restored = ImposePlan.model_validate_json(original.model_dump_json())
    assert restored == original


def test_json_schema_advertises_explicit_placements() -> None:
    schema = impose_plan_json_schema()
    assert "explicit_placements" in schema["properties"]
    assert "stagger_mode" in schema["properties"]
    assert "ExplicitPlacement" in schema["$defs"]
