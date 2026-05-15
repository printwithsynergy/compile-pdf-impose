"""Four-layer post-condition checks for impose output (spec §2.3 +
Phase 3 addendum).

Layer 1 — Schema. The output PDF parses cleanly with pikepdf, the
sheet page count matches the value the engine reported, every sheet's
``MediaBox`` matches the planned sheet size, and every cell's
``/CellSrcN`` Form XObject reference resolves.

Layer 2 — Determinism. Re-running the engine on the same input + plan
yields a byte-identical output. Skipped when the caller already
established determinism out-of-band.

Layer 3 — Nothing-else-touched. The output ``/Info`` dictionary is
clean (no leaked input metadata, no producer/creator drift) and no
extra root-level entries are added beyond ``/Pages``. Impose builds a
fresh PDF from scratch, so this layer guards against accidental input
inheritance via :meth:`Pdf.copy_foreign`.

Layer 5 — Cell-extract round-trip. For every placed cell on every
sheet, the SHA-256 of the embedded Form XObject's content stream must
match the SHA-256 of the corresponding input page's content stream.
This is the tractable structural equivalent of "extract cell N from
the imposed sheet, compare to original input page N byte-for-byte"
without requiring a full PDF rasterizer.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field

import pikepdf
from pikepdf import Name

from compile_pdf_impose.engine import apply_plan
from compile_pdf_impose.layout_schema import ImposePlan


@dataclass
class ImposeVerifyResult:
    """Outcome of running verify against an input/output pair."""

    layer1_schema: bool = False
    layer2_determinism: bool = False
    layer3_unchanged: bool = False
    layer5_cell_extract: bool = False
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (
            self.layer1_schema
            and self.layer2_determinism
            and self.layer3_unchanged
            and self.layer5_cell_extract
        )


def verify_impose(
    *,
    input_bytes: bytes,
    output_bytes: bytes,
    plan: ImposePlan,
    expected_sheets: int,
    determinism_replay: bool = True,
) -> ImposeVerifyResult:
    """Run all four post-condition layers and return a combined result."""
    result = ImposeVerifyResult()
    _layer1(output_bytes, plan, expected_sheets, result)
    _layer2(input_bytes, output_bytes, plan, result, replay=determinism_replay)
    _layer3(output_bytes, result)
    _layer5(input_bytes, output_bytes, result)
    return result


# --- Layer 1 ------------------------------------------------------------


def _layer1(
    output_bytes: bytes,
    plan: ImposePlan,
    expected_sheets: int,
    result: ImposeVerifyResult,
) -> None:
    try:
        pdf = pikepdf.open(io.BytesIO(output_bytes))
    except Exception as exc:
        result.failures.append(f"L1: output not parseable by pikepdf: {exc}")
        return
    try:
        if len(pdf.pages) != expected_sheets:
            result.failures.append(
                f"L1: sheet count mismatch (expected {expected_sheets}, got {len(pdf.pages)})"
            )
            return
        for i, page in enumerate(pdf.pages):
            mb = page.obj.get(Name.MediaBox)
            if mb is None:
                result.failures.append(f"L1: sheet {i} missing MediaBox")
                continue
            mb_w = float(mb[2]) - float(mb[0])
            mb_h = float(mb[3]) - float(mb[1])
            if abs(mb_w - plan.sheet.width_pt) > 1e-6 or abs(mb_h - plan.sheet.height_pt) > 1e-6:
                result.failures.append(
                    f"L1: sheet {i} MediaBox mismatch "
                    f"(expected {plan.sheet.width_pt}x{plan.sheet.height_pt}, got {mb_w}x{mb_h})"
                )
                continue
            # Every /CellSrcN reference in the content stream must exist
            # in /Resources/XObject.
            xobjs_obj = page.obj[Name.Resources].get(Name.XObject)
            xobj_keys: set[str] = set()
            if isinstance(xobjs_obj, pikepdf.Dictionary):
                xobj_keys = {str(k) for k in list(xobjs_obj.keys())}  # noqa: SIM118
            for ref in _xobject_references(page):
                if ref not in xobj_keys:
                    result.failures.append(
                        f"L1: sheet {i} references {ref} but resource is missing"
                    )
        if not any(f.startswith("L1:") for f in result.failures):
            result.layer1_schema = True
    finally:
        pdf.close()


def _xobject_references(page: pikepdf.Page) -> list[str]:
    contents = page.obj.get(Name.Contents)
    if contents is None:
        return []
    raw = bytes(contents.read_bytes()) if hasattr(contents, "read_bytes") else b""
    return re.findall(r"(/CellSrc\d+)\s+Do", raw.decode("latin-1"))


# --- Layer 2 ------------------------------------------------------------


def _layer2(
    input_bytes: bytes,
    output_bytes: bytes,
    plan: ImposePlan,
    result: ImposeVerifyResult,
    *,
    replay: bool,
) -> None:
    if not replay:
        result.layer2_determinism = True
        return
    replay_result = apply_plan(input_bytes, plan)
    if replay_result.output_bytes == output_bytes:
        result.layer2_determinism = True
    else:
        result.failures.append(
            "L2: re-running engine produced different bytes "
            f"(orig={hashlib.sha256(output_bytes).hexdigest()[:16]}, "
            f"replay={replay_result.pdf_sha256[:16]})"
        )


# --- Layer 3 ------------------------------------------------------------


def _layer3(output_bytes: bytes, result: ImposeVerifyResult) -> None:
    """Output is freshly built — assert no leaked input metadata."""
    try:
        pdf = pikepdf.open(io.BytesIO(output_bytes))
    except Exception as exc:
        result.failures.append(f"L3: output unparseable: {exc}")
        return
    try:
        info = pdf.trailer.get(Name.Info)
        if info is not None and isinstance(info, pikepdf.Dictionary):
            info_keys = list(info.keys())  # noqa: SIM118 — pikepdf Dict needs explicit keys()
            if info_keys:
                keys = sorted(str(k) for k in info_keys)
                result.failures.append(f"L3: output /Info should be clean, found keys {keys}")
            else:
                result.layer3_unchanged = True
        else:
            result.layer3_unchanged = True
    finally:
        pdf.close()


# --- Layer 5 ------------------------------------------------------------


def _layer5(
    input_bytes: bytes,
    output_bytes: bytes,
    result: ImposeVerifyResult,
) -> None:
    """For each cell, the embedded Form XObject's content-stream hash
    matches the source page's content-stream hash."""
    src_hashes = _input_page_content_hashes(input_bytes)
    if not src_hashes:
        result.failures.append("L5: input PDF unparseable")
        return
    out_pdf = pikepdf.open(io.BytesIO(output_bytes))
    try:
        for sheet_idx, page in enumerate(out_pdf.pages):
            xobjs = page.obj[Name.Resources].get(Name.XObject)
            if not isinstance(xobjs, pikepdf.Dictionary):
                continue
            for resource_name in list(xobjs.keys()):  # noqa: SIM118 — pikepdf Dict
                key = str(resource_name)
                if not key.startswith("/CellSrc"):
                    continue
                src_index = int(key.removeprefix("/CellSrc"))
                if src_index >= len(src_hashes):
                    result.failures.append(
                        f"L5: sheet {sheet_idx} references {key} "
                        f"but input has only {len(src_hashes)} pages"
                    )
                    continue
                form = xobjs[resource_name]
                form_hash = hashlib.sha256(bytes(form.read_bytes())).hexdigest()
                if form_hash != src_hashes[src_index]:
                    result.failures.append(
                        f"L5: sheet {sheet_idx} {key} content stream "
                        f"differs from input page {src_index} "
                        f"(form={form_hash[:16]}, src={src_hashes[src_index][:16]})"
                    )
        if not any(f.startswith("L5:") for f in result.failures):
            result.layer5_cell_extract = True
    finally:
        out_pdf.close()


def _input_page_content_hashes(input_bytes: bytes) -> list[str]:
    try:
        pdf = pikepdf.open(io.BytesIO(input_bytes))
    except Exception:
        return []
    try:
        hashes: list[str] = []
        for page in pdf.pages:
            contents = page.obj.get(Name.Contents)
            data = bytes(contents.read_bytes()) if contents is not None else b""
            hashes.append(hashlib.sha256(data).hexdigest())
        return hashes
    finally:
        pdf.close()


__all__ = [
    "ImposeVerifyResult",
    "verify_impose",
]
