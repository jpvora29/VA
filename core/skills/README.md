# Skills

Claude-style skill files with YAML frontmatter, loaded progressively by the
planner / SQL / response / chart nodes. The loader (`loader.py`) injects only the
skills whose triggers match the routed query, replacing the bulk `SurveyRules` /
`GPRRules` / `GIMMIRules` strings in `core/rules/`.

## Layout

```
catalog/
  <flow>/                 # gpr | survey | gimmi | cross | chart
    <name>.skill.md       # one skill per file, discovered recursively
    refs/<file>.md        # shared section bodies pulled in via {{ref}} (optional)
```

Discovery is `rglob("*.skill.md")` under `catalog/`; `refs/` files are never
loaded as standalone skills. Every skill must carry `name`, `flow`, and `scope`.

## Frontmatter

```markdown
---
name: gpr-share-of-wallet
description: Share of Wallet definition, SQL shape, and response wording.
flow: gpr                       # gpr | survey | gimmi | cross
scope: [planner, sql, response] # planner | sql | response | chart | pitch
kind: metric
priority: 85
risk_level: high
triggers: [sow, share of wallet, wallet share]
negative_triggers: [wallet size]
requires: [gpr-marsh-market, cross-sql-readonly-safety]
conflicts_with: []
tables: [GPR]
columns: [Premium, Carrier_Group, Country, Year]
metrics: [share_of_wallet, premium]
---

(rule body — markdown, injected verbatim)
```

## Section references

A skill body can externalise a shared section into a sibling `refs/<file>.md`
and pull it back inline with a directive on its own line:

```markdown
{{ref: refs/gpr-sow-definition.md#definition}}
```

The directive is replaced by the body of the matching heading section. Paths are
resolved relative to the skill's own folder and guarded against escaping the
catalog root.

## Two-phase charts

`chart/` keeps only the always-on `chart-type-selection` (decision tree) and
`chart-field-mapping` skills. The six per-type guides live in
`chart/refs/chart-*.md` and are fetched on demand by `SkillLoader.chart_detail`:
the chart node first picks `chart_type` from the selection tree, then injects ONLY
that type's detail for the spec pass (`core/agents/common/chart_spec.py`).

## Inspect

```powershell
python -m core.skills.inspect --flow gpr --scope sql --query "Zurich SoW by product"
python -m core.skills.inspect --flow survey --scope planner --list
python -m core.skills.inspect --validate
python -m core.skills.inspect --body gpr-share-of-wallet
```
