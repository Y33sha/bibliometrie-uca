"""Peuplement de `person_name_forms` à partir des sources existantes.

Mode incrémental : à chaque run, recalcule l'ensemble des couples attendus `(name_form, person_id, sources)` depuis les sources (personnes et membres de leurs groupes), puis synchronise la table par diff (insert/update/delete).

Sources :
1. `persons.last_name` + `persons.first_name` (source: `'persons'`) — inclut les personnes exclues, qui restent des ancres du matching.
2. le nom normalisé des informations du contributeur des membres des groupes rattachés à la personne (`contributor_information.author_name_normalized`, toutes sources biblio).

L'orchestrateur produit les formes "persons" en Python via `compute_person_name_forms` (variantes prénom/nom/initiales) et les charge dans la table temp `_raw_forms`. La fusion et la synchronisation se font ensuite côté SQL via `sync_from_raw_forms` (GROUP BY (name_form, person_id), agrégation des sources, diff INSERT/UPDATE/DELETE).
"""

from typing import NamedTuple, TypedDict

from sqlalchemy import Connection, bindparam, text

from domain.persons.identifiers import AttributionStatus
from domain.persons.name_forms import CANONICAL_NAME_FORM_SOURCE, compute_person_name_forms
from infrastructure.db.jsonb import Jsonb
from infrastructure.sql_fragments import GROUP_MEMBERS


class PersonNameRow(NamedTuple):
    """Projection `persons` consommée par `populate_person_name_forms` : id + parts du nom (trimmées en SQL)."""

    id: int
    first_name: str | None
    last_name: str


class RawFormBatchItem(TypedDict):
    """Ligne du batch vers la table temp `_raw_forms` : forme de nom normalisée."""

    name_form: str
    person_id: int
    source: str


class SyncCounts(NamedTuple):
    """Bilan d'une synchronisation de `person_name_forms`."""

    inserted: int
    updated: int
    deleted: int


def fetch_persons_names(conn: Connection) -> list[PersonNameRow]:
    """Inclut les personnes exclues : leurs name_forms restent dans `person_name_forms` comme ancres du matching, donc le pipeline ne les recrée pas à chaque run."""
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
    """Reçoit les triplets calculés en Python depuis `persons` (un par forme retournée par `compute_person_name_forms`, source `'persons'`). Les formes des membres des groupes sont lues directement par la query d'agrégation, sans transiter par cette table."""
    conn.execute(text("CREATE TEMP TABLE _raw_forms (name_form TEXT, person_id INT, source TEXT)"))


def insert_raw_forms_batch(conn: Connection, rows: list[RawFormBatchItem]) -> None:
    """Insert massif de formes de nom dans la table temporaire `_raw_forms`."""
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
    """Construit en table temp `_expected_pnf` l'état attendu agrégé par `(name_form, person_id)`, sources triées dédupliquées. Puis 3 statements de sync : DELETE des couples manquants, INSERT des couples absents (statut `pending`), UPDATE des `sources` qui ont changé.

    Le recompute respecte le `status` (validation du lien forme↔personne) : l'UPDATE touche seulement `sources`, laissant le `status` intact ; une ligne `confirmed`/`rejected` (verdict) survit à la purge, sauf une forme de source `'persons'` absente de l'état attendu — seule une édition du nom/prénom retire une forme canonique. L'appartenance au nom canonique se lit dans `sources` (`'persons'`), non dans le statut.
    """
    conn.execute(
        text(f"""
            CREATE TEMP TABLE _expected_pnf AS
            WITH all_forms AS (
                SELECT name_form, person_id, source
                FROM _raw_forms
                UNION
                SELECT ci.author_name_normalized AS name_form,
                       g.person_id, sc.source::text AS source
                FROM {GROUP_MEMBERS}
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

    # La purge retire les `pending` orphelins et les formes `'persons'` absentes de l'état attendu (édition du nom) ; les verdicts `confirmed`/`rejected` sur des formes non-canoniques (bibliographiques) survivent.
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

    # Toute forme insérée entre en `pending` ; seule une action admin tranche. L'appartenance au nom canonique se lit dans `sources` (`'persons'`).
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

    # Resynchronise les seules `sources` ; le statut (verdict admin ou `pending`) est préservé.
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
