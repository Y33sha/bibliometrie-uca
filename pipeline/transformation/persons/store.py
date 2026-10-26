"""Accès aux personnes que plusieurs tâches de la phase `persons` partagent."""

from sqlalchemy import Connection, text

from domain.persons.identifiers import AttributionStatus
from domain.persons.matching import IdentifiedPerson, Namesake
from domain.persons.name_forms import CANONICAL_NAME_FORM_SOURCE
from infrastructure.sql_fragments import REJECTED_PAIRS, active_name_form


def fetch_namesakes(conn: Connection) -> list[Namesake]:
    """Les personnes non exclues, avec leur nom et prénom tels que saisis — matière du rattachement par initiales compatibles."""
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
    """Le nom normalisé de la personne ciblée accompagne le `person_id` : la décision d'une contribution corrobore le match identifiant par le nom (`decide_match_by_identifier`), et refuse l'identifiant d'une contribution source étrangère."""
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
    """Agrégation par `name_form` sur la table dénormalisée `(name_form, person_id, sources[], status)` : un dict trié par `person_id` croissant pour stabilité. Les liens `status = 'rejected'` sont exclus : une forme de nom rejetée pour une personne reste écartée du matching par nom (verrou de non-retour). Une forme dérivée du nom de la personne reste toujours active."""
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
    """Sert à la corroboration du matching par identifiant : quand un identifiant résout vers une personne, le verdict du couple (forme de la contribution source, personne) tranche sans test de compatibilité de nom — `confirmed` corrobore, `rejected` refuse ; en l'absence de verdict, on retombe sur la comparaison par tokens.

    Le verdict combine le statut admin et la provenance de la forme : une forme dérivée du nom de la personne (`'persons' ∈ sources`) corrobore toujours ; sinon un rejet admin refuse et une confirmation admin (`status = 'confirmed'`) corrobore. Les formes seulement `pending` et non dérivées du nom sont omises.
    """
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
    """Garde de matching : une paire `(publication, personne)` rejetée n'est jamais re-rattachée. Une publication est rejetée pour une personne dès qu'un de ses enregistrements sources l'est. Le caller élimine ces personnes des candidats (cf. `domain.persons.contribution_matching.decide_contribution`)."""
    rows = conn.execute(
        text(f"""
            SELECT publication_id, array_agg(DISTINCT person_id) AS person_ids
            FROM ({REJECTED_PAIRS}) rp
            WHERE publication_id IS NOT NULL
            GROUP BY publication_id
        """)
    ).all()
    return {r.publication_id: frozenset(r.person_ids) for r in rows}
