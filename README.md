# compile-pdf-impose

Sheet-level step-and-repeat layout for CompilePDF.

Layout solved by `codex_pdf.geom.tile_grid`; this package drops cells via `pikepdf`. Configurable sheet, gutter, cell rotation, page mapping. Back-side modes: work-and-turn, work-and-tumble. Cell-extract round-trip verifier (Layer 5) confirms every cell matches its source page SHA-256.

## Install

```bash
uv pip install compile-pdf-impose
```

## Position in the stack

One of four [CompilePDF](https://compilepdf.com) producers (trap, impose, marks, rewrite). Each lives in its own repo and PyPI package so you install only what you need. Producers depend on `compile-pdf-core`, never on each other.

- Repo: https://github.com/printwithsynergy/compile-pdf-impose
- Deployment host: https://github.com/printwithsynergy/compile-pdf
- License: AGPL-3.0-or-later
