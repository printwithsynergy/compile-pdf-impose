"""registration_marks / crop_marks — plumb-only fields ported from compile-pdf
main so the satellite ImposePlan is a superset (it already carried
explicit_placements / stagger_mode)."""

from __future__ import annotations

from compile_pdf_impose.layout_schema import ImposePlan


def _base() -> dict:
    return {
        "sheet": {"width_pt": 864.0, "height_pt": 576.0},
        "cell": {"width_pt": 288.0, "height_pt": 144.0},
    }


def test_registration_and_crop_marks_round_trip() -> None:
    plan = ImposePlan.model_validate({**_base(), "registration_marks": True, "crop_marks": True})
    assert plan.registration_marks is True
    assert plan.crop_marks is True


def test_defaults_false() -> None:
    plan = ImposePlan.model_validate(_base())
    assert plan.registration_marks is False
    assert plan.crop_marks is False
