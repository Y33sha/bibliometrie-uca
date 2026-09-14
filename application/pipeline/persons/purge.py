"""Purge de la phase personnes : re-orphelinage des formes de nom devenues ambiguës, suppression des attributions d'identifiant sans appui, puis suppression des personnes vidées.

Tourne **après `populate_person_name_forms`**, qui régénère les formes canoniques : c'est seulement là qu'une forme réduite (« j martin »), partagée par une personne réduite et par la forme pleine dont elle est l'initiale, devient ambiguë. Le re-orphelinage détache alors les signatures nominales à forme ambiguë, non épinglées ; le GC supprime les personnes ainsi vidées (hors référentiel RH), ce qui retire leurs formes canoniques et désambiguïse. La signature libérée rejoint la forme pleine au `match` du run suivant.

Placée après le peuplement, la purge voit l'ambiguïté née des créations du run courant : la convergence se fait en deux runs.

Elle supprime aussi les attributions d'identifiant d'origine automatique, en attente, qu'aucune signature de leur personne ne porte : celles d'un rattachement défait pendant le passage.
"""

import logging

from sqlalchemy import Connection

from application.ports.pipeline.persons.matching import PersonsMatchingQueries


def purge(
    conn: Connection, queries: PersonsMatchingQueries, logger: logging.Logger
) -> dict[str, int]:
    """Re-orpheline les signatures nominales à forme ambiguë, supprime les attributions d'identifiant sans appui, puis les personnes vidées.

    Retourne les compteurs `{reorphaned, deleted_attributions, deleted_persons}`. Le commit est laissé au caller.
    """
    reorphaned = queries.reorphan_ambiguous_nominal(conn)
    deleted_attributions = queries.delete_unsupported_identifier_attributions(conn)
    deleted_persons = queries.delete_empty_persons(conn)

    return {
        "reorphaned": reorphaned,
        "deleted_attributions": deleted_attributions,
        "deleted_persons": deleted_persons,
    }
