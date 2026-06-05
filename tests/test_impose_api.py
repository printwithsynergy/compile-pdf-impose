"""Integration tests for POST /v1/impose/apply."""

from __future__ import annotations

import base64

from compile_pdf.api.main import app
from fastapi.testclient import TestClient


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def test_impose_apply_round_trips(four_page_content_pdf: bytes) -> None:
    client = TestClient(app)
    response = client.post(
        "/v1/impose/apply",
        json={
            "input_pdf_b64": _b64(four_page_content_pdf),
            "plan": {
                "sheet": {"width_pt": 1782, "height_pt": 1700},
                "cell": {"width_pt": 612, "height_pt": 792},
                "gutter": {"x_pt": 12, "y_pt": 12},
            },
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sheets_written"] == 1
    assert body["cells_per_sheet"] == 4
    assert body["input_pages"] == 4
    assert body["pdf_sha256"]
    assert body["cache_key"]


def test_impose_apply_rejects_invalid_base64() -> None:
    client = TestClient(app)
    response = client.post(
        "/v1/impose/apply",
        json={
            "input_pdf_b64": "not-valid-base64!!!",
            "plan": {
                "sheet": {"width_pt": 612, "height_pt": 792},
                "cell": {"width_pt": 612, "height_pt": 792},
            },
        },
    )
    assert response.status_code == 400


def test_impose_apply_rejects_unparseable_plan(four_page_content_pdf: bytes) -> None:
    client = TestClient(app)
    response = client.post(
        "/v1/impose/apply",
        json={
            "input_pdf_b64": _b64(four_page_content_pdf),
            "plan": {"sheet": {"width_pt": 0, "height_pt": 0}},  # cell missing
        },
    )
    assert response.status_code == 422


def test_impose_apply_rejects_oversized_cell(four_page_content_pdf: bytes) -> None:
    """Sheet smaller than a cell → engine raises ImposePlanError → 422."""
    client = TestClient(app)
    response = client.post(
        "/v1/impose/apply",
        json={
            "input_pdf_b64": _b64(four_page_content_pdf),
            "plan": {
                "sheet": {"width_pt": 100, "height_pt": 100},
                "cell": {"width_pt": 612, "height_pt": 792},
            },
        },
    )
    assert response.status_code == 422


def test_contract_endpoint_lists_impose() -> None:
    client = TestClient(app)
    response = client.get("/v1/contract")
    assert response.status_code == 200
    endpoints = response.json()["endpoints"]
    assert any("/v1/impose/apply" in e for e in endpoints)


def test_same_input_same_plan_same_cache_key(four_page_content_pdf: bytes) -> None:
    client = TestClient(app)
    payload = {
        "input_pdf_b64": _b64(four_page_content_pdf),
        "plan": {
            "sheet": {"width_pt": 1782, "height_pt": 1700},
            "cell": {"width_pt": 612, "height_pt": 792},
        },
    }
    a = client.post("/v1/impose/apply", json=payload).json()
    b = client.post("/v1/impose/apply", json=payload).json()
    assert a["cache_key"] == b["cache_key"]
    assert a["pdf_sha256"] == b["pdf_sha256"]
