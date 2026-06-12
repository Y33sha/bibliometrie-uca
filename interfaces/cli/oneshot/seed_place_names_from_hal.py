"""
Seed `place_name_forms` (kind='institution') depuis l'API Structures de HAL.

Complète le seed ROR avec les noms de structures que HAL connaît mais pas ROR
(labos, structures françaises et étrangères auto-créées au dépôt, etc.).

On n'interroge que les structures **réellement référencées par le corpus**
(`source_authorships.source_structures`, ~43 k docid distincts), pas les 610 k
fiches du référentiel. Le champ retenu est `name_s` : c'est exactement le
`StructNom` que `normalize_hal` embarque dans `addresses` (vérifié), donc
`normalize_text(name_s)` matche les formes d'adresses. Le pays vient de
`country_s` (ISO minuscule). Pas de filtre `valid_s` : 35 % des structures du
corpus sont OLD/INCOMING mais portent un pays valide et apparaissent dans les
adresses historiques.

Garde-fou **mono-pays** : si un même nom normalisé provient de structures de
pays différents (nom générique type « faculty of medicine »), on le retire.

Deux modes :
  --build : interroge l'API par lots de docid, agrège, écrit `data/hal_structures.csv`.
  (défaut): seede ce CSV (`kind='institution'`, `ON CONFLICT DO NOTHING`).

Usage :
    python -m interfaces.cli.oneshot.seed_place_names_from_hal --build
    python -m interfaces.cli.oneshot.seed_place_names_from_hal
"""

import argparse
import csv
import time
from collections import defaultdict

from sqlalchemy import text

from domain.normalize import normalize_text
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.sources.api_limits import HAL_DELAY
from infrastructure.sources.http_retry import http_request_with_retry
from interfaces.cli.oneshot.seed_place_names_from_ror import seed

logger = setup_logger("seed_place_names_hal", "processing/logs")

STRUCTURE_API = "https://api.archives-ouvertes.fr/ref/structure/"
CSV_PATH = "data/hal_structures.csv"
DOCID_BATCH = 200


def corpus_structure_ids() -> list[str]:
    """docid des structures HAL référencées par au moins une source_authorship."""
    with get_sync_engine().connect() as conn:
        return [
            r[0]
            for r in conn.execute(
                text(
                    "SELECT DISTINCT unnest(source_structures) FROM source_authorships "
                    "WHERE source = 'hal' AND source_structures IS NOT NULL"
                )
            )
        ]


def build_csv() -> None:
    """Interroge l'API Structures par docid, agrège name_s → country_s, écrit le CSV mono-pays."""
    docids = corpus_structure_ids()
    logger.info(f"{len(docids)} structures HAL distinctes dans le corpus")

    name_countries: dict[str, set[str]] = defaultdict(set)
    for i in range(0, len(docids), DOCID_BATCH):
        batch = docids[i : i + DOCID_BATCH]
        data = http_request_with_retry(
            "GET",
            STRUCTURE_API,
            params={
                "q": "docid:(" + " ".join(batch) + ")",
                "fl": "name_s,country_s",
                "rows": len(batch),
                "wt": "json",
            },
            timeout=60,
            label=f"structures {min(i + DOCID_BATCH, len(docids))}/{len(docids)}",
        )
        for struct in data.get("response", {}).get("docs", []):
            country = (struct.get("country_s") or "").strip().lower()
            form = normalize_text(struct.get("name_s", ""))
            if not country or not form or form.isdigit() or len(form) < 6:
                continue
            name_countries[form].add(country)
        logger.info(f"  {min(i + DOCID_BATCH, len(docids))}/{len(docids)}")
        time.sleep(HAL_DELAY)

    rows = sorted(
        (next(iter(countries)), form)
        for form, countries in name_countries.items()
        if len(countries) == 1
    )
    multi = sum(1 for countries in name_countries.values() if len(countries) > 1)
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as out:
        writer = csv.writer(out)
        writer.writerow(["iso_code", "form_normalized"])
        writer.writerows(rows)
    logger.info(f"{len(rows)} formes mono-pays → {CSV_PATH} ({multi} noms multi-pays écartés)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true", help="(Re)générer le CSV depuis l'API HAL")
    parser.add_argument("--csv", default=CSV_PATH, help="CSV à seeder (iso_code, form_normalized)")
    args = parser.parse_args()
    if args.build:
        build_csv()
    else:
        seed(args.csv, "institution")


if __name__ == "__main__":
    main()
