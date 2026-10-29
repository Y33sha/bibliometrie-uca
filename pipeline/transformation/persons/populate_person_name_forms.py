"""Synchronisation de `person_name_forms` avec les formes attendues de chaque personne : celles de son nom (source `persons`), exclues comprises, et les noms des contributions sources de ses contributions.

Les formes du nom se calculent en Python (`compute_person_name_forms`) et passent par la table temporaire `_raw_forms`. La synchronisation se fait en SQL (`sync_from_raw_forms`).
"""

from typing import NamedTuple, TypedDict

from sqlalchemy import Connection, bindparam, text

from domain.persons.identifiers import AttributionStatus
from domain.persons.name_forms import CANONICAL_NAME_FORM_SOURCE, compute_person_name_forms
from infrastructure.db.jsonb import Jsonb
from infrastructure.sql_fragments import CONTRIBUTIONS_AND_SOURCES


class PersonNameRow(NamedTuple):
    """Nom et prénom d'une personne, sans les espaces qui les entourent."""

    id: int
    first_name: str | None
    last_name: str


class RawFormBatchItem(TypedDict):
    """Forme de nom à charger dans `_raw_forms`."""

    name_form: str
    person_id: int
    source: str


class SyncCounts(NamedTuple):
    """Bilan d'une synchronisation de `person_name_forms`."""

    inserted: int
    updated: int
    deleted: int


def fetch_persons_names(conn: Connection) -> list[PersonNameRow]:
    """Nom de chaque personne, exclues comprises : leurs formes de nom servent au matching, qui ne recrée donc pas ces personnes."""
    rows = conn.execute(
        text("""
            SELECT id,
                   trim(first_name) AS first_name,
                   trim(last_name) AS last_name
            FROM persons
            WHERE last_name IS NOT NULL AND last_name != ''
        """)
    ).all()
    return [PersonNameRow(id=r.id, first_name=r.first_name, last_name=r.last_name) for r in rows]


def create_temp_raw_forms_table(conn: Connection) -> None:
    """Crée la table temporaire `_raw_forms`, qui reçoit les formes du nom des personnes."""
    conn.execute(text("CREATE TEMP TABLE _raw_forms (name_form TEXT, person_id INT, source TEXT)"))


def insert_raw_forms_batch(conn: Connection, rows: list[RawFormBatchItem]) -> None:
    """Insère un lot de formes de nom dans `_raw_forms`."""
    if not rows:
        return
    conn.execute(
        text("""
            INSERT INTO _raw_forms (name_form, person_id, source)
            SELECT name_form, person_id, source
            FROM jsonb_to_recordset(:payload) AS t(name_form text, person_id int, source text)
        """).bindparams(bindparam("payload", type_=Jsonb)),
        {"payload": list(rows)},
    )


def drop_temp_raw_forms_table(conn: Connection) -> None:
    """Supprime la table temporaire `_raw_forms`."""
    conn.execute(text("DROP TABLE _raw_forms"))


def sync_from_raw_forms(conn: Connection) -> SyncCounts:
    """Synchronise `person_name_forms` avec l'état attendu, agrégé par `(name_form, person_id)` : suppression des couples absents, insertion des nouveaux en `pending`, mise à jour des `sources`. Le statut reste inchangé. Une forme `confirmed` ou `rejected` reste en base, sauf une forme du nom de la personne (source `persons`) qu'une modification du nom retire."""
    conn.execute(
        text(f"""
            CREATE TEMP TABLE _expected_pnf AS
            WITH all_forms AS (
                SELECT name_form, person_id, source
                FROM _raw_forms
                UNION
                SELECT ci.author_name_normalized AS name_form,
                       g.person_id, sc.source::text AS source
                FROM {CONTRIBUTIONS_AND_SOURCES}
                WHERE g.person_id IS NOT NULL
                  AND ci.author_name_normalized IS NOT NULL
                  AND ci.author_name_normalized != ''
            )
            SELECT name_form, person_id,
                   array_agg(DISTINCT source ORDER BY source) AS sources
            FROM all_forms
            WHERE name_form != ''
            GROUP BY name_form, person_id
        """)
    )
    conn.execute(text("CREATE INDEX ON _expected_pnf (name_form, person_id)"))

    # Seules les formes `pending` et les formes du nom de la personne absentes de l'état attendu sont supprimées.
    deleted = conn.execute(
        text(f"""
            DELETE FROM person_name_forms p
            WHERE NOT EXISTS (
                SELECT 1 FROM _expected_pnf e
                WHERE e.name_form = p.name_form AND e.person_id = p.person_id
            )
            AND (p.status = '{AttributionStatus.PENDING.value}'
                 OR '{CANONICAL_NAME_FORM_SOURCE}' = ANY(p.sources))
        """)
    ).rowcount

    # Une forme insérée est `pending` ; seule l'administration la tranche.
    inserted = conn.execute(
        text(f"""
            INSERT INTO person_name_forms (name_form, person_id, sources, status)
            SELECT e.name_form, e.person_id, e.sources,
                   '{AttributionStatus.PENDING.value}'::identifier_status
            FROM _expected_pnf e
            WHERE NOT EXISTS (
                SELECT 1 FROM person_name_forms p
                WHERE p.name_form = e.name_form AND p.person_id = e.person_id
            )
        """)
    ).rowcount

    # Seules les `sources` changent ; le statut reste.
    updated = conn.execute(
        text("""
            UPDATE person_name_forms p
            SET sources = e.sources
            FROM _expected_pnf e
            WHERE p.name_form = e.name_form AND p.person_id = e.person_id
              AND p.sources IS DISTINCT FROM e.sources
        """)
    ).rowcount

    conn.execute(text("DROP TABLE _expected_pnf"))
    return SyncCounts(inserted=inserted, updated=updated, deleted=deleted)


BATCH_SIZE = 5000


def populate(conn: Connection) -> SyncCounts:
    """Synchronise `person_name_forms` avec les formes attendues. Rend les formes insérées, modifiées et supprimées."""
    create_temp_raw_forms_table(conn)
    batch: list[RawFormBatchItem] = []
    for r in fetch_persons_names(conn):
        fn = (r.first_name or "").strip()
        ln = r.last_name.strip()
        for form in compute_person_name_forms(ln, fn):
            batch.append(
                {"name_form": form, "person_id": r.id, "source": CANONICAL_NAME_FORM_SOURCE}
            )
            if len(batch) >= BATCH_SIZE:
                insert_raw_forms_batch(conn, batch)
                batch = []
    if batch:
        insert_raw_forms_batch(conn, batch)

    counts = sync_from_raw_forms(conn)
    drop_temp_raw_forms_table(conn)
    return counts
