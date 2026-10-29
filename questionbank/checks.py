"""Quality checks on generated questions: near-duplicates, copied samples, and an AI review of syllabus fit and
answers. Checks only flag problems for a person to look at; they never change the questions."""

import re
from difflib import SequenceMatcher

# Two questions at least this similar (0–1, after normalising) count as duplicates.
SIMILARITY = 0.85


def normalize(text):
    """Lower-case, punctuation and extra spaces removed; works for Bangla as well as English."""
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


def similar(a, b):
    """Similarity of two normalised texts, from 0 to 1."""
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    if matcher.real_quick_ratio() < SIMILARITY or matcher.quick_ratio() < SIMILARITY:
        return 0.0
    return matcher.ratio()


def find_similar(text, candidates):
    """The first (key, normalised text) candidate that duplicates text, or None."""
    norm = normalize(text)
    for key, other in candidates:
        if norm and similar(norm, other) >= SIMILARITY:
            return key
    return None
