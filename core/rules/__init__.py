"""Static prompt rules for each SQL flow.

Phase 1: Python string constants on rule classes (unchanged behavior).
Phase 2 target: replace with Claude-style `skill.md` files under
`core/skills/`, loaded progressively by a registry based on router output.
Do NOT add new rules here — add them as `.md` skills from the start.
"""
