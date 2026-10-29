"""Clés de confirmation d'un enregistrement source : les valeurs par lesquelles deux enregistrements sources désignent le même document.

- Identifiants : le DOI, et l'identifiant actif de rôle le plus fort de chaque type de `CONFIRMATION_ID_TYPES`.
- Bloc de métadonnées : `<type de document>|<titre normalisé>|<année>`, pour un titre assez long. Le type de document dans la clé impose l'égalité des types.

Les valeurs sont celles de l'enregistrement source corrigé (phase `metadata_correction`). Le voisinage SQL de la réconciliation (`_UNIVERSE_SQL`) réécrit ces clés, et `TestUniverseMatchesPythonTokens` vérifie que les deux concordent. Un type d'identifiant de plus demande son entrée dans `CONFIRMATION_ID_TYPES` et un champ de même nom dans `ConfirmationKeys`. Une clé composite demande aussi sa branche dans `_UNIVERSE_SQL`.
"""

from collections.abc import Iterable
from dataclasses import dataclass, fields

from domain.publications.identifiers import DOI
from domain.source_records.identifiers import (
    SourceIdentifier,
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


@dataclass(frozen=True, slots=True)
class ConfirmationKeys:
    """Clés de confirmation d'un enregistrement source ; une clé absente vaut `None`."""

    doi: str | None
    nnt: str | None
    pmid: str | None
    arxiv_id: str | None
    hal_id: str | None
    metadata_block: str | None

    def tokens(self) -> frozenset[tuple[str, str]]:
        """Clés présentes, en jetons `(nom de la clé, valeur)` : un DOI `x` et un NNT `x` restent distincts. Deux enregistrements sources qui partagent un jeton sont reliés dans le graphe des composantes."""
        return frozenset(
            (name, value) for name in _KEY_NAMES if (value := getattr(self, name)) is not None
        )


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
    doi: str | None,
    identifiers: Iterable[SourceIdentifier],
    doc_type: str | None,
    title_normalized: str | None,
    publication_year: int | None,
) -> ConfirmationKeys:
    """Clés de confirmation d'un enregistrement source. `identifiers` : ses identifiants, avec leur rôle et leur statut. Le bloc de métadonnées demande un type de document, une année et un titre normalisé plus long que `DISCRIMINANT_TITLE_MIN_LENGTH`."""
    doi_vo = DOI.try_parse(doi) if isinstance(doi, str) else None
    metadata_block = (
        f"{doc_type}|{title_normalized}|{publication_year}"
        if doc_type
        and title_normalized
        and len(title_normalized) > DISCRIMINANT_TITLE_MIN_LENGTH
        and publication_year is not None
        else None
    )
    return ConfirmationKeys(
        doi=str(doi_vo) if doi_vo else None,
        metadata_block=metadata_block,
        **confirmation_identifiers(identifiers),
    )
