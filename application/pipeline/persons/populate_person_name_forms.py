"""Peuplement de `person_name_forms` à partir des sources existantes.

Mode incrémental : à chaque run, recalcule l'ensemble des couples attendus `(name_form, person_id, sources)` depuis les sources (persons + source_authorships), puis synchronise la table par diff (insert/update/delete).

Sources :
1. `persons.last_name` + `persons.first_name` (source: `'persons'`) — inclut les `rejected = TRUE` pour préserver l'ancre de matching des entités douteuses.
2. le nom normalisé de l'identité des signatures (`author_identifying_keys.author_name_normalized`, toutes sources biblio).

L'orchestrateur produit les formes "persons" en Python via `compute_person_name_forms` (variantes prénom/nom/initiales) et les charge dans la table temp `_raw_forms`. La fusion et la synchronisation se font ensuite côté SQL via `sync_from_raw_forms` (GROUP BY (name_form, person_id), agrégation des sources, diff INSERT/UPDATE/DELETE).

L'orchestrateur dépend du port `NameFormsQueries` ; il est appelé par `run_pipeline`.
"""

import logging

from sqlalchemy import Connection

from application.ports.pipeline.name_forms import NameFormsQueries, RawFormBatchItem
from domain.persons.name_forms import compute_person_name_forms

BATCH_SIZE = 5000


def populate(conn: Connection, queries: NameFormsQueries, logger: logging.Logger) -> None:
    logger.info("▶ régénération des formes de nom")
    queries.create_temp_raw_forms_table(conn)
    batch: list[RawFormBatchItem] = []
    n_persons_rows = 0
    for r in queries.fetch_persons_names(conn):
        fn = (r.first_name or "").strip()
        ln = r.last_name.strip()
        for form in compute_person_name_forms(ln, fn):
            batch.append({"raw_text": form, "person_id": r.id, "source": "persons"})
            n_persons_rows += 1
            if len(batch) >= BATCH_SIZE:
                queries.insert_raw_forms_batch(conn, batch)
                batch = []
    if batch:
        queries.insert_raw_forms_batch(conn, batch)
    logger.info("  %d formes calculées depuis les personnes", n_persons_rows)

    logger.info("  synchronisation avec les formes issues des signatures...")
    inserted, updated, deleted = queries.sync_from_raw_forms(conn)
    queries.drop_temp_raw_forms_table(conn)

    logger.info(
        "  → %d ajoutées, %d mises à jour, %d supprimées",
        inserted,
        updated,
        deleted,
    )
