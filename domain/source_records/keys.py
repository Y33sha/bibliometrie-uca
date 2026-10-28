"""Projection d'une `source_record` vers son jeu de clés de confirmation.

Une *clé de confirmation* est un attribut cross-source par lequel deux `source_records` attestent du même document. Deux familles :

- **Identifiants** : DOI de la colonne `doi`, et identifiants de `source_record_identifiers` de rôle admis (`CONFIRMATION_KEY_ROLES`) — égalité directe. Un `hal_id` est une clé quand il est primaire (enregistrement source HAL) ou dérivé (dépôt dont un enregistrement source ScanR ou OpenAlex est tiré).
- **Token métadonnée** : `("metadata_block", "<doc_type>|<title_normalized>|<publication_year>")`, pour **tout** `doc_type` (empiriquement ~99 % de même-œuvre par type au-delà du seuil de longueur de titre). Le `doc_type` dans la clé impose l'égalité de type (« un DOI, une œuvre » étendu au type). Garde de **longueur minimale de titre** : écarte les collisions de titres génériques. La thèse passe par ce même token (`thesis|<titre>|<année>`) ; `thesis` et `ongoing_thesis` ne co-bloquent jamais (leurs années diffèrent — inscription vs soutenance). Les paliers plus lâches (hors `doc_type`, titres courts via le conteneur), qui exigeraient un second accord pairwise, relèvent d'un mécanisme distinct.

La projection est la définition Python des clés de confirmation. La réconciliation des publications (`pipeline/transformation/publications/reconciliation.py`) la consomme. Son voisinage SQL (`_UNIVERSE_SQL`) réécrit ces clés ; `TestUniverseMatchesPythonTokens` vérifie que les deux concordent. `run_pipeline --only publications --rebuild-publications` applique une règle de clé au stock.

Les valeurs sont lues sur la `source_record` **corrigée** : DOI de la colonne (concept Zenodo déjà substitué par `metadata_correction`), identifiants actifs.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from domain.publications.identifiers import DOI
from domain.source_records.external_ids import MULTIVALUED_ID_TYPES, ExternalIdType
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)

# Types d'`external_ids` par lesquels deux `source_records` désignent le même document. Le DOI (colonne dédiée) et le token métadonnée sont les autres familles de clés de confirmation.
CONFIRMATION_ID_TYPES = (
    ExternalIdType.HAL_ID,
    ExternalIdType.ARXIV_ID,
    ExternalIdType.PMID,
    ExternalIdType.NNT,
)
# Clés de confirmation stockées en valeur unique dans `external_ids`, comparées par égalité directe. `hal_id` y est une liste.
SCALAR_CONFIRMATION_ID_TYPES = tuple(
    t for t in CONFIRMATION_ID_TYPES if t not in MULTIVALUED_ID_TYPES
)

_SAME_DOCUMENT = frozenset(
    {SourceIdentifierRole.PRIMARY, SourceIdentifierRole.DERIVED, SourceIdentifierRole.SECONDARY}
)
CONFIRMATION_KEY_ROLES: dict[SourceIdentifierType, frozenset[SourceIdentifierRole]] = {
    SourceIdentifierType.HAL_ID: frozenset(
        {SourceIdentifierRole.PRIMARY, SourceIdentifierRole.DERIVED}
    ),
    SourceIdentifierType.ARXIV_ID: _SAME_DOCUMENT,
    SourceIdentifierType.PMID: _SAME_DOCUMENT,
    SourceIdentifierType.NNT: _SAME_DOCUMENT,
}
"""Rôles d'un identifiant actif qui en font une clé de confirmation, par type. Un `hal_id` secondaire désigne souvent une autre version du document : une communication et son article, un poster et son acte."""


def is_confirmation_key(identifier: SourceIdentifier) -> bool:
    """Indique si l'identifiant est une clé de confirmation : actif, et d'un rôle de `CONFIRMATION_KEY_ROLES` pour son type."""
    return identifier.removed_by is None and identifier.role in CONFIRMATION_KEY_ROLES.get(
        identifier.id_type, frozenset()
    )


# Seuil de longueur de `title_normalized` (caractères, strict) en-deçà duquel un titre est trop
# générique pour rapprocher deux publications : token `metadata_block` (matching de clés), univers
# de réconciliation, appariement par titre (relations, dédup HAL). Les requêtes SQL l'interpolent.
DISCRIMINANT_TITLE_MIN_LENGTH = 30


@dataclass(frozen=True, slots=True)
class ConfirmationKeys:
    """Clés de confirmation d'une `source_record`, normalisées.

    `identifiers` : couples `(type, valeur)` des identifiants qui sont des clés (`is_confirmation_key`). `metadata_block` = `"<doc_type>|<title_normalized>|<publication_year>"` pour toute `source_record` à `doc_type` présent et titre assez long. Une clé absente vaut `None`.
    """

    doi: str | None
    metadata_block: str | None
    identifiers: frozenset[tuple[str, str]] = frozenset()

    def tokens(self) -> frozenset[tuple[str, str]]:
        """Jeu de tokens `(nom de la clé, valeur)` de la `source_record`, pour le clustering.

        Chaque token est namespacé par son type : un DOI `x` et un NNT `x` ne s'apparentent pas. Deux `source_records` partageant un token sont reliées dans le graphe de composantes (cf. `connected_components`). Une clé absente ne produit pas de token.
        """
        named = (("doi", self.doi), ("metadata_block", self.metadata_block))
        return self.identifiers | {(name, value) for name, value in named if value is not None}


def project_confirmation_keys(
    doi: str | None,
    identifiers: Iterable[SourceIdentifier],
    doc_type: str | None,
    title_normalized: str | None,
    publication_year: int | None,
) -> ConfirmationKeys:
    """Extrait les clés de confirmation normalisées d'une `source_record`.

    Le DOI est lu sur la colonne (déjà corrigée, concept Zenodo inclus). `identifiers` sont les identifiants de l'enregistrement source, déjà normalisés. `metadata_block` est posée pour toute `source_record` à `doc_type` présent, `publication_year` présent et `title_normalized` plus long que `DISCRIMINANT_TITLE_MIN_LENGTH`.
    """
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
        identifiers=frozenset(
            (i.id_type.value, i.value) for i in identifiers if is_confirmation_key(i)
        ),
    )
