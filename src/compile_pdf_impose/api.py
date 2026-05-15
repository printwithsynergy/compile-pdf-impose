"""FastAPI router for the impose producer.

Mounts under ``/v1/impose`` from :mod:`compile_pdf.api.main`. Single
endpoint today: ``POST /v1/impose/apply``.
"""

from __future__ import annotations

import base64
import hashlib

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from compile_pdf_core.cache import compute_cache_key, hash_canonical_plan
from compile_pdf_impose.engine import ImposePlanError, apply_plan
from compile_pdf_impose.layout_schema import ImposePlan
from compile_pdf_impose.verify import verify_impose
from compile_pdf_core.retention import (
    parse_consent,
    persist_if_opted_in,
    resolve_tenant,
)
from compile_pdf_core.version import (
    CODEX_DOCUMENT_SCHEMA_VERSION_PIN,
    IMPOSE_SCHEMA_VERSION,
    VERSION,
)

logger = structlog.get_logger(__name__)

router = APIRouter()


class ImposeApplyRequest(BaseModel):
    """Request envelope: an inline base64-encoded PDF + a plan."""

    model_config = {"extra": "forbid"}

    input_pdf_b64: str = Field(min_length=1)
    plan: ImposePlan


class ImposeApplyResponse(BaseModel):
    model_config = {"extra": "forbid"}

    output_pdf_b64: str
    pdf_sha256: str
    input_sha256: str
    plan_sha256: str
    cache_key: str
    cache_hit: bool = False
    sheets_written: int
    cells_per_sheet: int
    input_pages: int
    schema_version: str = IMPOSE_SCHEMA_VERSION
    compile_version: str = VERSION


@router.post("/apply", response_model=ImposeApplyResponse, status_code=status.HTTP_200_OK)
async def impose_apply(payload: ImposeApplyRequest, request: Request) -> ImposeApplyResponse:
    """Impose an inline base64-encoded PDF onto sheets per the plan."""
    try:
        input_bytes = base64.b64decode(payload.input_pdf_b64, validate=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"input_pdf_b64 is not valid base64: {exc}",
        ) from exc

    if not input_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="input is empty")

    input_sha256 = hashlib.sha256(input_bytes).hexdigest()
    plan_sha256 = hash_canonical_plan(payload.plan.model_dump(mode="json"))

    try:
        from codex_pdf.color import COLOR_SCHEMA_VERSION
        from codex_pdf.geom import GEOM_SCHEMA_VERSION
    except ImportError as exc:  # pragma: no cover — codex-pdf is a hard dep
        raise HTTPException(
            status_code=500, detail=f"codex-pdf surface unavailable: {exc}"
        ) from exc

    cache_key = compute_cache_key(
        producer="impose",
        input_sha256=input_sha256,
        canonical_plan_sha256=plan_sha256,
        codex_pdf_package_version=_resolve_codex_pdf_version(),
        color_schema_version=COLOR_SCHEMA_VERSION,
        geom_schema_version=GEOM_SCHEMA_VERSION,
        codex_document_schema_version=CODEX_DOCUMENT_SCHEMA_VERSION_PIN,
    )

    logger.info(
        "impose.apply.start",
        input_sha256=input_sha256[:16],
        plan_sha256=plan_sha256[:16],
        cache_key=cache_key[:16],
    )

    try:
        result = apply_plan(input_bytes, payload.plan)
    except ImposePlanError as exc:
        raise HTTPException(status_code=422, detail=f"plan rejected: {exc}") from exc

    verify = verify_impose(
        input_bytes=input_bytes,
        output_bytes=result.output_bytes,
        plan=payload.plan,
        expected_sheets=result.sheets_written,
        determinism_replay=False,
    )
    if not (verify.layer1_schema and verify.layer3_unchanged and verify.layer5_cell_extract):
        logger.error("impose.apply.verify_failed", failures=verify.failures)
        raise HTTPException(
            status_code=500,
            detail={"error": "verify failed", "failures": verify.failures},
        )

    consent = parse_consent(request)
    response = ImposeApplyResponse(
        output_pdf_b64=base64.b64encode(result.output_bytes).decode("ascii"),
        pdf_sha256=result.pdf_sha256,
        input_sha256=input_sha256,
        plan_sha256=plan_sha256,
        cache_key=cache_key,
        cache_hit=False,
        sheets_written=result.sheets_written,
        cells_per_sheet=result.cells_per_sheet,
        input_pages=result.input_pages,
    )
    retained = persist_if_opted_in(
        consent=consent,
        producer="impose",
        tenant=resolve_tenant(request),
        input_bytes=input_bytes,
        output_bytes=result.output_bytes,
        result=response.model_dump(mode="json"),
        input_sha256=input_sha256,
    )
    logger.info(
        "impose.apply.ok",
        output_sha256=result.pdf_sha256[:16],
        sheets_written=result.sheets_written,
        consent=consent,
        retained=retained,
    )
    return response


def _resolve_codex_pdf_version() -> str:
    """Read codex_pdf wheel version Compile was deployed against."""
    try:
        from codex_pdf import __version__ as codex_version
    except ImportError:
        return "unknown"
    return str(codex_version)
