"""
Peuplement de person_name_forms à partir des sources existantes.

Mode incrémental :
- Recalcule les formes depuis les sources (persons + source_authorships)
- Met à jour les formes existantes (person_ids, sources)
- Ajoute les nouvelles formes
- Supprime les formes obsolètes UNIQUEMENT si elles n'ont que des sources
  bibliographiques (hal, openalex, wos). Les formes avec source 'persons'
  ou 'manual' sont préservées.

Sources :
1. persons.last_name + persons.first_name (source: 'persons')
2. source_authorships.author_name_normalized (toutes sources)

Le SQL est isolé dans `infrastructure/db/queries/name_forms.py`.
"""

import os
from typing import Any

from application.persons import compute_person_name_forms
from domain.sources import BIBLIO_SOURCES_SET as BIBLIO_SOURCES
from infrastructure.db.connection import get_connection
from infrastructure.db.queries.name_forms import (
    create_temp_raw_forms_table,
    delete_name_form,
    drop_temp_raw_forms_table,
    fetch_active_persons_names,
    fetch_existing_name_forms,
    fetch_normalized_forms_from_temp,
    fetch_source_authorship_name_forms,
    insert_name_form_with_merge,
    insert_raw_forms_batch,
    update_name_form,
)
from infrastructure.log import setup_logger

log = setup_logger("populate_person_name_forms", os.path.join(os.path.dirname(__file__), "logs"))


BATCH_SIZE = 5000


def populate(conn: Any) -> Any:
    cur = conn.cursor()

    triples = []

    log.info("Source 1 : persons (prénom nom + nom prénom)")
    for r in fetch_active_persons_names(cur):
        fn = (r["first_name"] or "").strip()
        ln = r["last_name"].strip()
        for form in compute_person_name_forms(ln, fn):
            triples.append((form, r["id"], "persons"))

    log.info("Source 2 : source_authorships.author_name_normalized (toutes sources)")
    source_forms = fetch_source_authorship_name_forms(cur)
    log.info(f"  {len(triples)} triplets persons + {len(source_forms)} formes source_authorships")

    log.info("Normalisation des formes persons...")
    create_temp_raw_forms_table(cur)
    batch: list[tuple[str, int, str]] = []
    for raw, pid, src in triples:
        batch.append((raw.strip(), pid, src))
        if len(batch) >= BATCH_SIZE:
            insert_raw_forms_batch(cur, batch)
            batch = []
    if batch:
        insert_raw_forms_batch(cur, batch)

    new_forms = {r["name_form"]: r for r in fetch_normalized_forms_from_temp(cur) if r["name_form"]}
    drop_temp_raw_forms_table(cur)

    for r in source_forms:
        nf = r["name_form"]
        if nf in new_forms:
            pids = set(new_forms[nf]["person_ids"])
            pids.add(r["person_id"])
            new_forms[nf]["person_ids"] = sorted(pids)
            srcs = set(new_forms[nf]["sources"])
            srcs.add(r["source"])
            new_forms[nf]["sources"] = sorted(srcs)
        else:
            new_forms[nf] = {
                "name_form": nf,
                "person_ids": [r["person_id"]],
                "sources": [r["source"]],
            }

    log.info(f"  {len(new_forms)} formes distinctes après fusion")

    existing = {r["name_form"]: r for r in fetch_existing_name_forms(cur)}
    log.info(f"  {len(existing)} formes existantes en base")

    inserted = 0
    updated = 0
    deleted = 0
    preserved = 0

    for nf, data in new_forms.items():
        if nf in existing:
            old = existing[nf]
            if set(data["person_ids"]) != set(old["person_ids"]) or set(data["sources"]) != set(
                old["sources"] or []
            ):
                update_name_form(cur, old["id"], data["person_ids"], data["sources"])
                updated += 1
        else:
            insert_name_form_with_merge(cur, nf, data["person_ids"], data["sources"])
            inserted += 1

    for nf, old in existing.items():
        if nf not in new_forms:
            old_sources = set(old["sources"] or [])
            if not old_sources or old_sources <= BIBLIO_SOURCES:
                delete_name_form(cur, old["id"])
                deleted += 1
            else:
                preserved += 1

    conn.commit()

    log.info(
        f"Terminé : {inserted} ajoutées, {updated} mises à jour, "
        f"{deleted} supprimées, {preserved} préservées"
    )


if __name__ == "__main__":
    conn = get_connection()
    try:
        populate(conn)
    finally:
        conn.close()
