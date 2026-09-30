"""Projection d'une `source_publication` vers son jeu de clés de confirmation.

Une *clé de confirmation* est un attribut cross-source par lequel deux `source_publications` attestent du même document. Deux familles :

- **Identifiants** : DOI, NNT, HAL ID, PMID, arXiv ID — égalité directe. Une notice qui liste plusieurs identifiants HAL a pour clé le premier : le sien pour une notice HAL, le dépôt dont elle est tirée pour une notice ScanR, sa première localisation pour une notice OpenAlex.
- **Token métadonnée** : `("metadata_block", "<doc_type>|<title_normalized>|<pub_year>")`, pour **tout** `doc_type` (empiriquement ~99 % de même-œuvre par type au-delà du seuil de longueur de titre). Le `doc_type` dans la clé impose l'égalité de type (« DOI = identité » étendue au type). Garde de **longueur minimale de titre** : écarte les collisions de titres génériques. La thèse passe par ce même token (`thesis|<titre>|<année>`) ; `thesis` et `ongoing_thesis` ne co-bloquent jamais (leurs années diffèrent — inscription vs soutenance). Les paliers plus lâches (hors `doc_type`, titres courts via le conteneur), qui exigeraient un second accord pairwise, relèvent d'un mécanisme distinct.

La projection est l'unique définition des clés que porte une `source_publication`, consommée par la passe d'assignation et de réconciliation des composantes (`reconcile_components`) — aucun autre site ne ré-encode son extraction.

Les valeurs sont lues sur la `source_publication` **corrigée** (colonnes typées + `external_ids`), déjà normalisées (phase `normalize`) puis corrigées (phase `metadata_correction`). Les identifiants repassent par les VO : idempotent sur des valeurs propres, forme canonique unique quel que soit l'appelant. Le DOI lu est la colonne nue (concept Zenodo déjà substitué en amont par `metadata_correction`) : la projection ignore Zenodo.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from domain.publications.identifiers import DOI, NNT, PMID, ArxivId, HALId
from domain.source_publications.external_ids import MULTIVALUED_ID_TYPES, ExternalIdType

# Types d'`external_ids` par lesquels deux `source_publications` désignent le même document. Le DOI (colonne dédiée) et le token métadonnée sont les autres familles de clés de confirmation.
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
    """Clés de confirmation portées par une `source_publication`, normalisées.

    Chaque clé est au plus unitaire ; `hal_id` est le premier identifiant HAL que liste la `source_publication`. Les identifiants sont des chaînes canoniques (forme produite par les VO), prêtes pour les lookups `find_by_*`. `metadata_block` = `"<doc_type>|<title_normalized>|<pub_year>"` pour toute `source_publication` à `doc_type` présent et titre assez long. Une clé absente vaut `None`.
    """

    doi: str | None
    nnt: str | None
    pmid: str | None
    arxiv_id: str | None
    hal_id: str | None
    metadata_block: str | None

    def tokens(self) -> frozenset[tuple[str, str]]:
        """Jeu de tokens `(type, valeur)` portés par la `source_publication`, pour le clustering.

        Chaque token est namespacé par son type : un DOI `x` et un NNT `x` ne s'apparentent pas. Deux `source_publications` partageant un token sont reliées dans le graphe de composantes (cf. `connected_components`). Une clé absente ne produit pas de token.
        """
        toks: set[tuple[str, str]] = set()
        if self.doi:
            toks.add(("doi", self.doi))
        if self.nnt:
            toks.add((ExternalIdType.NNT, self.nnt))
        if self.pmid:
            toks.add((ExternalIdType.PMID, self.pmid))
        if self.arxiv_id:
            toks.add((ExternalIdType.ARXIV_ID, self.arxiv_id))
        if self.metadata_block:
            toks.add(("metadata_block", self.metadata_block))
        if self.hal_id:
            toks.add((ExternalIdType.HAL_ID, self.hal_id))
        return frozenset(toks)


def project_confirmation_keys(
    doi: str | None,
    external_ids: Mapping[str, object] | None,
    doc_type: str | None,
    title_normalized: str | None,
    pub_year: int | None,
) -> ConfirmationKeys:
    """Extrait les clés de confirmation normalisées d'une `source_publication`.

    `external_ids` porte `nnt`, `pmid`, `arxiv_id`, `hal_id` (liste). Le DOI est lu sur la colonne (déjà corrigée, concept Zenodo inclus). Une valeur d'identifiant malformée est écartée silencieusement (`try_parse` → `None`), comme une clé absente. `metadata_block` est posée pour toute `source_publication` à `doc_type` présent, `pub_year` présent et `title_normalized` plus long que `DISCRIMINANT_TITLE_MIN_LENGTH`.
    """
    ids: Mapping[str, object] = external_ids if isinstance(external_ids, Mapping) else {}

    doi_vo = DOI.try_parse(doi) if isinstance(doi, str) else None

    nnt_raw = ids.get(ExternalIdType.NNT)
    nnt_vo = NNT.try_parse(nnt_raw) if isinstance(nnt_raw, str) else None

    pmid_raw = ids.get(ExternalIdType.PMID)
    pmid_vo = PMID.try_parse(pmid_raw) if isinstance(pmid_raw, str) else None

    arxiv_raw = ids.get(ExternalIdType.ARXIV_ID)
    arxiv_vo = ArxivId.try_parse(arxiv_raw) if isinstance(arxiv_raw, str) else None

    raw_hal = ids.get(ExternalIdType.HAL_ID)
    first_hal = raw_hal[0] if isinstance(raw_hal, list) and raw_hal else None
    hal_vo = HALId.try_parse(first_hal) if isinstance(first_hal, str) else None

    metadata_block = (
        f"{doc_type}|{title_normalized}|{pub_year}"
        if doc_type
        and title_normalized
        and len(title_normalized) > DISCRIMINANT_TITLE_MIN_LENGTH
        and pub_year is not None
        else None
    )

    return ConfirmationKeys(
        doi=str(doi_vo) if doi_vo else None,
        nnt=str(nnt_vo) if nnt_vo else None,
        pmid=str(pmid_vo) if pmid_vo else None,
        arxiv_id=str(arxiv_vo) if arxiv_vo else None,
        hal_id=str(hal_vo) if hal_vo else None,
        metadata_block=metadata_block,
    )
