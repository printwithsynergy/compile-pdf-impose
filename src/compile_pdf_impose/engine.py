"""Impose engine — sheet-level step-and-repeat composition.

Calls :func:`codex_pdf.geom.tile_grid` for the canonical
``CellPlacement[]`` solution and drops each cell onto the output sheet
with pikepdf. **No Compile-side layout math** — every position +
rotation + flip comes from Codex (spec §4.1; consume-surface audit
script enforces the boundary).

Pipeline per call:

1. Open the input PDF and convert each page to a Form XObject via
   :meth:`pikepdf.Page.as_form_xobject`. Form XObjects are deduped
   per input-page index so ``page_mapping="repeat"`` only embeds the
   source once.
2. Forward the parsed plan to ``codex_pdf.geom.tile_grid`` and read
   back the :class:`TileResult`.
3. Compute sheet count from ``page_mapping`` and the cells-per-sheet
   yield. Build one front sheet per group; if ``back_side != "none"``
   append one back sheet per front sheet with the mirror transform.
4. Emit a single content stream per sheet that issues one
   ``q ... cm /CellSrcN Do ... Q`` block per cell.

Determinism: the output PDF is written via
``Pdf.save(deterministic_id=True, linearize=False)``; resource names
follow the pattern ``/CellSrc{i}`` so they are stable across
re-renders.
"""

from __future__ import annotations

import hashlib
import io
import math
from dataclasses import dataclass

import pikepdf
from codex_pdf.geom import Box, CellPlacement, MarksZone, TileGrid, TileResult, tile_grid
from pikepdf import Array, Dictionary, Name, Object, Pdf

from compile_pdf_impose.layout_schema import ImposePlan


@dataclass(frozen=True)
class ImposeResult:
    """Outcome of running an impose plan against an input PDF."""

    output_bytes: bytes
    pdf_sha256: str
    sheets_written: int
    cells_per_sheet: int
    input_pages: int


class ImposePlanError(ValueError):
    """The plan references something that cannot be reconciled with the
    input (zero pages, sheet smaller than a single cell, etc.). Raised
    before any mutation is committed."""


def apply_plan(input_bytes: bytes, plan: ImposePlan) -> ImposeResult:
    """Impose ``input_bytes`` onto sheets per ``plan``."""
    src = pikepdf.open(io.BytesIO(input_bytes))
    try:
        if len(src.pages) == 0:
            raise ImposePlanError("input PDF has no pages")

        layout = _solve_layout(plan)
        cells_per_sheet = len(layout.cells)
        if cells_per_sheet == 0:
            raise ImposePlanError(
                "codex tile_grid returned zero cells "
                "(sheet smaller than a single cell + marks_zone?)"
            )

        out = pikepdf.new()
        try:
            xobjects = _embed_input_pages(src, out)
            assignments = _page_assignments(
                input_pages=len(src.pages),
                cells_per_sheet=cells_per_sheet,
                page_mapping=plan.page_mapping,
            )
            sheets_written = 0
            for sheet_index, page_indices in enumerate(assignments):
                _emit_sheet(
                    out=out,
                    plan=plan,
                    layout=layout,
                    xobjects=xobjects,
                    page_indices=page_indices,
                    sheet_index=sheet_index,
                    is_back=False,
                )
                sheets_written += 1
                if plan.back_side != "none":
                    _emit_sheet(
                        out=out,
                        plan=plan,
                        layout=layout,
                        xobjects=xobjects,
                        page_indices=page_indices,
                        sheet_index=sheet_index,
                        is_back=True,
                    )
                    sheets_written += 1

            buf = io.BytesIO()
            out.save(buf, deterministic_id=True, linearize=False)
        finally:
            out.close()
    finally:
        src.close()

    output_bytes = buf.getvalue()
    return ImposeResult(
        output_bytes=output_bytes,
        pdf_sha256=hashlib.sha256(output_bytes).hexdigest(),
        sheets_written=sheets_written,
        cells_per_sheet=cells_per_sheet,
        input_pages=len(pikepdf.open(io.BytesIO(input_bytes)).pages),
    )


# --- Codex bridge -------------------------------------------------------


def _solve_layout(plan: ImposePlan) -> TileResult:
    """Resolve the per-cell placement solution for ``plan``.

    Two paths:

    * ``explicit_placements`` set — use the solver-provided boxes
      directly (sift-pdf stagger / gang / nest handoff). Compile does no
      grid math here; it wraps the pre-solved coordinates in codex's
      ``CellPlacement`` vocabulary so the downstream emit path is shared
      with the grid path.
    * otherwise — forward the plan's geometry knobs to ``codex.tile_grid``.

    Codex raises ``ValueError`` when the geometry is unsatisfiable
    (sheet smaller than cell, negative gutters, etc.) — re-raise as
    :class:`ImposePlanError` so callers see a single error type.
    """
    if plan.explicit_placements is not None:
        return _explicit_layout(plan)
    grid = TileGrid(
        sheet=Box(0.0, 0.0, plan.sheet.width_pt, plan.sheet.height_pt),
        cell_width=plan.cell.width_pt,
        cell_height=plan.cell.height_pt,
        gutter_x=plan.gutter.x_pt,
        gutter_y=plan.gutter.y_pt,
        marks_zone=MarksZone(
            top=plan.marks_zone.top_pt,
            right=plan.marks_zone.right_pt,
            bottom=plan.marks_zone.bottom_pt,
            left=plan.marks_zone.left_pt,
        ),
        cell_rotation=float(plan.cell_rotation),
        flip_per_row=plan.flip_per_row,
        bleed_handling=plan.bleed_handling,
        bleed=plan.bleed_pt,
    )
    try:
        return tile_grid(grid)
    except ValueError as exc:
        raise ImposePlanError(f"codex tile_grid rejected layout: {exc}") from exc


def _explicit_layout(plan: ImposePlan) -> TileResult:
    """Build a :class:`TileResult` from solver-provided explicit placements.

    Each :class:`ExplicitPlacement` becomes a codex ``CellPlacement`` so
    the cell-emit + post-condition pipeline is identical to the grid
    path. Compile performs no layout solving here — it wraps coordinates
    the upstream solver already computed (sift-pdf stagger / gang / nest).
    """
    placements = plan.explicit_placements or []
    if not placements:
        raise ImposePlanError(
            "explicit_placements is set but empty — no cells to place "
            "(omit the field for an empty plan, or provide at least one placement)"
        )

    cells: list[CellPlacement] = []
    union_x0 = union_y0 = float("inf")
    union_x1 = union_y1 = float("-inf")
    for ep in placements:
        if ep.x1_pt <= ep.x0_pt or ep.y1_pt <= ep.y0_pt:
            raise ImposePlanError(
                f"explicit placement {ep.source_ref!r} has a non-positive box "
                f"({ep.x0_pt},{ep.y0_pt})-({ep.x1_pt},{ep.y1_pt})"
            )
        box = Box(ep.x0_pt, ep.y0_pt, ep.x1_pt, ep.y1_pt)
        cells.append(
            CellPlacement(
                box=box,
                rotation=ep.rotation,
                flip_h=ep.flip_h,
                flip_v=ep.flip_v,
                row=ep.row if ep.row is not None else 0,
                col=ep.col if ep.col is not None else 0,
            )
        )
        union_x0 = min(union_x0, ep.x0_pt)
        union_y0 = min(union_y0, ep.y0_pt)
        union_x1 = max(union_x1, ep.x1_pt)
        union_y1 = max(union_y1, ep.y1_pt)

    sheet = Box(0.0, 0.0, plan.sheet.width_pt, plan.sheet.height_pt)
    tolerance = 1e-6
    if (
        union_x0 < -tolerance
        or union_y0 < -tolerance
        or union_x1 > plan.sheet.width_pt + tolerance
        or union_y1 > plan.sheet.height_pt + tolerance
    ):
        raise ImposePlanError(
            "explicit placements extend beyond the sheet "
            f"(union=({union_x0},{union_y0})-({union_x1},{union_y1}); "
            f"sheet={plan.sheet.width_pt}x{plan.sheet.height_pt})"
        )

    used = Box(union_x0, union_y0, union_x1, union_y1)
    return TileResult(
        sheet=sheet,
        cells=tuple(cells),
        rows=1,
        cols=len(cells),
        used=used,
        waste=sheet,
        cell_width=plan.cell.width_pt,
        cell_height=plan.cell.height_pt,
        gutter_x=plan.gutter.x_pt,
        gutter_y=plan.gutter.y_pt,
        marks_zone=MarksZone(
            top=plan.marks_zone.top_pt,
            right=plan.marks_zone.right_pt,
            bottom=plan.marks_zone.bottom_pt,
            left=plan.marks_zone.left_pt,
        ),
    )


# --- Form XObject embedding ---------------------------------------------


def _embed_input_pages(src: Pdf, out: Pdf) -> list[Object]:
    """Convert every input page to a Form XObject in ``out``.

    Result order matches ``src.pages``; ``out``'s resource registration
    happens later, per sheet, when each page is actually placed.
    """
    forms: list[Object] = []
    for page in src.pages:
        form = page.as_form_xobject()
        forms.append(out.copy_foreign(form))
    return forms


def _page_assignments(
    *, input_pages: int, cells_per_sheet: int, page_mapping: str
) -> list[list[int]]:
    """Group input page indices into per-sheet lists.

    Sequential mode paginates: pages 0..N → sheet 0..ceil(N/cells).
    Repeat mode emits one sheet that uses input page 0 in every cell.
    Trailing cells on the final sequential sheet are left empty
    (encoded as -1) — the engine skips empty cells silently.
    """
    if page_mapping == "repeat":
        return [[0] * cells_per_sheet]
    sheets: list[list[int]] = []
    n_sheets = math.ceil(input_pages / cells_per_sheet)
    for s in range(n_sheets):
        page_indices = []
        for c in range(cells_per_sheet):
            idx = s * cells_per_sheet + c
            page_indices.append(idx if idx < input_pages else -1)
        sheets.append(page_indices)
    return sheets


# --- Sheet emission -----------------------------------------------------


def _emit_sheet(
    *,
    out: Pdf,
    plan: ImposePlan,
    layout: TileResult,
    xobjects: list[Object],
    page_indices: list[int],
    sheet_index: int,
    is_back: bool,
) -> None:
    """Build a single sheet page with all cells composited via Form XObjects."""
    sheet_width = plan.sheet.width_pt
    sheet_height = plan.sheet.height_pt

    resources_xobjects = Dictionary()
    body_parts: list[bytes] = []
    used_indices: list[int] = []

    for cell_pos, page_idx in zip(layout.cells, page_indices, strict=True):
        if page_idx < 0:
            continue
        # Back-side mirror is applied at the cell-anchor level only;
        # rotation/flip from codex still hold for the per-cell content.
        if is_back:
            anchor_box, mirror_extra = _mirror_cell(
                cell_pos.box, sheet_width, sheet_height, plan.back_side
            )
        else:
            anchor_box = cell_pos.box
            mirror_extra = (1.0, 1.0)

        name = Name(f"/CellSrc{page_idx}")
        if name not in resources_xobjects:
            resources_xobjects[name] = xobjects[page_idx]
            used_indices.append(page_idx)

        # Use the cell box's own dimensions so explicit (non-grid)
        # placements with varying sizes anchor correctly. For grid cells
        # the box dimensions equal ``plan.cell`` exactly, so this is
        # byte-identical to the prior behaviour.
        body_parts.append(
            _cell_op(
                cell_box=anchor_box,
                rotation=cell_pos.rotation,
                flip_h=cell_pos.flip_h,
                flip_v=cell_pos.flip_v,
                back_mirror=mirror_extra,
                cell_w=cell_pos.box.x1 - cell_pos.box.x0,
                cell_h=cell_pos.box.y1 - cell_pos.box.y0,
                xobject_name=name,
            )
        )

    contents = b"".join(body_parts)

    sheet_page = pikepdf.Page(
        out.make_indirect(
            Dictionary(
                Type=Name.Page,
                MediaBox=Array([0, 0, sheet_width, sheet_height]),
                TrimBox=Array([0, 0, sheet_width, sheet_height]),
                Resources=Dictionary(XObject=resources_xobjects),
                Contents=out.make_stream(contents),
            )
        )
    )
    out.pages.append(sheet_page)
    _ = sheet_index, used_indices  # surfaced for future per-sheet lineage tagging


def _mirror_cell(
    cell: Box, sheet_w: float, sheet_h: float, back_mode: str
) -> tuple[Box, tuple[float, float]]:
    """Return a back-side-mirrored cell box plus a per-cell flip
    multiplier consumed by :func:`_cell_op`.

    work-and-turn mirrors about the vertical sheet midline (flip x).
    work-and-tumble mirrors about the horizontal sheet midline (flip y).
    """
    if back_mode == "work-and-turn":
        new_box = Box(sheet_w - cell.x1, cell.y0, sheet_w - cell.x0, cell.y1)
        return new_box, (-1.0, 1.0)
    if back_mode == "work-and-tumble":
        new_box = Box(cell.x0, sheet_h - cell.y1, cell.x1, sheet_h - cell.y0)
        return new_box, (1.0, -1.0)
    return cell, (1.0, 1.0)  # pragma: no cover — caller guards


def _cell_op(
    *,
    cell_box: Box,
    rotation: float,
    flip_h: bool,
    flip_v: bool,
    back_mirror: tuple[float, float],
    cell_w: float,
    cell_h: float,
    xobject_name: Name,
) -> bytes:
    """Emit ``q ... cm /CellSrcN Do Q`` for one cell.

    The transform places the source page's ``(0,0)`` at the cell's
    lower-left, then applies codex's rotation + flip + the back-side
    mirror multiplier. All numeric formatting goes through
    :func:`_fmt` so the output is byte-stable.
    """
    # Build the affine matrix as a 3x3 (only the top 2 rows reach PDF).
    a, b, c, d, e, f = _build_matrix(
        rotation=rotation,
        flip_h=flip_h ^ (back_mirror[0] < 0),
        flip_v=flip_v ^ (back_mirror[1] < 0),
        cell_w=cell_w,
        cell_h=cell_h,
        x0=cell_box.x0,
        y0=cell_box.y0,
    )
    return (
        f"q\n{_fmt(a)} {_fmt(b)} {_fmt(c)} {_fmt(d)} {_fmt(e)} {_fmt(f)} cm\n{xobject_name} Do\nQ\n"
    ).encode("ascii")


def _build_matrix(
    *,
    rotation: float,
    flip_h: bool,
    flip_v: bool,
    cell_w: float,
    cell_h: float,
    x0: float,
    y0: float,
) -> tuple[float, float, float, float, float, float]:
    """Return the (a, b, c, d, e, f) of the placement matrix.

    Source-page user-space ``(0, 0)`` lives at the lower-left of the
    page bounding box; the transform first applies rotation about that
    origin, then flips, then translates so the page's lower-left lands
    at ``(x0, y0)`` (with appropriate offsets to keep the rotated /
    flipped content inside the cell rect).
    """
    # Rotation matrix (PDF coords: counter-clockwise positive).
    theta = math.radians(rotation)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)

    # Apply flips by negating the corresponding axes.
    sx = -1.0 if flip_h else 1.0
    sy = -1.0 if flip_v else 1.0

    # Compose: translate(x0, y0) * rotate(theta) * flip(sx, sy)
    # Matrix entries (PDF stores columns: [a b ; c d ; e f]).
    a = sx * cos_t
    b = sx * sin_t
    c = -sy * sin_t
    d = sy * cos_t

    # Translation needs to compensate for rotation/flip placing content
    # outside the cell bounds. Test the transformed corners and shift
    # so the bounding box of the source aligns with (x0, y0)..(x1, y1).
    corners = [(0.0, 0.0), (cell_w, 0.0), (cell_w, cell_h), (0.0, cell_h)]
    txs = [a * px + c * py for (px, py) in corners]
    tys = [b * px + d * py for (px, py) in corners]
    e = x0 - min(txs)
    f = y0 - min(tys)
    return a, b, c, d, e, f


def _fmt(n: float) -> str:
    """Stable numeric formatting — fixed 4 decimals, no negative zero."""
    s = f"{n:.4f}"
    if s == "-0.0000":
        s = "0.0000"
    return s


__all__ = [
    "ImposePlanError",
    "ImposeResult",
    "apply_plan",
]
