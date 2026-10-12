"""Câblage de la phase `publications`."""

from __future__ import annotations

from pipeline.context import Phase


def build() -> Phase:
    """Assignation des `source_publications` aux publications, en une seule passe.

    Les documents sources modifiés et leur voisinage sont regroupés par composante connexe de leurs clés de confirmation — DOI, NNT, hal_id, PMID, et pour les thèses le couple titre-année. Chaque document rejoint la publication qui ancre sa partition. Rattacher un document, fusionner deux publications ou en scinder une sont trois lectures du même regroupement.

    La phase suit `metadata_correction`, qui a substitué le DOI de concept aux DOI de version DataCite : le regroupement se fait alors sur le concept.

    `--rebuild-publications` marque tout le stock à traiter avant le regroupement, qui reprend alors le corpus entier. Sert après une évolution des règles de clés, pour matérialiser les fusions et scissions qu'elles impliquent.

    Séquence, transactions et métriques dans `pipeline/publications/publications.py`.
    """
    from infrastructure.repositories import publication_repository
    from pipeline.publications.publications import PublicationsPhase
    from pipeline.publications.reconciliation import (
        PublicationsReconciliationQueries,
    )

    return PublicationsPhase(
        PublicationsReconciliationQueries(),
        publication_repo_factory=publication_repository,
    )
