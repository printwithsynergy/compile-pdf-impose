"""CLI tests for ``compile-pdf impose``."""

from __future__ import annotations

import json
from pathlib import Path

import pikepdf
from click.testing import CliRunner

from compile_pdf.cli import cli


def test_impose_cli_round_trips(tmp_path: Path, four_page_content_pdf: bytes) -> None:
    in_path = tmp_path / "in.pdf"
    out_path = tmp_path / "out.pdf"
    layout_path = tmp_path / "layout.json"
    in_path.write_bytes(four_page_content_pdf)
    layout_path.write_text(
        json.dumps(
            {
                "sheet": {"width_pt": 1782, "height_pt": 1700},
                "cell": {"width_pt": 612, "height_pt": 792},
                "gutter": {"x_pt": 12, "y_pt": 12},
            }
        )
    )

    runner = CliRunner()
    result = runner.invoke(
        cli, ["impose", "--layout", str(layout_path), str(in_path), str(out_path)]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["sheets_written"] == 1
    assert payload["cells_per_sheet"] == 4
    assert payload["pdf_sha256"]

    pdf = pikepdf.open(out_path)
    try:
        assert len(pdf.pages) == 1
    finally:
        pdf.close()


def test_impose_cli_rejects_invalid_plan(tmp_path: Path, four_page_content_pdf: bytes) -> None:
    in_path = tmp_path / "in.pdf"
    out_path = tmp_path / "out.pdf"
    layout_path = tmp_path / "layout.json"
    in_path.write_bytes(four_page_content_pdf)
    layout_path.write_text(json.dumps({"sheet": {}}))

    runner = CliRunner()
    result = runner.invoke(
        cli, ["impose", "--layout", str(layout_path), str(in_path), str(out_path)]
    )
    assert result.exit_code == 3


def test_impose_cli_rejects_oversized_cell(tmp_path: Path, four_page_content_pdf: bytes) -> None:
    in_path = tmp_path / "in.pdf"
    out_path = tmp_path / "out.pdf"
    layout_path = tmp_path / "layout.json"
    in_path.write_bytes(four_page_content_pdf)
    layout_path.write_text(
        json.dumps(
            {
                "sheet": {"width_pt": 100, "height_pt": 100},
                "cell": {"width_pt": 612, "height_pt": 792},
            }
        )
    )

    runner = CliRunner()
    result = runner.invoke(
        cli, ["impose", "--layout", str(layout_path), str(in_path), str(out_path)]
    )
    assert result.exit_code == 4


def test_impose_schema_dumps_json_schema() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["impose-schema"])
    assert result.exit_code == 0
    schema = json.loads(result.output)
    assert "properties" in schema


def test_top_level_help_lists_impose() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "impose" in result.output
