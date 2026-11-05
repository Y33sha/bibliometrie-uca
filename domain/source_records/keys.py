"""Clés de confirmation d'un enregistrement source : les valeurs par lesquelles deux enregistrements sources désignent le même document.

- DOI : tous ses DOI actifs de rôle autre que `related`, chacun remplacé par sa cible quand c'est le DOI d'une forme secondaire (`DoiKeys`).
- Identifiants : l'identifiant actif de rôle le plus fort de chaque type de `CONFIRMATION_ID_TYPES`.
- Identifiants à plusieurs valeurs : tous les identifiants actifs de rôle autre que `related` des types de `MULTI_VALUED_CONFIRMATION_ID_TYPES`.
- Bloc de métadonnées : `<type de document>|<titre normalisé>|<année>`, pour un titre assez long. Le type de document dans la clé impose l'égalité des types.

Les valeurs sont celles de l'enregistrement source corrigé (phase `metadata_correction`). Le voisinage SQL de la réconciliation (`_UNIVERSE_SQL`) réécrit ces clés, et `TestUniverseMatchesPythonTokens` vérifie que les deux concordent. Un type d'identifiant de plus demande son entrée dans `CONFIRMATION_ID_TYPES`. Une clé composite demande aussi sa branche dans `_UNIVERSE_SQL`.

Les ancres d'un ensemble d'enregistrements sources (`doi_anchors`) sont les DOI qui le coupent à la réconciliation et qui donnent son DOI à une publication. Un DOI de dépôt (`is_deposit_doi`) est seulement le DOI d'une publication sans ancre (`deposit_anchors`) : un preprint ou une copie rejoint ainsi la publication de sa version publiée.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from domain.platforms.registry import is_deposit_doi
from domain.source_records.identifiers import (
    STRONG_ROLES,
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
    active,
    by_role,
)

CONFIRMATION_ID_TYPES = (
    SourceIdentifierType.HAL_ID,
    SourceIdentifierType.PMID,
    SourceIdentifierType.NNT,
)
"""Types d'identifiants dont l'identifiant de rôle le plus fort est une clé de confirmation, à côté du DOI et du bloc de métadonnées."""

MULTI_VALUED_CONFIRMATION_ID_TYPES = (
    SourceIdentifierType.PATENT_PUBLICATION_NUMBER,
    SourceIdentifierType.PATENT_APPLICATION_NUMBER,
)
"""Types d'identifiants dont chaque valeur est une clé de confirmation. Une famille de brevets a un numéro de demande et un numéro de publication par office. Chaque type a ses jetons : un numéro de demande WO égal au numéro de publication d'une autre famille relie rien."""


def is_multi_valued_key(identifier: SourceIdentifier) -> bool:
    """Indique si l'identifiant est une clé de `MULTI_VALUED_CONFIRMATION_ID_TYPES` : actif, de rôle autre que `related`."""
    return (
        identifier.id_type in MULTI_VALUED_CONFIRMATION_ID_TYPES
        and identifier.removed_by is None
        and identifier.role is not SourceIdentifierRole.RELATED
    )


DISCRIMINANT_TITLE_MIN_LENGTH = 30
"""Longueur de titre normalisé, en caractères, en deçà de laquelle un titre est trop générique pour servir de clé. Sert aux clés de confirmation, aux relations et au dédoublonnage HAL ; les requêtes SQL l'interpolent."""


@dataclass(frozen=True, slots=True)
class DoiKeys:
    """DOI actifs d'un enregistrement source, cible appliquée."""

    strong: frozenset[str] = frozenset()
    """DOI de rôle `primary` ou `derived`."""
    weak: frozenset[str] = frozenset()
    """DOI de rôle `secondary`, absents de `strong`."""
    doc_type: str | None = None
    """Type de document de l'enregistrement source : il décide des DOI de dépôt d'une plateforme comme Zenodo."""

    @property
    def all(self) -> frozenset[str]:
        return self.strong | self.weak

    @property
    def deposits(self) -> frozenset[str]:
        """DOI de dépôt (`is_deposit_doi`), qui ne coupent pas la réconciliation."""
        return frozenset(d for d in self.all if is_deposit_doi(d, self.doc_type))


def doi_keys(
    identifiers: Iterable[SourceIdentifier],
    doi_targets: Mapping[str, str] | None = None,
    doc_type: str | None = None,
) -> DoiKeys:
    """Renvoie les DOI actifs de `identifiers` de rôle autre que `related`, chacun ramené à sa cible dans `doi_targets`.

    Args:
        doc_type: type de document de l'enregistrement source.
    """
    targets = doi_targets or {}
    strong: set[str] = set()
    weak: set[str] = set()
    for i in active(identifiers):
        if i.id_type is not SourceIdentifierType.DOI or i.role is SourceIdentifierRole.RELATED:
            continue
        (strong if i.role in STRONG_ROLES else weak).add(targets.get(i.value, i.value))
    return DoiKeys(frozenset(strong), frozenset(weak - strong), doc_type)


def _anchors(keys: Iterable[DoiKeys], *, deposits: bool) -> frozenset[str]:
    """Renvoie les DOI `primary` ou `derived` des enregistrements sources, à défaut le DOI de ceux qui ont un seul DOI, parmi les DOI de dépôt ou parmi les autres."""
    kept = []
    for k in keys:
        own_deposits = k.deposits
        kept.append(
            DoiKeys(
                frozenset(d for d in k.strong if (d in own_deposits) is deposits),
                frozenset(d for d in k.weak if (d in own_deposits) is deposits),
            )
        )
    strong = frozenset().union(*(k.strong for k in kept))
    if strong:
        return strong
    return frozenset(next(iter(k.weak)) for k in kept if len(k.weak) == 1)


def doi_anchors(keys: Iterable[DoiKeys]) -> frozenset[str]:
    """Renvoie les ancres d'un ensemble d'enregistrements sources, hors DOI de dépôt : leurs DOI `primary` ou `derived` ; à défaut, le DOI de ceux qui ont un seul DOI."""
    return _anchors(keys, deposits=False)


def deposit_anchors(keys: Iterable[DoiKeys]) -> frozenset[str]:
    """Renvoie les DOI de dépôt d'un ensemble d'enregistrements sources, choisis comme les ancres (`doi_anchors`). Ils donnent son DOI à une publication sans ancre."""
    return _anchors(keys, deposits=True)


def anchor_of(keys: DoiKeys, anchors: frozenset[str]) -> str | None:
    """Renvoie l'ancre rejointe par un enregistrement source : celle de son DOI `primary` ou `derived`, à défaut l'unique ancre parmi ses DOI `secondary`. `None` sans ancre unique. Ses DOI de dépôt sont écartés, comme dans `doi_anchors`."""
    candidates = anchors - keys.deposits
    own = keys.strong & candidates or keys.weak & candidates
    return next(iter(own)) if len(own) == 1 else None


@dataclass(frozen=True, slots=True)
class Derivation:
    """Identifiants qui relient un enregistrement source dérivé à son parent, l'enregistrement source dont l'identifiant primaire est son identifiant dérivé."""

    primary: tuple[str, str] | None = None
    """Identifiant actif de rôle `primary`, en couple (type, valeur)."""
    derived: tuple[str, str] | None = None
    """Identifiant actif de rôle `derived`, en couple (type, valeur)."""


def derivation(identifiers: Iterable[SourceIdentifier]) -> Derivation:
    """Renvoie l'identifiant primaire et l'identifiant dérivé actifs de `identifiers`."""
    kept = active(identifiers)

    def first(role: SourceIdentifierRole) -> tuple[str, str] | None:
        return next(((i.id_type.value, i.value) for i in kept if i.role is role), None)

    return Derivation(
        primary=first(SourceIdentifierRole.PRIMARY), derived=first(SourceIdentifierRole.DERIVED)
    )


@dataclass(frozen=True, slots=True)
class ConfirmationKeys:
    """Clés de confirmation d'un enregistrement source."""

    doi: DoiKeys
    single_valued: Mapping[str, str]
    """Clés présentes à une seule valeur, par nom de clé : identifiants de `CONFIRMATION_ID_TYPES` et bloc de métadonnées (`metadata_block`)."""
    multi_valued: frozenset[tuple[str, str]] = frozenset()
    """Identifiants de `MULTI_VALUED_CONFIRMATION_ID_TYPES`, en couples (type, valeur)."""

    def tokens(self) -> frozenset[tuple[str, str]]:
        """Renvoie les clés présentes, en jetons `(nom de la clé, valeur)` : un DOI `x` et un NNT `x` restent distincts. Deux enregistrements sources qui partagent un jeton sont reliés dans le graphe des composantes."""
        return frozenset(
            {*self.single_valued.items(), *self.multi_valued, *(("doi", d) for d in self.doi.all)}
        )


def confirmation_identifiers(identifiers: Iterable[SourceIdentifier]) -> dict[str, str]:
    """Renvoie la clé de chaque type de `CONFIRMATION_ID_TYPES` présent : l'identifiant actif de rôle le plus fort, puis de plus petite valeur (`by_role`)."""
    keys: dict[str, str] = {}
    for identifier in by_role(active(identifiers)):
        if identifier.id_type in CONFIRMATION_ID_TYPES:
            keys.setdefault(identifier.id_type.value, identifier.value)
    return keys


def project_confirmation_keys(
    identifiers: Iterable[SourceIdentifier],
    doc_type: str | None,
    title_normalized: str | None,
    publication_year: int | None,
    doi_targets: Mapping[str, str] | None = None,
) -> ConfirmationKeys:
    """Calcule les clés de confirmation d'un enregistrement source. Le bloc de métadonnées demande un type de document, une année et un titre normalisé plus long que `DISCRIMINANT_TITLE_MIN_LENGTH`.

    Args:
        identifiers: identifiants de l'enregistrement source, avec leur rôle et leur statut.
        doi_targets: cible du DOI de chaque forme secondaire.
    """
    identifiers = list(identifiers)
    single_valued = confirmation_identifiers(identifiers)
    if (
        doc_type
        and title_normalized
        and len(title_normalized) > DISCRIMINANT_TITLE_MIN_LENGTH
        and publication_year is not None
    ):
        single_valued["metadata_block"] = f"{doc_type}|{title_normalized}|{publication_year}"
    multi_valued = frozenset(
        (i.id_type.value, i.value) for i in identifiers if is_multi_valued_key(i)
    )
    return ConfirmationKeys(
        doi_keys(identifiers, doi_targets, doc_type), single_valued, multi_valued
    )
