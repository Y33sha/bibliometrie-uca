"""Projection d'une `source_publication` vers son jeu de clés de confirmation.

Une *clé de confirmation* est un attribut cross-source par lequel deux `source_publications` attestent du même document. Deux familles :

- **Identifiants** : DOI, NNT, HAL ID, PMID — égalité directe.
- **Token métadonnée** : `("metadata_block", "<doc_type>|<title_normalized>|<pub_year>")`, pour **tout** `doc_type` (audit chantier `DATA_dedup-pairwise-gated` : ~99 % de même-œuvre par type au-delà du seuil de longueur). `doc_type` dans la clé = égalité de type requise (décision « DOI = identité » étendue au type). Garde de **longueur minimale de titre** : écarte les collisions de titres génériques. La thèse passe par ce même token (`thesis|<titre>|<année>`) ; pas de collapse `thesis`/`ongoing_thesis` (leurs années diffèrent — inscription vs soutenance —, ils ne co-bloquent donc jamais). Les paliers plus lâches (hors `doc_type`, titres courts via le conteneur) qui exigeraient un second accord pairwise relèvent d'un mécanisme distinct.

La projection est l'unique définition de « quelles clés porte cette SP », consommée par la passe d'assignation + réconciliation des composantes (`reconcile_components`) — aucun site ne ré-encode son extraction.

Les valeurs sont lues sur la SP **corrigée** (colonnes typées + `external_ids`), déjà normalisées en amont (phase `normalize`) puis corrigées (phase `metadata_correction`). Les identifiants repassent par les VO : idempotent sur des valeurs propres, forme canonique unique quel que soit l'appelant (le clustering relie les SP par égalité de tokens). Le DOI lu est la colonne nue (concept Zenodo déjà substitué a priori par `metadata_correction`) : la projection ignore Zenodo.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from domain.publications.identifiers import DOI, NNT, PMID, HALId

# Seuil de longueur de `title_normalized` (caractères, strict) pour le token `metadata_block` :
# écarte les collisions de titres génériques. Dupliqué en SQL dans la branche `metadata_block`
# de l'univers de réconciliation (`publications_reconciliation`) — garder synchrone.
_METADATA_BLOCK_MIN_TITLE_LENGTH = 30


@dataclass(frozen=True, slots=True)
class ConfirmationKeys:
    """Clés de confirmation portées par une `source_publication`, normalisées.

    `hal_ids` est multivalué (une SP peut référencer plusieurs dépôts HAL) ; les autres clés sont au plus unitaires. Les identifiants sont des chaînes canoniques (forme produite par les VO), prêtes pour les lookups `find_by_*`. `metadata_block` = `"<doc_type>|<title_normalized>|<pub_year>"` pour toute SP à `doc_type` présent et titre assez long. Une clé absente vaut `None` (tuple vide pour `hal_ids`).
    """

    doi: str | None
    nnt: str | None
    pmid: str | None
    hal_ids: tuple[str, ...]
    metadata_block: str | None

    def tokens(self) -> frozenset[tuple[str, str]]:
        """Jeu de tokens `(type, valeur)` portés par la SP, pour le clustering.

        Chaque token est namespacé par son type : un DOI `x` et un NNT `x` ne s'apparentent pas. Deux `source_publications` partageant un token sont reliées dans le graphe de composantes (cf. `connected_components`). Une clé absente ne produit pas de token.
        """
        toks: set[tuple[str, str]] = set()
        if self.doi:
            toks.add(("doi", self.doi))
        if self.nnt:
            toks.add(("nnt", self.nnt))
        if self.pmid:
            toks.add(("pmid", self.pmid))
        if self.metadata_block:
            toks.add(("metadata_block", self.metadata_block))
        toks.update(("hal_id", hal) for hal in self.hal_ids)
        return frozenset(toks)


def project_confirmation_keys(
    doi: str | None,
    external_ids: Mapping[str, object] | None,
    doc_type: str | None,
    title_normalized: str | None,
    pub_year: int | None,
) -> ConfirmationKeys:
    """Extrait les clés de confirmation normalisées d'une `source_publication`.

    `external_ids` porte `nnt`, `pmid`, `hal_id` (liste). Le DOI est lu sur la colonne (déjà corrigée, concept Zenodo inclus). Une valeur d'identifiant malformée est écartée silencieusement (`try_parse` → `None`), comme une clé absente. `metadata_block` est posée pour toute SP à `doc_type` présent, `pub_year` présent et `title_normalized` plus long que `_METADATA_BLOCK_MIN_TITLE_LENGTH`.
    """
    ids: Mapping[str, object] = external_ids if isinstance(external_ids, Mapping) else {}

    doi_vo = DOI.try_parse(doi) if isinstance(doi, str) else None

    nnt_raw = ids.get("nnt")
    nnt_vo = NNT.try_parse(nnt_raw) if isinstance(nnt_raw, str) else None

    pmid_raw = ids.get("pmid")
    pmid_vo = PMID.try_parse(pmid_raw) if isinstance(pmid_raw, str) else None

    raw_hal = ids.get("hal_id")
    hal_ids = tuple(
        str(hal_vo)
        for hal in (raw_hal if isinstance(raw_hal, list) else [])
        if isinstance(hal, str) and (hal_vo := HALId.try_parse(hal)) is not None
    )

    metadata_block = (
        f"{doc_type}|{title_normalized}|{pub_year}"
        if doc_type
        and title_normalized
        and len(title_normalized) > _METADATA_BLOCK_MIN_TITLE_LENGTH
        and pub_year is not None
        else None
    )

    return ConfirmationKeys(
        doi=str(doi_vo) if doi_vo else None,
        nnt=str(nnt_vo) if nnt_vo else None,
        pmid=str(pmid_vo) if pmid_vo else None,
        hal_ids=hal_ids,
        metadata_block=metadata_block,
    )
