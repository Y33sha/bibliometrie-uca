"""Base des identifiants : une valeur ramenée à sa forme canonique et validée à la construction."""

from dataclasses import dataclass
from typing import ClassVar, Self

from domain.errors import ValidationError


@dataclass(frozen=True)
class NormalizedIdentifier:
    """Identifiant dont `value` est la forme canonique que rend `normalize`. Une valeur sans forme canonique lève `ValidationError` ; `try_parse` rend alors `None`.

    Une sous-classe donne `label`, le nom de l'identifiant dans les messages d'erreur, et `normalize`.
    """

    value: str
    label: ClassVar[str]

    @staticmethod
    def normalize(raw: str | None) -> str | None:
        """Forme canonique de `raw`, ou `None`."""
        raise NotImplementedError

    def __post_init__(self) -> None:
        cleaned = type(self).normalize(self.value)
        if not cleaned:
            raise ValidationError(f"{self.label} invalide : {self.value!r}")
        object.__setattr__(self, "value", cleaned)

    @classmethod
    def try_parse(cls, raw: str | None) -> Self | None:
        """L'identifiant, ou `None` si `raw` est vide ou sans forme canonique."""
        if not raw:
            return None
        try:
            return cls(raw)
        except ValidationError:
            return None

    def __str__(self) -> str:
        return self.value
