# Reference assets

Copied from the supplied `IconSheetStudio_From_Scratch_Assets` starter pack.
No previous IconSheetStudio codebase was consulted or copied.

- `finance-icon-sheet.svg` — professionally hand-built SVG version of the
  `fixtures/real/finance-icon-sheet.jpg` raster sheet. Used as a
  qualitative "what good looks like" comparison target for the Phase 1
  slice, not an automated golden file.
- `main1.svg`, `main2.svg`, `main3.svg` — examples of clean, professional,
  editable SVG icon construction (true primitives, minimal anchors, stable
  strokes). Used as a style reference for svg_model.py output.
- `rough-conversion-reference.png` — annotated example of the unacceptable
  rough-tracing failure mode (double/comb outlines from blurry edges) that
  the centerline-based line_mode.py pipeline is designed to avoid.

The UI screenshots from the starter pack (`ui/*.png`) were reviewed during
planning for dark-theme/workflow style conventions but were not copied
into the repository, since they depict a different product's forward
(name -> generate sheet) workflow rather than this app's reconstruction
workflow.
