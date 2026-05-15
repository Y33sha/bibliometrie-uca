"""
Peuplement de person_name_forms à partir des sources existantes.

Mode incrémental : à chaque run, recalcule l'ensemble des formes
attendues depuis les sources (persons + source_authorships rattachées),
puis synchronise la table par diff (insert/update/delete).

Sources :
1. persons.last_name + persons.first_name (source: 'persons') —
   inclut les ``rejected = TRUE`` pour préserver l'ancre de matching
   des entités douteuses.
2. source_authorships.author_name_normalized (toutes sources biblio).

La colonne de vérité est `persons jsonb` au format ``{ "<pid>":
["src1", ...], ... }`` — l'orchestrateur agrège les triplets
``(name_form, person_id, source)`` en dict via
`domain.persons.name_forms.add_person_source`, puis compare au dict
stocké en base (égalité de dict) pour décider insert/update/delete.

Une forme dans la table mais absente de la recalculation est
supprimée — par construction, plus aucune source actuelle ne la
soutient.

L'orchestrateur dépend du port `NameFormsQueries`. Le point d'entrée CLI
est dans `interfaces/cli/pipeline/populate_person_name_forms.py`.
"""

import logging

from sqlalchemy import Connection

from application.ports.pipeline.name_forms import NameFormsQueries
from domain.persons.name_forms import (
    PersonsDict,
    add_person_source,
    compute_person_name_forms,
)

BATCH_SIZE = 5000


def populate(conn: Connection, queries: NameFormsQueries, logger: logging.Logger) -> None:
    triples: list[tuple[str, int, str]] = []

    logger.info("Source 1 : persons (prénom nom + nom prénom)")
    for r in queries.fetch_persons_names(conn):
        fn = (r["first_name"] or "").strip()
        ln = r["last_name"].strip()
        for form in compute_person_name_forms(ln, fn):
            triples.append((form, r["id"], "persons"))

    logger.info("Source 2 : source_authorships.author_name_normalized (toutes sources)")
    source_forms = queries.fetch_source_authorship_name_forms(conn)
    logger.info(
        f"  {len(triples)} triplets persons + {len(source_forms)} formes source_authorships"
    )

    logger.info("Normalisation des formes persons...")
    queries.create_temp_raw_forms_table(conn)
    batch: list[dict[str, object]] = []
    for raw, pid, src in triples:
        batch.append({"raw_text": raw.strip(), "person_id": pid, "source": src})
        if len(batch) >= BATCH_SIZE:
            queries.insert_raw_forms_batch(conn, batch)
            batch = []
    if batch:
        queries.insert_raw_forms_batch(conn, batch)

    normalized_persons_triples = queries.fetch_normalized_forms_from_temp(conn)
    queries.drop_temp_raw_forms_table(conn)

    expected_forms: dict[str, PersonsDict] = {}
    for r in normalized_persons_triples:
        nf = r["name_form"]
        if not nf:
            continue
        expected_forms[nf] = add_person_source(
            expected_forms.get(nf, {}), r["person_id"], r["source"]
        )
    for r in source_forms:
        nf = r["name_form"]
        expected_forms[nf] = add_person_source(
            expected_forms.get(nf, {}), r["person_id"], r["source"]
        )

    logger.info(f"  {len(expected_forms)} formes distinctes après fusion")

    existing = {r["name_form"]: r for r in queries.fetch_existing_name_forms(conn)}
    logger.info(f"  {len(existing)} formes existantes en base")

    inserted = 0
    updated = 0
    deleted = 0

    for nf, persons in expected_forms.items():
        if nf in existing:
            old = existing[nf]
            if persons != (old["persons"] or {}):
                queries.update_name_form(conn, old["id"], persons)
                updated += 1
        else:
            queries.insert_name_form(conn, nf, persons)
            inserted += 1

    for nf, old in existing.items():
        if nf not in expected_forms:
            queries.delete_name_form(conn, old["id"])
            deleted += 1

    conn.commit()

    logger.info(f"Terminé : {inserted} ajoutées, {updated} mises à jour, {deleted} supprimées")
