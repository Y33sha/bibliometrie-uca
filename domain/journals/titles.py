"""Comparaison des titres de revues."""

from domain.normalize import normalize_text


def nested_titles(a: str | None, b: str | None) -> bool:
    """Les mots d'un titre sont tous dans l'autre : « BMJ » et « BMJ British Medical Journal », pas « Physical review C » et « Physical review D »."""
    if not a or not b:
        return False
    words_a, words_b = set(normalize_text(a).split()), set(normalize_text(b).split())
    return bool(words_a and words_b) and (words_a <= words_b or words_b <= words_a)
