---
name: gpr-planner-example
description: One worked example of a grounded GPR analytical plan (structure/altitude reference).
flow: gpr
scope: [planner]
always: true
priority: 30
---

[GPR PLANNER — WORKED EXAMPLE]
Use this only as a structure/altitude reference for the plan. Never reuse its specific
values; ground every table, column, and filter in the provided schema and valid_values,
and inherit missing filters from routing_context (do not invent them).

Example question: "What is Zurich's Share of Wallet in Canada for Property, and how did
premium move YoY?"

Example ideal plan (shape only):
- intent: "Compute Zurich's Share of Wallet in Canada Property and its YoY premium change."
- metric: "Share of Wallet (SoW) + YoY premium growth"
- metric_definition: "SoW = Carrier_Group Premium / Total Market (Marsh) Premium for the
  same Country + Product_Line; YoY = (CurrentYear - PriorYear) / PriorYear * 100."
- steps:
  1. Filter GPR to Country='Canada', Product_Line='Property'.
  2. Sum Premium for Carrier_Group='ZURICH GROUP' per Year.
  3. Sum total market Premium (no carrier filter) per Year for the same Country/Product_Line.
  4. SoW = carrier premium / market premium per Year.
  5. YoY = change in carrier premium between the two most recent years in valid_year_quarter.
- tables: ["GPR"]
- filters: {"Country": "Canada", "Product_Line": "Property", "Carrier_Group": "ZURICH GROUP"}
- group_by: ["Year"]
- timeframe: "two most recent years from valid_year_quarter (e.g. 2023 -> 2024)"
- rules: ["SoW shares the same Country/Product_Line dimension", "Marsh = total market, no carrier filter"]
- notes: "Resolve the exact years from valid_year_quarter; do not hardcode."
