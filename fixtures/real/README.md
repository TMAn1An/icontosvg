# Real fixture: finance-icon-sheet.jpg

Source: supplied in the `IconSheetStudio_From_Scratch_Assets/reference-assets/`
starter pack, used here as the first real end-to-end test input for the
Phase 1 vertical slice.

- **Format:** JPEG, 5x10 grid of line-style finance icons (dollar signs,
  wallets, cards, charts, etc.) on a white background.
- **Why this fixture:** it is a real, moderately compressed raster sheet
  with the JPEG noise (soft edges, slight ringing) the geometry pipeline
  needs to normalize into clean, stable centerlines — not a synthetic
  clean-edge test case.
- **Used by:** the slice-1 manual end-to-end run (upload -> preprocess ->
  detect one icon -> editable crop -> heuristic name -> centerline
  reconstruction -> SVG export -> render/compare). Not yet wired into the
  automated test suite; automated geometry tests use the synthetic
  fixtures in `tests/fixtures_gen/` instead.
- **Reference comparison:** `docs/reference/finance-icon-sheet.svg` is the
  professionally hand-built SVG version of this same sheet, used as a
  qualitative "what good looks like" target — not a golden file for exact
  automated comparison, since line count and construction style will
  legitimately differ.
