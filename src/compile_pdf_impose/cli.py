"""Click subcommand registration for ``compile-pdf impose``."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from compile_pdf_impose.engine import ImposePlanError, apply_plan
from compile_pdf_impose.layout_schema import ImposePlan, impose_plan_json_schema
from compile_pdf_impose.verify import verify_impose


def register(group: click.Group) -> None:
    """Attach the ``impose`` subcommand to the top-level CLI group."""

    @group.command("impose", help="Impose a 1-up PDF onto sheets.")
    @click.option(
        "--layout",
        "layout_path",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        required=True,
        help="JSON impose-plan document.",
    )
    @click.option(
        "--verify/--no-verify",
        default=True,
        help="Run four-layer post-condition checks before writing output.",
    )
    @click.argument(
        "input_path",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
    )
    @click.argument(
        "output_path",
        type=click.Path(dir_okay=False, path_type=Path),
    )
    def impose_cmd(
        layout_path: Path,
        input_path: Path,
        output_path: Path,
        verify: bool,
    ) -> None:
        plan_dict = json.loads(layout_path.read_text(encoding="utf-8"))
        try:
            plan = ImposePlan.model_validate(plan_dict)
        except Exception as exc:
            click.echo(f"plan validation failed: {exc}", err=True)
            sys.exit(3)

        input_bytes = input_path.read_bytes()
        try:
            result = apply_plan(input_bytes, plan)
        except ImposePlanError as exc:
            click.echo(f"plan rejected: {exc}", err=True)
            sys.exit(4)

        if verify:
            check = verify_impose(
                input_bytes=input_bytes,
                output_bytes=result.output_bytes,
                plan=plan,
                expected_sheets=result.sheets_written,
            )
            if not check.passed:
                click.echo("verify failed:", err=True)
                for failure in check.failures:
                    click.echo(f"  - {failure}", err=True)
                sys.exit(4)

        output_path.write_bytes(result.output_bytes)
        click.echo(
            json.dumps(
                {
                    "sheets_written": result.sheets_written,
                    "cells_per_sheet": result.cells_per_sheet,
                    "input_pages": result.input_pages,
                    "pdf_sha256": result.pdf_sha256,
                    "output": str(output_path),
                },
                indent=2,
            )
        )

    @group.command("impose-schema", hidden=True, help="Dump the impose-plan JSON Schema.")
    def impose_schema_cmd() -> None:
        click.echo(json.dumps(impose_plan_json_schema(), indent=2))
