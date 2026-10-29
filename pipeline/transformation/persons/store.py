"""Accès aux personnes que plusieurs tâches de la phase `persons` partagent."""

from sqlalchemy import Connection, text

from domain.persons.identifiers import AttributionStatus
from domain.persons.matching import IdentifiedPerson, Namesake
from domain.persons.name_forms import CANONICAL_NAME_FORM_SOURCE
from infrastructure.sql_fragments import REJECTED_PAIRS, active_name_form


def fetch_namesakes(conn: Connection) -> list[Namesake]:
    """Personnes non exclues, avec leur nom et prénom saisis, pour le rattachement par initiales compatibles."""
    rows = conn.execute(
        text("""
            SELECT id, last_name, COALESCE(first_name, '') AS first_name
            FROM persons
            WHERE exclusion IS NULL
            ORDER BY id
        """)
    ).all()
    return [Namesake(r.id, r.last_name, r.first_name) for r in rows]


def fetch_identifier_to_person_map(conn: Connection, id_type: str) -> dict[str, IdentifiedPerson]:
    """Personne de chaque valeur d'un type d'identifiant, attributions rejetées exclues, avec son nom normalisé : le rattachement par identifiant se corrobore par le nom (`decide_match_by_identifier`)."""
    rows = conn.execute(
        text(f"""
            SELECT pi.id_value, pi.person_id,
                   p.last_name_normalized AS ln, p.first_name_normalized AS fn
            FROM person_identifiers pi
            JOIN persons p ON p.id = pi.person_id
            WHERE pi.id_type = :id_type
              AND pi.status != '{AttributionStatus.REJECTED.value}'
        """),
        {"id_type": id_type},
    ).all()
    return {r.id_value: IdentifiedPerson(r.person_id, r.ln or "", r.fn or "") for r in rows}


def fetch_name_form_map(conn: Connection) -> dict[str, list[int]]:
    """Personnes de chaque forme de nom active, par `person_id` croissant. Une forme rejetée pour une personne est écartée ; une forme tirée du nom de la personne reste active."""
    rows = conn.execute(
        text(f"""
            SELECT name_form,
                   array_agg(person_id ORDER BY person_id) AS person_ids
            FROM person_name_forms
            WHERE {active_name_form("person_name_forms")}
            GROUP BY name_form
        """)
    ).all()
    return {r.name_form: r.person_ids for r in rows}


def fetch_name_form_status_map(conn: Connection) -> dict[tuple[str, int], str]:
    """Verdict de chaque couple (forme de nom, personne), qui corrobore (`confirmed`) ou refuse (`rejected`) un rattachement par identifiant sans comparer les noms. Une forme tirée du nom de la personne corrobore ; sinon, le statut de la forme décide. Les formes `pending` hors du nom de la personne sont omises."""
    rows = conn.execute(
        text(f"""
            SELECT name_form, person_id,
                   CASE WHEN '{CANONICAL_NAME_FORM_SOURCE}' = ANY(sources)
                        THEN '{AttributionStatus.CONFIRMED.value}'
                        WHEN status = '{AttributionStatus.REJECTED.value}'
                        THEN '{AttributionStatus.REJECTED.value}'
                        ELSE '{AttributionStatus.CONFIRMED.value}' END AS status
            FROM person_name_forms
            WHERE status = '{AttributionStatus.REJECTED.value}'
               OR status = '{AttributionStatus.CONFIRMED.value}'
               OR '{CANONICAL_NAME_FORM_SOURCE}' = ANY(sources)
        """)
    ).all()
    return {(r.name_form, r.person_id): r.status for r in rows}


def fetch_rejected_person_ids_by_publication(conn: Connection) -> dict[int, frozenset[int]]:
    """Personnes rejetées pour chaque publication, que la décision écarte des candidats (`decide_contribution`). Une publication est rejetée pour une personne dès qu'un de ses enregistrements sources l'est."""
    rows = conn.execute(
        text(f"""
            SELECT publication_id, array_agg(DISTINCT person_id) AS person_ids
            FROM ({REJECTED_PAIRS}) rp
            WHERE publication_id IS NOT NULL
            GROUP BY publication_id
        """)
    ).all()
    return {r.publication_id: frozenset(r.person_ids) for r in rows}
