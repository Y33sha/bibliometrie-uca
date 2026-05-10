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

Une forme dans la table mais absente de la recalculation est
supprimée — par construction, plus aucune source actuelle ne la
soutient.

L'orchestrateur dépend du port `NameFormsQueries`. Le point d'entrée CLI
est dans `interfaces/cli/pipeline/populate_person_name_forms.py`.
"""

from typing import Any

from application.ports.name_forms import NameFormsQueries
from domain.names import compute_person_name_forms

BATCH_SIZE = 5000


def populate(conn: Any, queries: NameFormsQueries, logger: Any) -> None:
    triples = []

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
    batch: list[dict[str, Any]] = []
    for raw, pid, src in triples:
        batch.append({"raw_text": raw.strip(), "person_id": pid, "source": src})
        if len(batch) >= BATCH_SIZE:
            queries.insert_raw_forms_batch(conn, batch)
            batch = []
    if batch:
        queries.insert_raw_forms_batch(conn, batch)

    expected_forms = {
        r["name_form"]: r for r in queries.fetch_normalized_forms_from_temp(conn) if r["name_form"]
    }
    queries.drop_temp_raw_forms_table(conn)

    for r in source_forms:
        nf = r["name_form"]
        if nf in expected_forms:
            pids = set(expected_forms[nf]["person_ids"])
            pids.add(r["person_id"])
            expected_forms[nf]["person_ids"] = sorted(pids)
            srcs = set(expected_forms[nf]["sources"])
            srcs.add(r["source"])
            expected_forms[nf]["sources"] = sorted(srcs)
        else:
            expected_forms[nf] = {
                "name_form": nf,
                "person_ids": [r["person_id"]],
                "sources": [r["source"]],
            }

    logger.info(f"  {len(expected_forms)} formes distinctes après fusion")

    existing = {r["name_form"]: r for r in queries.fetch_existing_name_forms(conn)}
    logger.info(f"  {len(existing)} formes existantes en base")

    inserted = 0
    updated = 0
    deleted = 0

    for nf, data in expected_forms.items():
        if nf in existing:
            old = existing[nf]
            if set(data["person_ids"]) != set(old["person_ids"]) or set(data["sources"]) != set(
                old["sources"] or []
            ):
                queries.update_name_form(conn, old["id"], data["person_ids"], data["sources"])
                updated += 1
        else:
            queries.insert_name_form_with_merge(conn, nf, data["person_ids"], data["sources"])
            inserted += 1

    for nf, old in existing.items():
        if nf not in expected_forms:
            queries.delete_name_form(conn, old["id"])
            deleted += 1

    conn.commit()

    logger.info(f"Terminé : {inserted} ajoutées, {updated} mises à jour, {deleted} supprimées")
