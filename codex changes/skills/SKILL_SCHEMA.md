# Proposed Rich Skill Schema

## Purpose

The current skill loader proves that progressive rule loading works. The next
step is making skills self-describing, composable, testable, and observable.

## Frontmatter

```yaml
---
name: gpr-share-of-wallet
description: Share of Wallet definition, SQL shape, response rules, and tests.
flow: gpr
scope: [planner, sql, response, pitch]
kind: metric
priority: 90
risk_level: high

triggers:
  - sow
  - share of wallet
  - wallet share
  - share in marsh book

negative_triggers:
  - employee wallet
  - wallet size

requires:
  - gpr-marsh-market
  - cross-sql-readonly-safety

conflicts_with:
  - survey-score-only

tables:
  - GPR

supporting_tables:
  - Peers

columns:
  - Premium
  - Carrier_Group
  - Country
  - Product_Line
  - Year

metrics:
  - share_of_wallet
  - premium

examples:
  - user_query: What is Zurich share of wallet in Canada by product?
    expected_plan:
      metric: share_of_wallet
      group_by: [Product_Line]
      filters: {Carrier_Group: ZURICH GROUP, Country: Canada}
    expected_sql_shape: carrier premium divided by Marsh total premium for same slice

test_queries:
  positive:
    - Zurich SoW in Canada
    - share in Marsh book by product
  negative:
    - Zurich survey score in Canada
---
```

## Body Sections

Use the same section headings across skills:

```markdown
## Definition
## When To Use
## Required Evidence
## Expected Plan Shape
## Expected SQL Shape
## Response Rules
## Forbidden Mistakes
## Test Queries
```

## Loader Behavior Additions

Recommended future loader features:

- Match `negative_triggers` after positive triggers and suppress false positives.
- Load `requires` dependencies automatically.
- Detect `conflicts_with` and log warnings.
- Emit diagnostic records: matched skill, trigger hit, dependency loaded, skipped reason.
- Validate required frontmatter in CI.
- Generate a coverage report by flow/scope/metric.

## Compatibility

The first migration can keep current loader behavior and ignore unknown fields.
That lets richer skills land before runtime code changes.

