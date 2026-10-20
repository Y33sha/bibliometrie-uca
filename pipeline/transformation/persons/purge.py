"""Purge de la phase personnes : re-orphelinage des formes de nom devenues ambiguës, suppression des attributions d'identifiant sans appui, puis suppression des personnes vidées.

Tourne **après `populate_person_name_forms`**, qui régénère les formes canoniques : c'est seulement là qu'une forme réduite (« j martin »), partagée par une personne réduite et par la forme pleine dont elle est l'initiale, devient ambiguë. Le re-orphelinage détache alors les signatures nominales à forme ambiguë, non épinglées ; le GC supprime les personnes ainsi vidées (hors référentiel RH), ce qui retire leurs formes canoniques et désambiguïse. La signature libérée rejoint la forme pleine au `match` du run suivant.

Placée après le peuplement, la purge voit l'ambiguïté née des créations du run courant : la convergence se fait en deux runs.

Elle supprime aussi les attributions d'identifiant d'origine automatique, en attente, qu'aucune signature de leur personne ne porte : celles d'un rattachement défait pendant le passage.
"""

from sqlalchemy import Connection, text

from domain.persons.identifiers import (
    AttributionStatus,
    IdentifierOrigin,
)
from domain.persons.matching import (
    ResolutionMode,
)
from infrastructure.repositories.person_repository import person_without_decision_sql
from infrastructure.sql_fragments import (
    DETACHED_SOURCE_CONTRIBUTION,
    active_name_form,
    identifier_neutralized,
    pinned,
    publication_rejected_for,
)


def reorphan_ambiguous_nominal(conn: Connection) -> int:
    """Une signature résolue par forme de nom (`resolution_mode = 'name'`), non épinglée par l'admin (`confirmed_source_contributions`), dont l'`author_name_normalized` désigne au moins deux personnes dans `person_name_forms` (hors `rejected`), repasse à NULL — `person_id` et mode. Le sur-regroupement (une forme réduite collée au seul candidat présent avant l'arrivée de l'homonyme qui la départage) se défait ainsi dès que l'homonyme coexiste, quel que soit l'ordre d'ingestion.

    Comme la cascade, le décompte écarte les personnes rejetées pour la publication de la signature (`rejected_contributions`) : un rejet qui laisse un seul candidat rend la forme univoque pour cette signature.
    """
    # Les candidates (nominales, non épinglées, à forme ambiguë) sont matérialisées d'abord : le
    # décompte par signature et la jointure vers la publication ne portent que sur elles.
    return conn.execute(
        text(f"""
            WITH candidates AS MATERIALIZED (
                SELECT sc.id, sc.source_record_id,
                       ci.author_name_normalized AS name_form
                FROM source_contributions sc
                JOIN contributor_information ci ON ci.id = sc.contributor_information_id
                WHERE sc.resolution_mode = '{ResolutionMode.NAME.value}'
                  AND NOT {pinned("sc.id")}
                  AND ci.author_name_normalized IN (
                      SELECT name_form
                      FROM person_name_forms
                      WHERE {active_name_form("person_name_forms")}
                      GROUP BY name_form
                      HAVING count(DISTINCT person_id) >= 2
                  )
            )
            UPDATE source_contributions sc
            SET {DETACHED_SOURCE_CONTRIBUTION}
            FROM candidates c
            JOIN source_records sr ON sr.id = c.source_record_id
            WHERE sc.id = c.id
              AND (
                  SELECT count(DISTINCT pnf.person_id)
                  FROM person_name_forms pnf
                  WHERE pnf.name_form = c.name_form
                    AND {active_name_form("pnf")}
                    AND NOT {publication_rejected_for("sr.publication_id", "pnf.person_id")}
              ) >= 2
        """)
    ).rowcount


def delete_empty_persons(conn: Connection) -> int:
    """Après le re-orphelinage, une personne purement nominale peut se retrouver sans aucune `source_contributions` — typiquement une forme réduite dont les signatures ont rejoint la forme pleine. La supprimer retire ses formes de nom canoniques (FK `CASCADE`), ce qui désambiguïse la forme réduite et laisse les orphelines se re-attacher au run suivant.

    Une personne vide est conservée si elle a une notice RH, ou une décision humaine (`person_without_decision_sql`). Une personne rejetée reste ainsi un candidat connu, écarté par son rejet, au lieu d'être recréée à l'identique par la cascade.
    """
    return conn.execute(
        text(f"""
            DELETE FROM persons p
            WHERE NOT EXISTS (SELECT 1 FROM source_contributions sc WHERE sc.person_id = p.id)
              AND NOT EXISTS (SELECT 1 FROM hr_records rh WHERE rh.person_id = p.id)
              AND {person_without_decision_sql("p")}
        """)
    ).rowcount


def delete_unsupported_identifier_attributions(conn: Connection) -> int:
    """Supprime les attributions d'identifiant posées par le pipeline (origine `auto`), encore en attente, qu'aucune signature de leur personne ne porte. Une signature qui neutralise l'identifiant ne le porte pas. Les attributions confirmées, authentifiées ou saisies à la main restent."""
    return conn.execute(
        text(f"""
            DELETE FROM person_identifiers pi
            WHERE pi.source = '{IdentifierOrigin.AUTO.value}'
              AND pi.status = '{AttributionStatus.PENDING.value}'
              AND NOT EXISTS (
                  SELECT 1
                  FROM source_contributions sc
                  JOIN contributor_information ci ON ci.id = sc.contributor_information_id
                  WHERE sc.person_id = pi.person_id
                    AND ci.identifiers ->> pi.id_type::text = pi.id_value
                    AND NOT {identifier_neutralized("pi.id_type::text")}
              )
        """)
    ).rowcount


def purge(conn: Connection) -> dict[str, int]:
    """Re-orpheline les signatures nominales à forme ambiguë, supprime les attributions d'identifiant sans appui, puis les personnes vidées.

    Retourne les compteurs `{reorphaned, deleted_attributions, deleted_persons}`. Le commit est laissé au caller.
    """
    reorphaned = reorphan_ambiguous_nominal(conn)
    deleted_attributions = delete_unsupported_identifier_attributions(conn)
    deleted_persons = delete_empty_persons(conn)

    return {
        "reorphaned": reorphaned,
        "deleted_attributions": deleted_attributions,
        "deleted_persons": deleted_persons,
    }
