"""Validate translated Home Assistant strings."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


TRANSLATIONS = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "power_sync"
    / "translations"
)
PLACEHOLDER_PATTERN = re.compile(r"\{[^{}]+\}")


def _leaf_values(value: Any, prefix: tuple[str, ...] = ()) -> dict[tuple[str, ...], str]:
    if isinstance(value, dict):
        leaves = {}
        for key, item in value.items():
            leaves.update(_leaf_values(item, (*prefix, key)))
        return leaves
    if isinstance(value, str):
        return {prefix: value}
    return {}


def test_french_translation_matches_english_keys_and_placeholders():
    english = _leaf_values(json.loads((TRANSLATIONS / "en.json").read_text()))
    french = _leaf_values(json.loads((TRANSLATIONS / "fr.json").read_text()))

    assert french.keys() == english.keys()
    mismatches = {
        ".".join(key): {
            "english": PLACEHOLDER_PATTERN.findall(english[key]),
            "french": PLACEHOLDER_PATTERN.findall(french[key]),
        }
        for key in english
        if PLACEHOLDER_PATTERN.findall(french[key])
        != PLACEHOLDER_PATTERN.findall(english[key])
    }
    assert not mismatches
