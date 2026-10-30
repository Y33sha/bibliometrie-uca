"""Formes de nom d'une structure, avec leurs options de matching."""

from dataclasses import dataclass, field

from domain.errors import ValidationError


@dataclass(frozen=True)
class StructureNameForm:
    """Forme de nom d'une structure (table `structure_name_forms`)."""

    form_text: str
    """Texte normalisé à reconnaître dans une adresse."""
    is_word_boundary: bool = False
    """La forme exige une frontière de mot de chaque côté."""
    is_excluding: bool = False
    """La forme reconnue rejette la structure."""
    requires_context_of: tuple[int, ...] = field(default_factory=tuple)
    """Structures dont l'une doit aussi être reconnue dans l'adresse, son propre contexte compris."""

    def __post_init__(self) -> None:
        if not self.form_text or not self.form_text.strip():
            raise ValidationError("StructureNameForm.form_text ne peut pas être vide")

    def __str__(self) -> str:
        return self.form_text


# Longueur maximale, en caractères de texte normalisé, d'une forme courte. Une forme courte exige une frontière de mot (« ica » dans « africa ») ; une contrainte CHECK de `structure_name_forms` l'impose.
SHORT_FORM_MAX_LENGTH = 6


def is_short_form(form_text: str) -> bool:
    """Vrai si une forme de ce texte normalisé doit exiger une frontière de mot."""
    return len(form_text) <= SHORT_FORM_MAX_LENGTH
