"""Approved colour themes for Boardroom widgets.

Edits may only recolour a widget from this governed set (per the spec: "Colors
from an approved theme"), so we never end up with off-brand ad-hoc hex values.
Each theme maps to an accent + a soft background used by the widget chrome.
"""
from __future__ import annotations

from typing import Dict

THEMES: Dict[str, Dict[str, str]] = {
    "default": {"label": "Default", "accent": "#0b4bff", "soft": "#eef3fa", "ink": "#0b1320"},
    "navy": {"label": "Navy", "accent": "#000f47", "soft": "#e7ebf5", "ink": "#0b1320"},
    "teal": {"label": "Teal", "accent": "#00a6a6", "soft": "#e2f5f5", "ink": "#06403f"},
    "green": {"label": "Positive", "accent": "#1f9d55", "soft": "#e6f5ec", "ink": "#0c3f23"},
    "amber": {"label": "Caution", "accent": "#b9810a", "soft": "#fbf1da", "ink": "#5a3d05"},
    "red": {"label": "Adverse", "accent": "#c53532", "soft": "#fae9e8", "ink": "#5a1614"},
    "slate": {"label": "Neutral", "accent": "#5b6577", "soft": "#eef1f5", "ink": "#23303f"},
}

DEFAULT_THEME = "default"


def theme(key: str | None) -> Dict[str, str]:
    return THEMES.get(key or DEFAULT_THEME, THEMES[DEFAULT_THEME])


def theme_options():
    """For dropdowns: [{'label','value'}]."""
    return [{"label": v["label"], "value": k} for k, v in THEMES.items()]
