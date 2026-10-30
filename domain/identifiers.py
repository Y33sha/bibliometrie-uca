"""Classe de base des identifiants normalisés."""

from dataclasses import dataclass
from typing import ClassVar, Self

from domain.errors import ValidationError


@dataclass(frozen=True)
class NormalizedIdentifier:
    """Identifiant validé et ramené à sa forme normalisée dès sa construction. Une valeur invalide lève `ValidationError`."""

    value: str
    label: ClassVar[str]
    """Nom de l'identifiant affiché dans les messages d'erreur."""

    @staticmethod
    def normalize(raw: str | None) -> str | None:
        """Renvoie la forme normalisée de `raw`, ou `None` si `raw` est invalide."""
        raise NotImplementedError

    def __post_init__(self) -> None:
        cleaned = type(self).normalize(self.value)
        if not cleaned:
            raise ValidationError(f"{self.label} invalide : {self.value!r}")
        object.__setattr__(self, "value", cleaned)

    @classmethod
    def try_parse(cls, raw: str | None) -> Self | None:
        """Construit l'identifiant, ou renvoie `None` si `raw` est vide ou invalide."""
        if not raw:
            return None
        try:
            return cls(raw)
        except ValidationError:
            return None

    def __str__(self) -> str:
        return self.value
