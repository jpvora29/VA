---
name: pitch_report_design
description: Authoritative visual design spec for the client-ready Marsh pitch report (.docx).
# Machine-readable tokens — `document_builder/helpers/design_spec.py` parses this
# frontmatter into a DesignSpec, and `config/report_config.py` sources the palette
# + fonts from it. Hex values are 6-digit RGB WITHOUT a leading '#'.
palette:
  navy: "000F47"          # primary brand / headings, KPI values, table header fill
  electric_blue: "0B4BFF" # accents, sub-headings, links
  light_blue: "82BAFF"    # soft highlight
  white: "FFFFFF"
  dark: "1E2832"          # body text
  green_text: "2E7D32"    # favourable delta text
  red_text: "C53532"      # unfavourable delta text
  light_gray: "B9B6B1"
  gray: "505F73"          # captions / labels
  green_fill: "E8F5E9"    # favourable delta cell fill
  red_fill: "FDECEA"      # unfavourable delta cell fill
  header_fill: "000F47"   # table header band
  zebra_fill: "F7F9FD"    # alternating table row
  kpi_fill: "EEF2F8"      # KPI card background
  kicker_blue: "7396CD"   # muted blue kicker on the navy banner
  subtitle_blue: "9BB9E6" # soft blue banner subtitle
  cover_bg: "F4F7FC"      # light tint for cover accent panels
  rule_soft: "D0D8E8"     # hairline rule under section titles
  table_border: "D8DFF0"  # table cell hairline
fonts:
  heading: "Georgia Pro Light"
  body: "Arial"
sizes:
  heading: 28
  subheading: 18
  body: 10
  caption: 7
  section_title: 13
  kpi_value: 16
  kpi_label: 7
  table_header: 8.5
  table_body: 8.8
  cover_title: 40
  cover_subtitle: 20
  cover_kicker: 11
  cover_meta: 10
  page_header: 8
  page_footer: 8
# Reusable copy strings.
labels:
  kicker: "MARSH ICG  —  CARRIER PERFORMANCE REPORT"
  title: "Performance Analysis"
  banner_title: "Performance Analysis Builder"
  source: "Source — GPR, Carrier Survey"
  confidentiality: "Marsh ICG  —  Strictly Private & Confidential"
# Section order top-to-bottom in the rendered document.
section_order:
  - cover_page
  - header_banner
  - kpi_strip
  - executive_narrative
  - product_breakdown
  - whitespace_analysis
  - industry_analysis
  - segment_analysis
# Accent colour (palette key) for each analytical section's title rule.
section_accents:
  whitespace_analysis: red_text
  industry_analysis: navy
  segment_analysis: electric_blue
---

# Marsh Pitch Report — Design System

This skill is the single source of truth for how the carrier pitch report
(`document_builder/`) looks. The Python builder reads the frontmatter tokens above
and implements them deterministically — change a colour or font here and the
report follows. The prose below is the human-facing rationale and the rules the
builder encodes.

## Page furniture: cover, running header, footer

- **Cover page** (page 1, its own page): a centered title block on a clean white
  page with thin navy + red Marsh accent bands top and bottom. Shows the kicker,
  the large `title` in the heading font (navy), the carrier in electric blue, the
  `country • year` meta, a hairline divider, the prepared date, and the
  `confidentiality` line. Ends with a page break. No running header/footer here
  (`different_first_page_header_footer`).
- **Running header** (page 2+): a slim line — `banner_title` left in navy, and
  `carrier • country • year` right in gray — over a soft hairline rule.
- **Footer** (page 2+): `confidentiality` left in gray, centered `Page X of Y`
  via Word field codes, and the carrier right. Keep it 8pt and unobtrusive.

## Brand palette (Marsh)

- **Navy `#000F47`** — the primary brand colour. Use for headings, KPI values,
  table header bands, and section-title text. It anchors the page.
- **Electric Blue `#0B4BFF`** — accent. Sub-headings, the segment-analysis rule,
  and emphasis. Never use it for long body text.
- **Dark `#1E2832`** — body copy. High contrast, not pure black, for a softer read.
- **Gray `#505F73`** — captions, KPI labels, helper text.
- **Green `#2E7D32` / Red `#C53532`** with fills **`#E8F5E9` / `#FDECEA`** — the
  ONLY colours that carry meaning: green = directionally favourable movement,
  red = unfavourable. Never decorate with them; reserve them for deltas.

## Typography

- **Headings: Georgia Pro Light** — the banner title and large headings only.
- **Body: Arial** — everything else (body, tables, KPIs, captions).
- Sizes are fixed (see `sizes`): section titles 13pt navy bold; body 10pt;
  table headers 8.5pt white bold on navy; table body 8.8pt dark.

## KPI strip

- A single full-width, border-less 4-cell table directly under the header banner.
- Each cell: light fill `#EEF2F8`, a thin navy bottom rule, a 7pt gray uppercase
  LABEL, a 16pt navy bold VALUE, and an optional 8pt delta line.
- Delta line uses green/red text per direction; for rank, a smaller number is
  better (improving rank is green).
- Format premium as compact currency ($12.4M), percentages with a sign and `%`,
  rank as `#N`.

## Tables

- Centered, full page width, header row only on a navy band (`header_fill`) with
  white bold 8.5pt text.
- Body rows alternate white / zebra `#F7F9FD`; text dark 8.8pt; thin light-blue
  bottom rule per cell; comfortable cell margins.
- Delta / change / YoY / growth columns get green/red cell shading via the
  favourable-direction rule. Rank columns are NOT shaded by magnitude.
- Always format by column meaning: premium → currency, share/SoW/appetite → `%`,
  score → 1 decimal, rank → `#N`.

## Section headings

- Each major section opens with a 13pt navy bold title carrying a soft bottom
  rule. Analytical sections may use the `section_accents` colour for the rule.
- A one-line gray caption under the title sets context. Keep it to one sentence.

## Section order & the analytical sections

Render in the order under `section_order`. The three analytical sections are
client-facing and evidence-grounded:

1. **Whitespace Analysis** — slices where the carrier is absent / materially thin
   while the Marsh book (market) participates. Use the exact term *whitespace*.
   Table: slice · carrier premium · market premium · gap. Lead with the largest
   gaps; red accent signals the opportunity cost.
2. **Industry-Level Analysis** — performance by `SIC_Major_Class`. Table: industry
   · premium · YoY · share, with green/red on movement. Call out the strongest
   and weakest industries and any concentration.
3. **Segment Analysis** — performance by `Client_Segment`. Same table shape as
   industry. Highlight where the mix is shifting and where peers out/under-index.

All three render only when the evidence supports them; never fabricate rows.
Aggregate peers — never expose an individual peer/carrier name.
