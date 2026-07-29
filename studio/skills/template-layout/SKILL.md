---
name: template-layout
description: Classify PowerPoint QBR template slides and shapes into the Studio vocabulary with confidence scores. Use when asked to label slide purposes or shape roles for a template descriptor.
---

# Template layout classification

You are labelling a client-supplied QBR PowerPoint template so the deterministic
fill engine knows what each slide and shape is for. Your labels are *suggestions*:
a deterministic validator rejects anything outside the vocabulary or referencing
an id that does not exist.

## Slide purposes (closed vocabulary)

`cover`, `agenda`, `divider`, `executive_summary`, `trading_summary`,
`product_deep_dive`, `country_view`, `swot`, `feedback`, `ranking`, `growth`,
`methodology`, `appendix`, `other`

## Shape roles (closed vocabulary)

`title`, `subtitle`, `kpi`, `commentary`, `chart`, `table`, `footer`, `source`,
`decorative`, `manual`, `label`

## Hard rules

1. Use ONLY slide indexes and shape ids present in the payload. Never invent ids.
2. Choose purposes and roles ONLY from the vocabularies above.
3. Report a confidence in [0, 1] for every label. Prefer honest low confidence
   over a confident guess — low-confidence labels are escalated to a human.
4. Externally-linked charts (think-cell) are `manual`; they cannot be auto-filled.
5. A slide whose title is like "Country (3)" or "Product (2)" is a `divider`.

## Judgment guidance

- Title text repeated from the slide title, or a shape named "Title", is `title`.
- Small bottom-of-slide text mentioning "Source", "Confidential" or methodology
  is `source`; other short bottom strips are `footer`.
- Text boxes carrying number-shaped tokens (currency, %, ranks) are `kpi`.
- Text boxes with ellipsis placeholders ("…") expect prose: `commentary`.
- Prefer the deterministic heuristic's label unless the slide's wider context
  (surrounding shapes, agenda position, layout name) clearly contradicts it —
  your output only replaces a heuristic label when your confidence is higher.
