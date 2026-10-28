"""Projection d'une `source_record` vers son jeu de clés de confirmation.

Une *clé de confirmation* est un attribut cross-source par lequel deux `source_records` attestent du même document. Deux familles :

- **Identifiants** : DOI, NNT, HAL ID, PMID, arXiv ID — égalité directe. Un enregistrement source qui liste plusieurs identifiants HAL a pour clé le premier, dans l'ordre d'`external_ids` (par rôle, puis par valeur) : le sien pour un enregistrement source HAL, le dépôt dont il est tiré pour un enregistrement source ScanR ou OpenAlex, à défaut le premier dépôt qu'il cite.
- **Token métadonnée** : `("metadata_block", "<doc_type>|<title_normalized>|<publication_year>")`, pour **tout** `doc_type` (empiriquement ~99 % de même-œuvre par type au-delà du seuil de longueur de titre). Le `doc_type` dans la clé impose l'égalité de type (« un DOI, une œuvre » étendu au type). Garde de **longueur minimale de titre** : écarte les collisions de titres génériques. La thèse passe par ce même token (`thesis|<titre>|<année>`) ; `thesis` et `ongoing_thesis` ne co-bloquent jamais (leurs années diffèrent — inscription vs soutenance). Les paliers plus lâches (hors `doc_type`, titres courts via le conteneur), qui exigeraient un second accord pairwise, relèvent d'un mécanisme distinct.

La projection est la définition Python des clés de confirmation. La réconciliation des publications (`pipeline/transformation/publications/reconciliation.py`) la consomme. Son voisinage SQL (`_UNIVERSE_SQL`) réécrit ces clés ; `TestUniverseMatchesPythonTokens` vérifie que les deux concordent.

Un identifiant de `external_ids` devient une clé de confirmation par son ajout à `CONFIRMATION_ID_TYPES` et un champ de même nom dans `ConfirmationKeys`. Le voisinage SQL d'un identifiant scalaire en dérive. Une clé composite demande son calcul dans `project_confirmation_keys` et sa branche dans `_UNIVERSE_SQL`. `run_pipeline --only publications --rebuild-publications` applique une clé au stock.

Les valeurs sont lues sur la `source_record` **corrigée** (colonnes typées + `external_ids`), déjà normalisées (phase `normalize`) puis corrigées (phase `metadata_correction`). Les identifiants repassent par le normaliseur de leur type : idempotent sur des valeurs propres, forme canonique unique quel que soit l'appelant. Le DOI lu est la colonne nue (concept Zenodo déjà substitué en amont par `metadata_correction`) : la projection ignore Zenodo.
"""

from collections.abc import Mapping
from dataclasses import dataclass, fields

from domain.publications.identifiers import DOI
from domain.source_records.external_ids import (
    MULTIVALUED_ID_TYPES,
    ExternalIdType,
    external_id_normalizer,
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


# Seuil de longueur de `title_normalized` (caractères, strict) en-deçà duquel un titre est trop
# générique pour rapprocher deux publications : token `metadata_block` (matching de clés), univers
# de réconciliation, appariement par titre (relations, dédup HAL). Les requêtes SQL l'interpolent.
DISCRIMINANT_TITLE_MIN_LENGTH = 30


@dataclass(frozen=True, slots=True)
class ConfirmationKeys:
    """Clés de confirmation portées par une `source_record`, normalisées.

    Chaque clé est au plus unitaire ; `hal_id` est le premier identifiant HAL que liste la `source_record`. Les identifiants sont des chaînes canoniques (forme produite par les VO), prêtes pour les lookups `find_by_*`. `metadata_block` = `"<doc_type>|<title_normalized>|<publication_year>"` pour toute `source_record` à `doc_type` présent et titre assez long. Une clé absente vaut `None`.
    """

    doi: str | None
    nnt: str | None
    pmid: str | None
    arxiv_id: str | None
    hal_id: str | None
    metadata_block: str | None

    def tokens(self) -> frozenset[tuple[str, str]]:
        """Jeu de tokens `(nom de la clé, valeur)` de la `source_record`, pour le clustering.

        Chaque token est namespacé par son type : un DOI `x` et un NNT `x` ne s'apparentent pas. Deux `source_records` partageant un token sont reliées dans le graphe de composantes (cf. `connected_components`). Une clé absente ne produit pas de token.
        """
        return frozenset(
            (name, value) for name in _KEY_NAMES if (value := getattr(self, name)) is not None
        )


_KEY_NAMES = tuple(f.name for f in fields(ConfirmationKeys))
assert set(_KEY_NAMES) == {"doi", "metadata_block", *CONFIRMATION_ID_TYPES}, (
    "champs de ConfirmationKeys désynchronisés de CONFIRMATION_ID_TYPES"
)


# Nom, normaliseur et multivaluation de chaque identifiant de confirmation.
_CONFIRMATION_IDS = tuple(
    (str(t), external_id_normalizer(t), t in MULTIVALUED_ID_TYPES) for t in CONFIRMATION_ID_TYPES
)


def _confirmation_ids(ids: Mapping[str, object]) -> dict[str, str | None]:
    """Valeur normalisée de chaque identifiant de confirmation de `ids`. Un type multivalué a pour valeur le premier élément de sa liste."""
    values: dict[str, str | None] = {}
    for name, normalize, multivalued in _CONFIRMATION_IDS:
        raw = ids.get(name)
        if multivalued:
            raw = raw[0] if isinstance(raw, list) and raw else None
        values[name] = normalize(raw) if isinstance(raw, str) else None
    return values


def project_confirmation_keys(
    doi: str | None,
    external_ids: Mapping[str, object] | None,
    doc_type: str | None,
    title_normalized: str | None,
    publication_year: int | None,
) -> ConfirmationKeys:
    """Extrait les clés de confirmation normalisées d'une `source_record`.

    Le DOI est lu sur la colonne (déjà corrigée, concept Zenodo inclus). Une valeur d'identifiant malformée est écartée silencieusement, comme une clé absente. `metadata_block` est posée pour toute `source_record` à `doc_type` présent, `publication_year` présent et `title_normalized` plus long que `DISCRIMINANT_TITLE_MIN_LENGTH`.
    """
    ids: Mapping[str, object] = external_ids if isinstance(external_ids, Mapping) else {}
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
        **_confirmation_ids(ids),
    )
