# Pitch Evidence Summarization Design

## Goal

Keep full SQL evidence available for traceability while sending only compact,
high-signal summaries to LLM report-writing nodes.

## Evidence Object

```json
{
  "id": "q3.gpr.1",
  "question": "How is premium moving by product?",
  "flow": "gpr",
  "sql": "SELECT ...",
  "row_count": 12,
  "columns": ["Product_Line", "carrier_premium", "yoy"],
  "summary_rows": [
    {"Product_Line": "Property", "carrier_premium": "$12.4M", "yoy": "8.1%"}
  ],
  "full_rows_ref": "state.pitch_question_results[3].pitch_query_result"
}
```

## Summarization Rules

- Preserve exact numbers and labels.
- Keep top and bottom slices when ranking or movement matters.
- Keep carrier, peer, and Marsh rows clearly labeled.
- Never summarize peer rows with individual names.
- Include row count and omitted-row count.

## Prompt Budget

- Extractor prompt: max 8,000 characters per question result.
- Narrative arc prompt: max 15,000 characters total.
- Report writer prompt: max 20,000 characters total.
- If over budget, summarize each evidence group before writing.

