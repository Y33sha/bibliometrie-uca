"""Purge de la phase personnes : marquage des contributions rattachées par le nom dont la décision change, suppression des attributions d'identifiant sans appui, puis suppression des personnes sans contribution du périmètre.

La purge suit `populate_person_name_forms`, qui régénère les formes dérivées du nom des personnes. Une forme réduite (« j martin ») devient ambiguë quand elle désigne à la fois une personne au prénom réduit et une personne au prénom plein. La purge redécide les contributions rattachées par le nom avec la règle du rattachement (`decide_contribution`). Celles dont la décision change sont marquées pour la redécision de leur personne : au run suivant, le rattachement des contributions les laisse sans personne. La personne réduite, sans autre contribution du périmètre, est alors supprimée avec ses formes de nom, et la forme réduite redevient univoque. La contribution rejoint la personne au prénom plein au run d'après.
"""

from sqlalchemy import Connection, text

from domain.persons.contribution_matching import (
    NAME_MATCH_REASONS,
    ContributionOutcome,
    decide_contribution,
)
from domain.persons.identifiers import (
    AttributionStatus,
    IdentifierOrigin,
)
from infrastructure.db.queues import Queue, enqueue_ids
from infrastructure.repositories.person_repository import person_without_decision_sql
from infrastructure.sql_fragments import (
    CONTRIBUTIONS_AND_SOURCES,
    DETACHED_CONTRIBUTION,
    active_name_form,
    identifier_neutralized,
    in_clause,
)
from pipeline.transformation.persons.contribution_resolution import load_contributions, load_index
from pipeline.transformation.persons.first_names import conflicting_reduced_first_names
from pipeline.transformation.persons.store import fetch_rejected_person_ids_by_publication

_CONTESTED_NOMINAL_SQL = text(f"""
    SELECT DISTINCT g.id, g.person_id
    FROM {CONTRIBUTIONS_AND_SOURCES}
    JOIN person_name_forms pnf
      ON pnf.name_form = ci.author_name_normalized AND {active_name_form("pnf")}
    WHERE g.resolution_mode IN {in_clause(NAME_MATCH_REASONS)} AND pnf.person_id <> g.person_id
""")
"""Contributions rattachées par le nom dont une contribution source a une forme de nom active d'une autre personne, avec leur personne."""


def mark_ambiguous_nominal(conn: Connection) -> int:
    """Marque pour la redécision de leur personne (`Queue.CONTRIBUTION_RESOLUTION`) les contributions rattachées par le nom dont la décision (`decide_contribution`) désigne une autre personne ou aucune. Renvoie le nombre de contributions marquées.

    Seules sont décidées les contributions dont une contribution source a une forme de nom d'une autre personne. La décision suit le rattachement : même index des personnes, mêmes rejets pour la publication.
    """
    person_of = {r.id: r.person_id for r in conn.execute(_CONTESTED_NOMINAL_SQL)}
    if not person_of:
        return 0
    index = load_index(conn, conflicting_reduced_first_names(conn))
    rejected = fetch_rejected_person_ids_by_publication(conn)
    changed = []
    for publication_id, by_contribution in load_contributions(conn, list(person_of)).items():
        rejected_here = rejected.get(publication_id, frozenset())
        for contribution_id, members in by_contribution.items():
            decision = decide_contribution(members, index, rejected_here)
            if (decision.outcome, decision.person_id) != (
                ContributionOutcome.MATCH,
                person_of[contribution_id],
            ):
                changed.append(contribution_id)
    return enqueue_ids(conn, Queue.CONTRIBUTION_RESOLUTION, changed)


def delete_unsupported_identifier_attributions(conn: Connection) -> int:
    """Supprime les attributions d'identifiant d'origine `auto` et en attente, absentes des contributions sources des contributions de leur personne. Une contribution source neutralisant l'identifiant compte comme sans lui. Les attributions confirmées, authentifiées ou saisies à la main restent. Renvoie le nombre d'attributions supprimées."""
    # La sous-requête latérale part des contributions de chaque personne. Un `NOT EXISTS`, décorrélé par le planificateur, joint toutes les contributions rattachées à une personne.
    return conn.execute(
        text(f"""
            DELETE FROM person_identifiers
            WHERE id IN (
                SELECT pi.id
                FROM person_identifiers pi
                LEFT JOIN LATERAL (
                    SELECT 1 AS supported
                    FROM {CONTRIBUTIONS_AND_SOURCES}
                    WHERE g.person_id = pi.person_id
                      AND ci.identifiers ->> pi.id_type::text = pi.id_value
                      AND NOT {identifier_neutralized("pi.id_type::text")}
                    LIMIT 1
                ) support ON TRUE
                WHERE pi.source = '{IdentifierOrigin.AUTO.value}'
                  AND pi.status = '{AttributionStatus.PENDING.value}'
                  AND support.supported IS NULL
            )
        """)
    ).rowcount


def delete_persons_out_of_perimeter(conn: Connection) -> int:
    """Supprime les personnes sans contribution du périmètre, sans fiche RH et sans décision humaine (`person_without_decision_sql`). Leurs contributions perdent d'abord leur personne. Leurs formes de nom et leurs identifiants sont supprimés avec elles. Renvoie le nombre de personnes supprimées."""
    deletable = f"""
        NOT EXISTS (
            SELECT 1 FROM contributions g_in
            WHERE g_in.person_id = p.id AND g_in.in_perimeter
        )
        AND NOT EXISTS (SELECT 1 FROM hr_records rh WHERE rh.person_id = p.id)
        AND {person_without_decision_sql("p")}
    """
    # La clé étrangère des contributions vide seulement `person_id` : le mode de résolution est vidé avec lui.
    conn.execute(
        text(f"""
            UPDATE contributions g SET {DETACHED_CONTRIBUTION}
            FROM persons p WHERE g.person_id = p.id AND {deletable}
        """)
    )
    return conn.execute(text(f"DELETE FROM persons p WHERE {deletable}")).rowcount


def purge(conn: Connection) -> dict[str, int]:
    """Marque pour la redécision les contributions rattachées par le nom dont la décision change, supprime les attributions d'identifiant sans appui, puis les personnes sans contribution du périmètre.

    Renvoie les compteurs `{ambiguous_marked, deleted_attributions, deleted_persons}`. L'appelant commite.
    """
    return {
        "ambiguous_marked": mark_ambiguous_nominal(conn),
        "deleted_attributions": delete_unsupported_identifier_attributions(conn),
        "deleted_persons": delete_persons_out_of_perimeter(conn),
    }
