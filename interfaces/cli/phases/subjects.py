"""Câblage de la phase `subjects`."""

from __future__ import annotations

from application.pipeline.context import Phase


def build() -> Phase:
    """Sujets et mots-clés : ingestion, puis recalcul des décomptes.

    L'ingestion reprend les publications dont le contenu a changé depuis leur dernier passage, lit les sujets de leurs documents sources, et purge les sujets restés sans lien. Le recalcul qui suit compte les publications de chaque sujet et rafraîchit la matview des paires de sujets présents sur une même publication.

    La phase `authorships` ayant supprimé les publications sans auteur, `publication_subjects` contient seulement le périmètre, dont les deux décomptes héritent.

    `--rebuild-subjects` reprend toutes les publications, pour propager une évolution des règles d'ingestion sur tout le stock.

    Séquence, transactions et métriques dans `application/pipeline/subjects/phase.py`.
    """
    from application.pipeline.subjects.phase import SubjectsPhase
    from infrastructure.pipeline.subjects import PgSubjectsIngestionQueries

    return SubjectsPhase(PgSubjectsIngestionQueries())
