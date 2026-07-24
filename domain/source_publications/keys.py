"""Projection d'une `source_publication` vers son jeu de clés de confirmation.

Une *clé de confirmation* est un attribut cross-source par lequel deux `source_publications` attestent du même document. Deux familles :

- **Identifiants** : DOI, NNT, HAL ID, PMID, arXiv ID — égalité directe.
- **Token métadonnée** : `("metadata_block", "<doc_type>|<title_normalized>|<pub_year>")`, pour **tout** `doc_type` (empiriquement ~99 % de même-œuvre par type au-delà du seuil de longueur de titre). Le `doc_type` dans la clé impose l'égalité de type (« DOI = identité » étendue au type). Garde de **longueur minimale de titre** : écarte les collisions de titres génériques. La thèse passe par ce même token (`thesis|<titre>|<année>`) ; `thesis` et `ongoing_thesis` ne co-bloquent jamais (leurs années diffèrent — inscription vs soutenance). Les paliers plus lâches (hors `doc_type`, titres courts via le conteneur), qui exigeraient un second accord pairwise, relèvent d'un mécanisme distinct.

La projection est l'unique définition des clés que porte une `source_publication`, consommée par la passe d'assignation et de réconciliation des composantes (`reconcile_components`) — aucun autre site ne ré-encode son extraction.

Les valeurs sont lues sur la `source_publication` **corrigée** (colonnes typées + `external_ids`), déjà normalisées (phase `normalize`) puis corrigées (phase `metadata_correction`). Les identifiants repassent par les VO : idempotent sur des valeurs propres, forme canonique unique quel que soit l'appelant. Le DOI lu est la colonne nue (concept Zenodo déjà substitué en amont par `metadata_correction`) : la projection ignore Zenodo.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from domain.publications.identifiers import DOI, NNT, PMID, ArxivId, HALId


class ConfirmationKey(StrEnum):
    """Identifiant `external_ids` par lequel deux `source_publications` attestent du même document. Le DOI (colonne dédiée) et le token métadonnée sont d'autres familles de clés de confirmation, hors de cet enum."""

    HAL_ID = "hal_id"
    ARXIV_ID = "arxiv_id"
    PMID = "pmid"
    NNT = "nnt"


# Seuil de longueur de `title_normalized` (caractères, strict) en-deçà duquel un titre est trop
# générique pour rapprocher deux publications : token `metadata_block` (matching de clés), univers
# de réconciliation, appariement par titre (relations, dédup HAL). Les requêtes SQL l'interpolent.
DISCRIMINANT_TITLE_MIN_LENGTH = 30


@dataclass(frozen=True, slots=True)
class ConfirmationKeys:
    """Clés de confirmation portées par une `source_publication`, normalisées.

    `hal_ids` est multivalué (une `source_publication` peut référencer plusieurs dépôts HAL) ; les autres clés sont au plus unitaires. Les identifiants sont des chaînes canoniques (forme produite par les VO), prêtes pour les lookups `find_by_*`. `metadata_block` = `"<doc_type>|<title_normalized>|<pub_year>"` pour toute `source_publication` à `doc_type` présent et titre assez long. Une clé absente vaut `None` (tuple vide pour `hal_ids`).
    """

    doi: str | None
    nnt: str | None
    pmid: str | None
    arxiv_id: str | None
    hal_ids: tuple[str, ...]
    metadata_block: str | None

    def tokens(self) -> frozenset[tuple[str, str]]:
        """Jeu de tokens `(type, valeur)` portés par la `source_publication`, pour le clustering.

        Chaque token est namespacé par son type : un DOI `x` et un NNT `x` ne s'apparentent pas. Deux `source_publications` partageant un token sont reliées dans le graphe de composantes (cf. `connected_components`). Une clé absente ne produit pas de token.
        """
        toks: set[tuple[str, str]] = set()
        if self.doi:
            toks.add(("doi", self.doi))
        if self.nnt:
            toks.add((ConfirmationKey.NNT, self.nnt))
        if self.pmid:
            toks.add((ConfirmationKey.PMID, self.pmid))
        if self.arxiv_id:
            toks.add((ConfirmationKey.ARXIV_ID, self.arxiv_id))
        if self.metadata_block:
            toks.add(("metadata_block", self.metadata_block))
        toks.update((ConfirmationKey.HAL_ID, hal) for hal in self.hal_ids)
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

    nnt_raw = ids.get(ConfirmationKey.NNT)
    nnt_vo = NNT.try_parse(nnt_raw) if isinstance(nnt_raw, str) else None

    pmid_raw = ids.get(ConfirmationKey.PMID)
    pmid_vo = PMID.try_parse(pmid_raw) if isinstance(pmid_raw, str) else None

    arxiv_raw = ids.get(ConfirmationKey.ARXIV_ID)
    arxiv_vo = ArxivId.try_parse(arxiv_raw) if isinstance(arxiv_raw, str) else None

    raw_hal = ids.get(ConfirmationKey.HAL_ID)
    hal_ids = tuple(
        str(hal_vo)
        for hal in (raw_hal if isinstance(raw_hal, list) else [])
        if isinstance(hal, str) and (hal_vo := HALId.try_parse(hal)) is not None
    )

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
        hal_ids=hal_ids,
        metadata_block=metadata_block,
    )
