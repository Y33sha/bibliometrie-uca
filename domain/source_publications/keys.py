"""Projection d'une `source_publication` vers son jeu de clés de confirmation.

Une *clé de confirmation* est un attribut cross-source par lequel deux `source_publications` attestent du même document. Deux familles :

- **Identifiants** : DOI, NNT, HAL ID, PMID — égalité directe.
- **Token métadonnée** : pour une classe où une clé composite dérivable de la SP est assez **sélective** pour valoir identité par égalité. Deux cas : la **thèse** (`("thesis_meta", "<title_normalized>|<pub_year>")` — titre de thèse + année unique en pratique, `thesis`/`ongoing_thesis` collapsés, sans garde de longueur) ; le **bloc tier-1** (`("metadata_block", "<doc_type>|<title_normalized>|<pub_year>")`) pour les types sans identifiant fiable `conference_paper`/`poster`/`book_chapter`, gardé par une **longueur minimale de titre** (écarte les collisions de titres génériques) — `doc_type` dans la clé (égalité requise) ; audit ~99,95 % de même-œuvre (cf. fiche `DATA_dedup-pairwise-gated`). Les paliers plus lâches (hors `doc_type`, ou titres courts via le conteneur) qui exigeraient un second accord pairwise relèvent d'un mécanisme distinct.

La projection est l'unique définition de « quelles clés porte cette SP », consommée par la passe d'assignation + réconciliation des composantes (`reconcile_components`) — aucun site ne ré-encode son extraction.

Les valeurs sont lues sur la SP **corrigée** (colonnes typées + `external_ids`), déjà normalisées en amont (phase `normalize`) puis corrigées (phase `metadata_correction`). Les identifiants repassent par les VO : idempotent sur des valeurs propres, forme canonique unique quel que soit l'appelant (le clustering relie les SP par égalité de tokens). Le DOI lu est la colonne nue (concept Zenodo déjà substitué a priori par `metadata_correction`) : la projection ignore Zenodo.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from domain.publications.identifiers import DOI, NNT, PMID, HALId

# Types dont le couple (title_normalized, pub_year) vaut identité par égalité (token thèse).
_THESIS_DOC_TYPES: frozenset[str] = frozenset({"thesis", "ongoing_thesis"})

# Types sans identifiant fiable dont le triplet (doc_type, title_normalized, pub_year) vaut
# identité par égalité (token tier-1), à condition que le titre soit assez long pour écarter
# les collisions de titres génériques (audit chantier dedup-pairwise-gated : ~99,95 % de
# même-œuvre au-delà du seuil). `doc_type` est dans la clé : égalité de type requise.
_TIER1_DOC_TYPES: frozenset[str] = frozenset({"conference_paper", "poster", "book_chapter"})
# Seuil de longueur de `title_normalized` (caractères, strict). Dupliqué en SQL dans la branche
# `metadata_block` de l'univers de réconciliation (`publications_reconciliation`) — garder synchrone.
_TIER1_MIN_TITLE_LENGTH = 30


@dataclass(frozen=True, slots=True)
class ConfirmationKeys:
    """Clés de confirmation portées par une `source_publication`, normalisées.

    `hal_ids` est multivalué (une SP peut référencer plusieurs dépôts HAL) ; les autres clés sont au plus unitaires. Les identifiants sont des chaînes canoniques (forme produite par les VO), prêtes pour les lookups `find_by_*`. `thesis_meta` = `"<title_normalized>|<pub_year>"` pour une thèse identifiable par titre+année. `metadata_block` = `"<doc_type>|<title_normalized>|<pub_year>"` pour un type tier-1 à titre assez long. Une clé absente vaut `None` (tuple vide pour `hal_ids`).
    """

    doi: str | None
    nnt: str | None
    pmid: str | None
    hal_ids: tuple[str, ...]
    thesis_meta: str | None
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
        if self.thesis_meta:
            toks.add(("thesis_meta", self.thesis_meta))
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

    `external_ids` porte `nnt`, `pmid`, `hal_id` (liste). Le DOI est lu sur la colonne (déjà corrigée, concept Zenodo inclus). Une valeur d'identifiant malformée est écartée silencieusement (`try_parse` → `None`), comme une clé absente. `thesis_meta` est posée pour une thèse à titre+année présents ; `metadata_block` pour un type tier-1 (`conference_paper`/`poster`/`book_chapter`) à `title_normalized` plus long que `_TIER1_MIN_TITLE_LENGTH`.
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

    thesis_meta = (
        f"{title_normalized}|{pub_year}"
        if doc_type in _THESIS_DOC_TYPES and title_normalized and pub_year is not None
        else None
    )

    metadata_block = (
        f"{doc_type}|{title_normalized}|{pub_year}"
        if doc_type in _TIER1_DOC_TYPES
        and title_normalized
        and len(title_normalized) > _TIER1_MIN_TITLE_LENGTH
        and pub_year is not None
        else None
    )

    return ConfirmationKeys(
        doi=str(doi_vo) if doi_vo else None,
        nnt=str(nnt_vo) if nnt_vo else None,
        pmid=str(pmid_vo) if pmid_vo else None,
        hal_ids=hal_ids,
        thesis_meta=thesis_meta,
        metadata_block=metadata_block,
    )
