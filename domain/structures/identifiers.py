"""Value objects et helpers de normalisation des identifiants structure.

`RorId` (Research Organization Registry), `HalCollection` (code collection HAL) : deux VOs immuables et auto-validés, au même contrat que `domain/persons/identifiers.py` et `domain/publications/identifiers.py` :

- `X("...")` strict : lève `ValidationError` si malformé
- `X.try_parse(...)` tolérant : renvoie None si malformé

Les helpers `normalize_*` sont exposés indépendamment pour les call sites qui veulent juste normaliser sans construire un VO.
"""

import re
from dataclasses import dataclass

from domain.errors import ValidationError

# ── RorId (Research Organization Registry) ─────────────────────────
#
# Forme canonique : 9 caractères [0-9a-hjkmnp-z] (alphabet ROR : pas de
# i, l, o, u — réduit les ambiguïtés visuelles). L'URL
# `https://ror.org/<9-char>` reste possible à l'affichage ;
# côté stockage et VO on garde la forme courte, même principe qu'ORCID.

_ROR_URL_PREFIXES = (
    "https://ror.org/",
    "http://ror.org/",
    "ror.org/",
)
_ROR_CANONICAL = re.compile(r"^0[0-9a-hjkmnp-z]{8}$")


def normalize_ror_id(raw: str | None) -> str | None:
    """Normalise un RorId : strip URL préfixe, lowercase, validation alphabet ROR.

    Accepte une URL `https://ror.org/<id>` ou l'id 9-char nu. Renvoie None si la forme finale n'est pas valide.
    """
    if not raw:
        return None
    s = raw.strip().lower()
    for prefix in _ROR_URL_PREFIXES:
        if s.startswith(prefix):
            s = s[len(prefix) :]
            break
    s = s.strip()
    if not _ROR_CANONICAL.match(s):
        return None
    return s


@dataclass(frozen=True)
class RorId:
    """Identifiant Research Organization Registry, forme canonique 9-char.

    Format ROR : `0` + 8 caractères de l'alphabet ROR (chiffres + lettres sans i/l/o/u). Stocké et comparé en forme courte ; l'URL complète `https://ror.org/<id>` est une décoration d'affichage uniquement.
    """

    value: str

    def __post_init__(self) -> None:
        cleaned = normalize_ror_id(self.value)
        if not cleaned:
            raise ValidationError(f"RorId invalide : {self.value!r}")
        object.__setattr__(self, "value", cleaned)

    @classmethod
    def try_parse(cls, raw: str | None) -> "RorId | None":
        if not raw:
            return None
        try:
            return cls(raw)
        except ValidationError:
            return None

    def __str__(self) -> str:
        return self.value


# ── HalCollection (code de collection HAL) ─────────────────────────
#
# Une collection HAL est désignée par un code court (ex. `LIMOS`,
# `INSTITUT_PASCAL`, `LPC-CLERMONT`). Pas de format strictement
# imposé par HAL — on observe lettres ASCII majuscules, chiffres,
# underscore, tiret. On normalise en majuscules + trim, on valide le
# vocabulaire admis pour rejeter les saisies absurdes (espaces internes,
# caractères accentués, …).

_HAL_COLLECTION_CANONICAL = re.compile(r"^[A-Z0-9][A-Z0-9_-]*$")


def normalize_hal_collection(raw: str | None) -> str | None:
    """Normalise un code de collection HAL : trim + uppercase, valide qu'il ne contient que [A-Z0-9_-] et commence par une lettre/chiffre."""
    if not raw:
        return None
    s = raw.strip().upper()
    if not _HAL_COLLECTION_CANONICAL.match(s):
        return None
    return s


@dataclass(frozen=True)
class HalCollection:
    """Code de collection HAL (ex. `LIMOS`, `INSTITUT_PASCAL`).

    Normalisé en majuscules. Le format admis est `[A-Z0-9][A-Z0-9_-]*` — observation empirique sur le corpus, pas de spec HAL formelle.
    """

    value: str

    def __post_init__(self) -> None:
        cleaned = normalize_hal_collection(self.value)
        if not cleaned:
            raise ValidationError(f"HalCollection invalide : {self.value!r}")
        object.__setattr__(self, "value", cleaned)

    @classmethod
    def try_parse(cls, raw: str | None) -> "HalCollection | None":
        if not raw:
            return None
        try:
            return cls(raw)
        except ValidationError:
            return None

    def __str__(self) -> str:
        return self.value
