"""Câblage de la phase `subjects`."""

from __future__ import annotations

from pipeline.context import Phase


def build() -> Phase:
    """Sujets et mots-clés : ingestion, puis recalcul des décomptes.

    L'ingestion reprend les publications dont le contenu a changé depuis leur dernier passage, lit les sujets de leurs documents sources, et purge les sujets restés sans lien. Le recalcul qui suit compte les publications de chaque sujet et rafraîchit la matview des paires de sujets présents sur une même publication.

    La phase `authorships` ayant supprimé les publications sans auteur, `publication_subjects` contient seulement le périmètre, dont les deux décomptes héritent.

    `--rebuild-subjects` reprend toutes les publications, pour propager une évolution des règles d'ingestion sur tout le stock.

    Séquence, transactions et métriques dans `pipeline/publications/subjects.py`.
    """
    from pipeline.publications.subjects import SubjectsPhase
    from pipeline.publications.subjects_queries import SubjectsIngestionQueries

    return SubjectsPhase(SubjectsIngestionQueries())
