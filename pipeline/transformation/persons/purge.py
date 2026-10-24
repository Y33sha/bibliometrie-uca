"""Purge de la phase personnes : re-orphelinage des groupes à forme de nom ambiguë, suppression des attributions d'identifiant sans appui, puis suppression des personnes sans contribution du périmètre.

La purge tourne après `populate_person_name_forms`, qui régénère les formes dérivées du nom des personnes. Une forme réduite (« j martin ») devient ambiguë quand elle désigne à la fois une personne au prénom réduit et une personne au prénom plein. Les groupes rattachés par cette forme perdent leur personne. La personne réduite, sans autre contribution du périmètre, est supprimée avec ses formes de nom : la forme réduite redevient univoque. Le groupe libéré rejoint la personne au prénom plein au run suivant.

La purge voit l'ambiguïté née des créations du run courant. La convergence se fait donc en deux runs.
"""

from sqlalchemy import Connection, text

from domain.persons.group_matching import NAME_MATCH_REASONS
from domain.persons.identifiers import (
    AttributionStatus,
    IdentifierOrigin,
)
from infrastructure.repositories.person_repository import person_without_decision_sql
from infrastructure.sql_fragments import (
    GROUP_MEMBERS,
    active_name_form,
    identifier_neutralized,
    in_clause,
    publication_rejected_for,
)


def reorphan_ambiguous_nominal(conn: Connection) -> int:
    """Un groupe rattaché par le nom (`NAME_MATCH_REASONS`) dont un membre a une forme de nom qui désigne au moins deux personnes (formes actives, `active_name_form`) perd sa personne. Le décompte écarte les personnes rejetées pour la publication du groupe, comme la résolution : un rejet qui laisse un seul candidat rend la forme univoque pour ce groupe. Rend le nombre de groupes re-orphelinés."""
    # Les candidats (groupes nominaux à forme ambiguë) sont matérialisés d'abord : le décompte par publication se limite à eux.
    return conn.execute(
        text(f"""
            WITH candidates AS MATERIALIZED (
                SELECT DISTINCT g.id, g.publication_id, ci.author_name_normalized AS name_form
                FROM {GROUP_MEMBERS}
                WHERE g.resolution_mode IN {in_clause(NAME_MATCH_REASONS)}
                  AND ci.author_name_normalized IN (
                      SELECT name_form
                      FROM person_name_forms
                      WHERE {active_name_form("person_name_forms")}
                      GROUP BY name_form
                      HAVING count(DISTINCT person_id) >= 2
                  )
            )
            UPDATE source_contribution_groups g
            SET person_id = NULL, resolution_mode = NULL
            WHERE g.id IN (
                SELECT c.id
                FROM candidates c
                WHERE (
                    SELECT count(DISTINCT pnf.person_id)
                    FROM person_name_forms pnf
                    WHERE pnf.name_form = c.name_form
                      AND {active_name_form("pnf")}
                      AND NOT {publication_rejected_for("c.publication_id", "pnf.person_id")}
                ) >= 2
            )
        """)
    ).rowcount


def delete_unsupported_identifier_attributions(conn: Connection) -> int:
    """Supprime les attributions d'identifiant posées par le pipeline (origine `auto`), encore en attente, qu'aucun membre des groupes de leur personne ne contient. Un membre qui neutralise l'identifiant compte comme sans lui. Les attributions confirmées, authentifiées ou saisies à la main restent. Rend le nombre d'attributions supprimées."""
    return conn.execute(
        text(f"""
            DELETE FROM person_identifiers pi
            WHERE pi.source = '{IdentifierOrigin.AUTO.value}'
              AND pi.status = '{AttributionStatus.PENDING.value}'
              AND NOT EXISTS (
                  SELECT 1
                  FROM {GROUP_MEMBERS}
                  WHERE g.person_id = pi.person_id
                    AND ci.identifiers ->> pi.id_type::text = pi.id_value
                    AND NOT {identifier_neutralized("pi.id_type::text")}
              )
        """)
    ).rowcount


def delete_persons_out_of_perimeter(conn: Connection) -> int:
    """Supprime les personnes sans groupe du périmètre, sans fiche RH et sans décision humaine (`person_without_decision_sql`). Leurs groupes perdent d'abord leur personne. La suppression emporte leurs formes de nom et leurs identifiants. Rend le nombre de personnes supprimées."""
    deletable = f"""
        NOT EXISTS (
            SELECT 1 FROM source_contribution_groups g_in
            WHERE g_in.person_id = p.id AND g_in.in_perimeter
        )
        AND NOT EXISTS (SELECT 1 FROM hr_records rh WHERE rh.person_id = p.id)
        AND {person_without_decision_sql("p")}
    """
    # La clé étrangère des groupes vide seulement `person_id` : le mode de résolution est vidé avec lui.
    conn.execute(
        text(f"""
            UPDATE source_contribution_groups g SET person_id = NULL, resolution_mode = NULL
            FROM persons p WHERE g.person_id = p.id AND {deletable}
        """)
    )
    return conn.execute(text(f"DELETE FROM persons p WHERE {deletable}")).rowcount


def purge(conn: Connection) -> dict[str, int]:
    """Re-orpheline les groupes nominaux à forme ambiguë, supprime les attributions d'identifiant sans appui, puis les personnes sans contribution du périmètre.

    Rend les compteurs `{reorphaned, deleted_attributions, deleted_persons}`. Le commit est laissé à l'appelant.
    """
    return {
        "reorphaned": reorphan_ambiguous_nominal(conn),
        "deleted_attributions": delete_unsupported_identifier_attributions(conn),
        "deleted_persons": delete_persons_out_of_perimeter(conn),
    }
