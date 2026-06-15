"""Projection d'une `source_publication` vers son jeu de clés de confirmation.

Une *clé de confirmation* est un identifiant cross-source par lequel deux `source_publications` attestent du même document : DOI, NNT, HAL ID, PMID. La projection est l'unique définition de « quelles clés porte cette SP », destinée à être partagée par l'assignation (`match_or_create`) et par la réconciliation des composantes — aucun site ne ré-encode sa propre extraction.

Les valeurs sont lues sur la SP **corrigée** (colonne `doi` typée + `external_ids`), déjà normalisées en amont (phase `normalize`) puis corrigées (phase `metadata_correction`). La projection les repasse néanmoins par les VO d'identifiants : idempotent sur des valeurs propres, et garant d'une forme canonique unique quel que soit l'appelant (les lookups repo `find_by_*` consomment cette forme).

Le **DOI effectif** d'une SP Zenodo est son *concept* DOI (`external_ids.zenodo_concept_doi`, résolu par `resolve_zenodo_concept`), pas le DOI de version porté par la colonne : concept et versions convergent ainsi vers une même publication. La projection applique cette substitution en un point, pour que tous les consommateurs en héritent.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from domain.publications.identifiers import DOI, NNT, PMID, HALId


@dataclass(frozen=True, slots=True)
class ConfirmationKeys:
    """Clés d'identifiant portées par une `source_publication`, normalisées.

    `hal_ids` est multivalué (une SP peut référencer plusieurs dépôts HAL) ; les autres clés sont au plus unitaires. Toutes les valeurs sont des chaînes canoniques (forme produite par les VO d'identifiants), prêtes pour les lookups `find_by_*`. Une clé absente vaut `None` (tuple vide pour `hal_ids`).
    """

    doi: str | None
    nnt: str | None
    pmid: str | None
    hal_ids: tuple[str, ...]

    def tokens(self) -> frozenset[tuple[str, str]]:
        """Jeu de tokens `(type, valeur)` portés par la SP, pour le clustering.

        Chaque token est namespacé par son type d'identifiant : un DOI `x` et un NNT `x` ne s'apparentent pas. Deux `source_publications` partageant un token sont reliées dans le graphe de composantes (cf. `connected_components`). Une clé absente ne produit pas de token.
        """
        toks: set[tuple[str, str]] = set()
        if self.doi:
            toks.add(("doi", self.doi))
        if self.nnt:
            toks.add(("nnt", self.nnt))
        if self.pmid:
            toks.add(("pmid", self.pmid))
        toks.update(("hal_id", hal) for hal in self.hal_ids)
        return frozenset(toks)


def project_confirmation_keys(
    doi: str | None, external_ids: Mapping[str, object] | None
) -> ConfirmationKeys:
    """Extrait les clés de confirmation normalisées d'une `source_publication`.

    `external_ids` porte `nnt`, `pmid`, `hal_id` (liste) et `zenodo_concept_doi` (conventions des normalizers). Le DOI effectif est le concept Zenodo s'il est présent, sinon le DOI de la colonne. Une valeur malformée est écartée silencieusement (`try_parse` → `None`), comme une clé absente.
    """
    ids: Mapping[str, object] = external_ids if isinstance(external_ids, Mapping) else {}

    concept = ids.get("zenodo_concept_doi")
    effective_doi = concept if isinstance(concept, str) and concept else doi
    doi_vo = DOI.try_parse(effective_doi) if isinstance(effective_doi, str) else None

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

    return ConfirmationKeys(
        doi=str(doi_vo) if doi_vo else None,
        nnt=str(nnt_vo) if nnt_vo else None,
        pmid=str(pmid_vo) if pmid_vo else None,
        hal_ids=hal_ids,
    )
