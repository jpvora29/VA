# Skills (Phase 2 target)

This directory will hold Claude-style `skill.md` files with YAML frontmatter:

```markdown
---
name: peer-analysis
description: Rules for queries involving peer averages and peer scoring.
triggers: [peer, peer average, peer score]
flow: survey
---

(rule body)
```

A skill registry will load only the skills whose triggers match the routed
query, replacing the bulk `SurveyRules` / `GPRRules` / `GIMMIRules` strings
currently in `core/rules/`.

Status: **empty in Phase 1** — populated in Phase 2.
