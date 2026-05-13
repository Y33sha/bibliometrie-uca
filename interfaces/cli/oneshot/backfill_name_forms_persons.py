# STATUS: oneshot (2026-05-13)
"""
Backfill de `person_name_forms.persons` (JSONB) depuis le modèle ancien.

Phase 2 du chantier `DATA_person-name-forms-normalisation.md` — quatre
étapes additives et idempotentes, à enchaîner dans l'ordre :

1. `keys` : initialise `persons` à ``{<pid>: []}`` pour chaque `pid` de
   `person_ids[]`. Skip les rows déjà initialisées (``persons IS NOT NULL``).
   Aucune source posée à ce stade — c'est juste l'armature des clés.
2. `persons` : ajoute ``"persons"`` à l'entrée ``(name_form, pid)`` pour
   chaque forme calculée via ``compute_person_name_forms`` depuis la
   table `persons` (inclut ``rejected = TRUE`` — cf. justification dans
   `fetch_persons_names`).
3. `authorships` : ajoute ``sa.source`` à l'entrée
   ``(author_name_normalized, sa.person_id)`` pour chaque
   `source_authorships` non exclus, person_id rattaché, name_form non
   nul.
4. `cleanup` : retire les clés `person_id` dont le tableau `sources`
   est resté vide après les étapes précédentes (orphelines du modèle
   ancien : présentes dans `person_ids[]` mais sans justification dans
   les sources actuelles). Supprime la row si `persons` devient ``'{}'``.

Toutes les étapes utilisent ``persons := persons || <new_keys>`` côté
SQL : la concaténation JSONB merge les clés (RHS gagne), donc les
sources déjà présentes pour les clés non touchées sont préservées et
les sources des clés touchées sont mergées via array_agg DISTINCT
(stabilité d'ordre).

Apply par défaut. ``--dry-run`` pour rollback final.

Usage :
    python -m interfaces.cli.oneshot.backfill_name_forms_persons --step keys
    python -m interfaces.cli.oneshot.backfill_name_forms_persons --step persons
    python -m interfaces.cli.oneshot.backfill_name_forms_persons --step authorships
    python -m interfaces.cli.oneshot.backfill_name_forms_persons --step cleanup
    python -m interfaces.cli.oneshot.backfill_name_forms_persons --step all
    python -m interfaces.cli.oneshot.backfill_name_forms_persons --step all --dry-run
"""

import argparse
import os
import sys

from sqlalchemy import Connection, text

from domain.persons.name_forms import compute_person_name_forms
from infrastructure.db.engine import get_sync_engine
from infrastructure.log import setup_logger

log = setup_logger("backfill_name_forms_persons", os.path.dirname(__file__))

STEPS = ("keys", "persons", "authorships", "cleanup")
BATCH_SIZE = 5000


def step_keys(conn: Connection) -> None:
    """Initialise `persons` à `{<pid>: []}` pour chaque pid de `person_ids[]`.

    Skip les rows déjà initialisées (idempotent sur re-run).
    """
    res = conn.execute(
        text("""
            UPDATE person_name_forms
            SET persons = (
                    SELECT jsonb_object_agg(pid::text, '[]'::jsonb)
                    FROM unnest(person_ids) AS pid
                ),
                updated_at = now()
            WHERE persons IS NULL
              AND array_length(person_ids, 1) > 0
        """)
    )
    log.info("keys : %d rows initialisées", res.rowcount)


def step_persons(conn: Connection) -> None:
    """Ajoute la source 'persons' depuis la table `persons`.

    Génère les formes brutes en Python via ``compute_person_name_forms``
    puis les normalise côté SQL via ``normalize_name_form()`` pour
    s'aligner sur le format stocké dans `person_name_forms.name_form`.
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
    log.info("persons : %d personnes à traiter", len(rows))

    triples: list[tuple[str, int]] = []
    for r in rows:
        ln = (r.last_name or "").strip()
        fn = (r.first_name or "").strip()
        for form in compute_person_name_forms(ln, fn):
            triples.append((form, r.id))
    log.info("persons : %d (forme, pid) générés", len(triples))

    conn.execute(text("DROP TABLE IF EXISTS _bf_persons"))
    conn.execute(
        text("CREATE TEMP TABLE _bf_persons (raw_text TEXT, person_id INT) ON COMMIT DROP")
    )
    for i in range(0, len(triples), BATCH_SIZE):
        batch = triples[i : i + BATCH_SIZE]
        conn.execute(
            text("INSERT INTO _bf_persons VALUES (:rt, :pid)"),
            [{"rt": rt, "pid": pid} for rt, pid in batch],
        )

    res = conn.execute(
        text("""
            WITH expected AS (
                SELECT DISTINCT
                    normalize_name_form(raw_text) AS name_form,
                    person_id::text AS pid_text
                FROM _bf_persons
                WHERE trim(raw_text) != ''
            ),
            merged_per_key AS (
                SELECT pnf.id,
                       e.pid_text,
                       (SELECT array_agg(DISTINCT s ORDER BY s)
                        FROM unnest(
                            COALESCE(
                                ARRAY(SELECT jsonb_array_elements_text(pnf.persons->e.pid_text)),
                                '{}'::text[]
                            ) || ARRAY['persons']::text[]
                        ) AS s) AS final_sources
                FROM person_name_forms pnf
                JOIN expected e ON e.name_form = pnf.name_form
            ),
            new_persons_per_row AS (
                SELECT id, jsonb_object_agg(pid_text, to_jsonb(final_sources)) AS new_keys
                FROM merged_per_key
                GROUP BY id
            )
            UPDATE person_name_forms pnf
            SET persons = COALESCE(pnf.persons, '{}'::jsonb) || np.new_keys,
                updated_at = now()
            FROM new_persons_per_row np
            WHERE pnf.id = np.id
        """)
    )
    log.info("persons : %d rows mises à jour", res.rowcount)


def step_authorships(conn: Connection) -> None:
    """Ajoute `sa.source` depuis `source_authorships` non exclus.

    Tout est déjà en base : pure SQL.
    """
    res = conn.execute(
        text("""
            WITH expected AS (
                SELECT sa.author_name_normalized AS name_form,
                       sa.person_id::text AS pid_text,
                       array_agg(DISTINCT sa.source::text) AS new_sources
                FROM source_authorships sa
                WHERE NOT sa.excluded
                  AND sa.person_id IS NOT NULL
                  AND sa.author_name_normalized IS NOT NULL
                  AND sa.author_name_normalized != ''
                GROUP BY sa.author_name_normalized, sa.person_id
            ),
            merged_per_key AS (
                SELECT pnf.id,
                       e.pid_text,
                       (SELECT array_agg(DISTINCT s ORDER BY s)
                        FROM unnest(
                            COALESCE(
                                ARRAY(SELECT jsonb_array_elements_text(pnf.persons->e.pid_text)),
                                '{}'::text[]
                            ) || e.new_sources
                        ) AS s) AS final_sources
                FROM person_name_forms pnf
                JOIN expected e ON e.name_form = pnf.name_form
            ),
            new_persons_per_row AS (
                SELECT id, jsonb_object_agg(pid_text, to_jsonb(final_sources)) AS new_keys
                FROM merged_per_key
                GROUP BY id
            )
            UPDATE person_name_forms pnf
            SET persons = COALESCE(pnf.persons, '{}'::jsonb) || np.new_keys,
                updated_at = now()
            FROM new_persons_per_row np
            WHERE pnf.id = np.id
        """)
    )
    log.info("authorships : %d rows mises à jour", res.rowcount)


def step_cleanup(conn: Connection) -> None:
    """Retire les clés `pid` aux sources vides ; supprime la row si vide."""
    res_filter = conn.execute(
        text("""
            WITH filtered AS (
                SELECT pnf.id,
                       COALESCE(
                           jsonb_object_agg(key, value)
                               FILTER (WHERE jsonb_array_length(value) > 0),
                           '{}'::jsonb
                       ) AS new_persons
                FROM person_name_forms pnf,
                     LATERAL jsonb_each(pnf.persons) AS j(key, value)
                WHERE pnf.persons IS NOT NULL
                GROUP BY pnf.id
            )
            UPDATE person_name_forms pnf
            SET persons = f.new_persons,
                updated_at = now()
            FROM filtered f
            WHERE pnf.id = f.id
              AND pnf.persons IS DISTINCT FROM f.new_persons
        """)
    )
    log.info("cleanup : %d rows nettoyées (clés vides retirées)", res_filter.rowcount)

    res_del = conn.execute(text("DELETE FROM person_name_forms WHERE persons = '{}'::jsonb"))
    log.info("cleanup : %d rows supprimées (persons vide)", res_del.rowcount)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--step",
        required=True,
        choices=[*STEPS, "all"],
        help="Étape à exécuter, ou 'all' pour les 4 dans l'ordre.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Rollback final (sinon commit). Apply par défaut.",
    )
    args = parser.parse_args()

    steps_to_run = list(STEPS) if args.step == "all" else [args.step]

    conn = get_sync_engine().connect()
    try:
        for step in steps_to_run:
            log.info("=== %s ===", step)
            if step == "keys":
                step_keys(conn)
            elif step == "persons":
                step_persons(conn)
            elif step == "authorships":
                step_authorships(conn)
            elif step == "cleanup":
                step_cleanup(conn)

        if args.dry_run:
            conn.rollback()
            log.info("[dry-run] rollback final, rien n'a été persisté.")
        else:
            conn.commit()
            log.info("commit OK.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
