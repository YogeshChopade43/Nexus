"""Approximate token counting: about 4 characters per token for English text."""
from __future__ import annotations

CHARS_PER_TOKEN = 4


def count_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)
