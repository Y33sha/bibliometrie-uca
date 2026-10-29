"""Clés de confirmation d'un enregistrement source : les valeurs par lesquelles deux enregistrements sources désignent le même document.

- DOI : tous ses DOI actifs de rôle autre que `related`, chacun remplacé par sa cible quand c'est le DOI d'une forme secondaire (`DoiKeys`).
- Identifiants : l'identifiant actif de rôle le plus fort de chaque type de `CONFIRMATION_ID_TYPES`.
- Bloc de métadonnées : `<type de document>|<titre normalisé>|<année>`, pour un titre assez long. Le type de document dans la clé impose l'égalité des types.

Les valeurs sont celles de l'enregistrement source corrigé (phase `metadata_correction`). Le voisinage SQL de la réconciliation (`_UNIVERSE_SQL`) réécrit ces clés, et `TestUniverseMatchesPythonTokens` vérifie que les deux concordent. Un type d'identifiant de plus demande son entrée dans `CONFIRMATION_ID_TYPES` et un champ de même nom dans `ConfirmationKeys`. Une clé composite demande aussi sa branche dans `_UNIVERSE_SQL`.

Les ancres d'un ensemble d'enregistrements sources (`doi_anchors`) sont les DOI qui le coupent à la réconciliation et qui donnent son DOI à une publication.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields

from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
    active,
    by_role,
)

# Types d'identifiants qui sont des clés de confirmation, à côté du DOI et du bloc de métadonnées.
CONFIRMATION_ID_TYPES = (
    SourceIdentifierType.HAL_ID,
    SourceIdentifierType.ARXIV_ID,
    SourceIdentifierType.PMID,
    SourceIdentifierType.NNT,
)


# Longueur de titre normalisé, en caractères, en deçà de laquelle un titre est trop générique pour apparier deux publications.
# Sert aux clés de confirmation, aux relations et au dédoublonnage HAL ; les requêtes SQL l'interpolent.
DISCRIMINANT_TITLE_MIN_LENGTH = 30

_STRONG_ROLES = frozenset({SourceIdentifierRole.PRIMARY, SourceIdentifierRole.DERIVED})


@dataclass(frozen=True, slots=True)
class DoiKeys:
    """DOI actifs d'un enregistrement source, cible appliquée : `strong`, de rôle `primary` ou `derived` ; `weak`, de rôle `secondary` et absents de `strong`."""

    strong: frozenset[str] = frozenset()
    weak: frozenset[str] = frozenset()

    @property
    def all(self) -> frozenset[str]:
        return self.strong | self.weak


def doi_keys(
    identifiers: Iterable[SourceIdentifier], doi_targets: Mapping[str, str] | None = None
) -> DoiKeys:
    """DOI actifs de `identifiers` de rôle autre que `related`, chacun remplacé par sa cible dans `doi_targets`."""
    targets = doi_targets or {}
    strong: set[str] = set()
    weak: set[str] = set()
    for i in active(identifiers):
        if i.id_type is not SourceIdentifierType.DOI or i.role is SourceIdentifierRole.RELATED:
            continue
        (strong if i.role in _STRONG_ROLES else weak).add(targets.get(i.value, i.value))
    return DoiKeys(frozenset(strong), frozenset(weak - strong))


def doi_anchors(keys: Iterable[DoiKeys]) -> frozenset[str]:
    """Ancres d'un ensemble d'enregistrements sources : leurs DOI `primary` ou `derived` ; à défaut, le DOI de ceux qui ont un seul DOI."""
    keys = list(keys)
    strong = frozenset().union(*(k.strong for k in keys))
    if strong:
        return strong
    return frozenset(next(iter(k.weak)) for k in keys if len(k.weak) == 1)


def anchor_of(keys: DoiKeys, anchors: frozenset[str]) -> str | None:
    """Ancre que rejoint un enregistrement source : celle de son DOI `primary` ou `derived`, à défaut l'unique ancre parmi ses DOI `secondary`. `None` sans ancre unique."""
    own = keys.strong & anchors or keys.weak & anchors
    return next(iter(own)) if len(own) == 1 else None


@dataclass(frozen=True, slots=True)
class ConfirmationKeys:
    """Clés de confirmation d'un enregistrement source ; une clé absente vaut `None`."""

    doi: DoiKeys
    nnt: str | None
    pmid: str | None
    arxiv_id: str | None
    hal_id: str | None
    metadata_block: str | None

    def tokens(self) -> frozenset[tuple[str, str]]:
        """Clés présentes, en jetons `(nom de la clé, valeur)` : un DOI `x` et un NNT `x` restent distincts. Deux enregistrements sources qui partagent un jeton sont reliés dans le graphe des composantes."""
        singles = {
            (name, value)
            for name in _KEY_NAMES
            if name != "doi" and (value := getattr(self, name)) is not None
        }
        return frozenset(singles | {("doi", d) for d in self.doi.all})


_KEY_NAMES = tuple(f.name for f in fields(ConfirmationKeys))
assert set(_KEY_NAMES) == {"doi", "metadata_block", *CONFIRMATION_ID_TYPES}, (
    "champs de ConfirmationKeys désynchronisés de CONFIRMATION_ID_TYPES"
)


def confirmation_identifiers(identifiers: Iterable[SourceIdentifier]) -> dict[str, str | None]:
    """Clé de chaque type de `CONFIRMATION_ID_TYPES` : l'identifiant actif de rôle le plus fort, puis de plus petite valeur (`by_role`). Un type sans identifiant actif vaut `None`."""
    keys: dict[str, str | None] = dict.fromkeys(map(str, CONFIRMATION_ID_TYPES))
    for identifier in by_role(active(identifiers)):
        if keys.get(identifier.id_type.value, "") is None:
            keys[identifier.id_type.value] = identifier.value
    return keys


def project_confirmation_keys(
    identifiers: Iterable[SourceIdentifier],
    doc_type: str | None,
    title_normalized: str | None,
    publication_year: int | None,
    doi_targets: Mapping[str, str] | None = None,
) -> ConfirmationKeys:
    """Clés de confirmation d'un enregistrement source. `identifiers` : ses identifiants, avec leur rôle et leur statut. `doi_targets` : cible du DOI de chaque forme secondaire. Le bloc de métadonnées demande un type de document, une année et un titre normalisé plus long que `DISCRIMINANT_TITLE_MIN_LENGTH`."""
    identifiers = list(identifiers)
    metadata_block = (
        f"{doc_type}|{title_normalized}|{publication_year}"
        if doc_type
        and title_normalized
        and len(title_normalized) > DISCRIMINANT_TITLE_MIN_LENGTH
        and publication_year is not None
        else None
    )
    return ConfirmationKeys(
        doi=doi_keys(identifiers, doi_targets),
        metadata_block=metadata_block,
        **confirmation_identifiers(identifiers),
    )
