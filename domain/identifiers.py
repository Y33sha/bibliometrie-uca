"""Identifiants normalisés : classe de base, IdRef."""

import re
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


_IDREF_URL_RE = re.compile(r"idref\.fr/(\d{8}[\dX])(?:/id)?", re.IGNORECASE)
# PPN : 8 chiffres + 1 caractère de contrôle (chiffre ou X)
_IDREF_CANONICAL = re.compile(r"^\d{8}[\dX]$")


def _normalize_idref(raw: str | None) -> str | None:
    """Renvoie la forme normalisée d'un IdRef, écrit seul ou dans une URL idref.fr ; `None` si le format est invalide."""
    if not raw:
        return None
    s = "".join(raw.split())
    m = _IDREF_URL_RE.search(s)
    if m:
        s = m.group(1)
    s = s.upper()
    if not _IDREF_CANONICAL.match(s):
        return None
    return s


class IdRef(NormalizedIdentifier):
    """IdRef (PPN du Sudoc) : 8 chiffres et une clé de contrôle. Il identifie une personne, une collectivité ou une vedette RAMEAU."""

    label = "IdRef"
    normalize = staticmethod(_normalize_idref)
