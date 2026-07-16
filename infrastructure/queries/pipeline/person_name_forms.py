"""Query service : SQL du peuplement de `person_name_forms`.

Appelé par `application/pipeline/persons/populate_person_name_forms.py`.
Collecte les formes brutes (table `persons` + `source_authorships`),
passe par une table temporaire pour la normalisation SQL via
`normalize_name_form()`, puis synchronise `person_name_forms` par
agrégation `GROUP BY (name_form, person_id)` + diff INSERT/UPDATE/DELETE.

Modèle de table cible : `(name_form, person_id, sources text[])` avec
PK composite — pas de JSONB, pas d'`id` de row. La fusion par couple
est faite en SQL (`array_agg DISTINCT`), pas en Python.
"""

from sqlalchemy import Connection, text

from application.ports.pipeline.person_name_forms import (
    PersonNameFormsQueries,
    PersonNameRow,
    RawFormBatchItem,
)


def fetch_persons_names(conn: Connection) -> list[PersonNameRow]:
    """`(id, first_name, last_name)` de toutes les personnes avec un nom.

    Inclut les `rejected = TRUE` : leurs name_forms doivent rester
    présentes dans `person_name_forms` pour servir d'ancre au matching
    et empêcher la re-création en boucle des entités douteuses
    (artefacts de parsing source, noms d'organisations, etc.) à chaque
    run pipeline.
    """
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
    """Crée la table temporaire `_raw_forms(raw_text, person_id, source)`.

    Reçoit les triplets calculés en Python depuis `persons` (un par
    forme retournée par `compute_person_name_forms`, source `'persons'`).
    Les formes issues de `source_authorships` sont lues directement par
    la query d'agrégation, sans transiter par cette table.
    """
    conn.execute(text("CREATE TEMP TABLE _raw_forms (raw_text TEXT, person_id INT, source TEXT)"))


def insert_raw_forms_batch(conn: Connection, rows: list[RawFormBatchItem]) -> None:
    """Insert par batch dans la table temporaire `_raw_forms`."""
    if not rows:
        return
    conn.execute(
        text("INSERT INTO _raw_forms VALUES (:raw_text, :person_id, :source)"),
        rows,
    )


def drop_temp_raw_forms_table(conn: Connection) -> None:
    conn.execute(text("DROP TABLE _raw_forms"))


def sync_from_raw_forms(conn: Connection) -> tuple[int, int, int]:
    """Agrège `_raw_forms` ∪ `source_authorships` et synchronise `person_name_forms`.

    Construit en table temp `_expected_pnf` l'état attendu agrégé par
    `(name_form, person_id)` avec sources triées dédupliquées. Puis 3
    statements de sync :
      1. DELETE des couples manquants.
      2. INSERT des couples nouveaux.
      3. UPDATE des `sources` qui ont changé.

    Le recompute respecte le `status` (validation du lien forme↔personne) :

    - il ne **modifie jamais** le `status` d'une ligne existante (l'UPDATE ne touche
      que `sources`) ;
    - il ne **supprime jamais** une ligne `confirmed`/`rejected` (verdict), sauf une
      forme de source `'persons'` devenue obsolète — seule une édition du nom/prénom
      de la personne peut faire disparaître ses formes canoniques ;
    - une ligne **nouvelle** est insérée `confirmed` si elle dérive du nom/prénom
      (source `'persons'`, forme canonique de la personne), `pending` sinon.

    Retourne `(inserted, updated, deleted)`.
    """
    conn.execute(
        text("""
            CREATE TEMP TABLE _expected_pnf AS
            WITH all_forms AS (
                SELECT normalize_name_form(raw_text) AS name_form,
                       person_id, source
                FROM _raw_forms
                WHERE trim(raw_text) != ''
                UNION
                SELECT aik.author_name_normalized AS name_form,
                       sa.person_id, sa.source::text AS source
                FROM source_authorships sa
                JOIN author_identifying_keys aik ON aik.id = sa.identity_id
                WHERE sa.person_id IS NOT NULL
                  AND aik.author_name_normalized IS NOT NULL
                  AND aik.author_name_normalized != ''
            )
            SELECT name_form, person_id,
                   array_agg(DISTINCT source ORDER BY source) AS sources
            FROM all_forms
            WHERE name_form != ''
            GROUP BY name_form, person_id
        """)
    )
    conn.execute(text("CREATE INDEX ON _expected_pnf (name_form, person_id)"))

    # On ne supprime que les `pending` orphelins et les formes `'persons'` devenues
    # obsolètes (édition du nom). Les verdicts `confirmed`/`rejected` sur des formes
    # non-canoniques (bibliographiques) sont préservés même s'ils ne sont plus dérivés.
    deleted = conn.execute(
        text("""
            DELETE FROM person_name_forms p
            WHERE NOT EXISTS (
                SELECT 1 FROM _expected_pnf e
                WHERE e.name_form = p.name_form AND e.person_id = p.person_id
            )
            AND (p.status = 'pending' OR 'persons' = ANY(p.sources))
        """)
    ).rowcount

    # Une forme nouvelle entre en `pending` : seule une action admin la confirme ou
    # la rejette. L'appartenance d'une forme au nom canonique se lit dans `sources`
    # (`'persons'`), pas dans le statut.
    inserted = conn.execute(
        text("""
            INSERT INTO person_name_forms (name_form, person_id, sources, status)
            SELECT e.name_form, e.person_id, e.sources, 'pending'::identifier_status
            FROM _expected_pnf e
            WHERE NOT EXISTS (
                SELECT 1 FROM person_name_forms p
                WHERE p.name_form = e.name_form AND p.person_id = e.person_id
            )
        """)
    ).rowcount

    # Resynchronise les seules `sources` ; le statut (verdict admin ou `pending`) est
    # préservé.
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
    return inserted, updated, deleted


class PgPersonNameFormsQueries(PersonNameFormsQueries):
    """Adapter PostgreSQL pour `application.ports.pipeline.person_name_forms.PersonNameFormsQueries`."""

    def fetch_persons_names(self, conn: Connection) -> list[PersonNameRow]:
        return fetch_persons_names(conn)

    def create_temp_raw_forms_table(self, conn: Connection) -> None:
        create_temp_raw_forms_table(conn)

    def insert_raw_forms_batch(self, conn: Connection, rows: list[RawFormBatchItem]) -> None:
        insert_raw_forms_batch(conn, rows)

    def drop_temp_raw_forms_table(self, conn: Connection) -> None:
        drop_temp_raw_forms_table(conn)

    def sync_from_raw_forms(self, conn: Connection) -> tuple[int, int, int]:
        return sync_from_raw_forms(conn)
