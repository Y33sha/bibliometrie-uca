"""Purge de la phase personnes : re-orphelinage des formes de nom devenues ambiguës,
puis suppression des personnes vidées.

Tourne **après `populate_person_name_forms`**, qui régénère les formes canoniques : c'est
seulement là qu'une forme réduite (« j martin »), partagée par une personne réduite et par la
forme pleine dont elle est l'initiale, devient ambiguë. Le re-orphelinage détache alors les
signatures nominales à forme ambiguë, non épinglées ; le GC supprime les personnes ainsi
vidées (hors référentiel RH), ce qui retire leurs formes canoniques et désambiguïse. La
signature libérée rejoint la forme pleine au `match` du run suivant.

Placer la purge après le peuplement — et non en tête de phase — évite qu'elle lise les formes
d'un run de retard : elle voit l'ambiguïté née des créations du run courant, et la convergence
se fait en deux runs au lieu de trois.
"""

import logging

from sqlalchemy import Connection

from application.ports.pipeline.persons_create import PersonsCreateQueries


def purge(
    conn: Connection, queries: PersonsCreateQueries, logger: logging.Logger
) -> dict[str, int]:
    """Re-orpheline les signatures nominales à forme ambiguë puis supprime les personnes vidées.

    Retourne les compteurs `{reorphaned, deleted_persons}`. Le commit est laissé au caller.
    """
    logger.info("Re-orphelinage des formes de nom devenues ambiguës...")
    reorphaned = queries.reorphan_ambiguous_nominal(conn)
    logger.info("  → %d signatures détachées", reorphaned)

    logger.info("GC des personnes vidées...")
    deleted_persons = queries.delete_empty_persons(conn)
    logger.info("  → %d personnes supprimées", deleted_persons)

    return {"reorphaned": reorphaned, "deleted_persons": deleted_persons}
