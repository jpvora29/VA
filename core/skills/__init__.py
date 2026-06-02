"""Skill files (skill.md) loaded progressively by the planner/SQL/response/chart nodes.

Public surface:
- `SkillLoader` — parses every `*.md` here and serves matching skills by flow + scope + query.
- `get_skill_loader()` — process-wide singleton (skills are parsed once, served many times).
"""
from core.skills.loader import Skill, SkillLoader, get_skill_loader

__all__ = ["Skill", "SkillLoader", "get_skill_loader"]

