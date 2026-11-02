"""Formes de nom courtes d'une structure."""

# Longueur maximale, en caractères de texte normalisé, d'une forme courte. Une forme courte exige une frontière de mot (« ica » dans « africa ») ; une contrainte CHECK de `structure_name_forms` l'impose.
SHORT_FORM_MAX_LENGTH = 6


def is_short_form(form_text: str) -> bool:
    """Vrai si une forme de ce texte normalisé doit exiger une frontière de mot."""
    return len(form_text) <= SHORT_FORM_MAX_LENGTH
