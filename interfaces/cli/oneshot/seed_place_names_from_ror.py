"""
Seed `place_name_forms` (kind='institution') depuis le registre ROR.

ROR (Research Organization Registry) est le référentiel autoritaire des organismes
de recherche : noms (+ variantes) et pays. On en tire un mapping forme → pays
propre, sans inférence empirique.

Deux modes :
  --build : télécharge le dump ROR v2.8 (épinglé, reproductible), aplatit
            `names[].value × locations[].geonames_details.country_code`, ne garde
            que les formes **mono-pays**, **hors acronymes**, **non purement
            numériques** et **≥ 6 caractères** (acronymes, numériques et formes
            courtes génèrent des faux positifs que le prune ne rattrape pas),
            normalise via `normalize_text`, écrit `data/ror_institutions.csv`.
  (défaut): lit `data/ror_institutions.csv` et insère `kind='institution'`
            (`ON CONFLICT (form_normalized) DO NOTHING`, idempotent).

`data/` est gitignoré : le CSV se génère une fois puis se transfère manuellement
entre machines. À lancer après avoir vidé les anciennes formes non-country.

Usage :
    python -m interfaces.cli.oneshot.seed_place_names_from_ror --build
    python -m interfaces.cli.oneshot.seed_place_names_from_ror
"""

import argparse
import csv
import io
import json
import time
import urllib.request
import zipfile
from collections import defaultdict

from sqlalchemy import text

from domain.normalize import normalize_text
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

logger = setup_logger("seed_place_names_ror", "processing/logs")

ROR_URL = "https://zenodo.org/api/records/20512981/files/v2.8-2026-06-02-ror-data.zip/content"
CSV_PATH = "data/ror_institutions.csv"
BATCH = 20000


def build_csv() -> None:
    """Télécharge le dump ROR épinglé et écrit le CSV (mono-pays, hors acronymes)."""
    logger.info(f"Téléchargement du dump ROR ({ROR_URL})…")
    with urllib.request.urlopen(ROR_URL, timeout=180) as resp:  # noqa: S310 (URL fixe de confiance)
        raw = resp.read()
    zf = zipfile.ZipFile(io.BytesIO(raw))
    json_name = next(n for n in zf.namelist() if n.endswith(".json"))
    records = json.loads(zf.read(json_name))
    logger.info(f"{len(records)} organismes dans le dump")

    form_countries: dict[str, set[str]] = defaultdict(set)
    form_is_acronym: dict[str, bool] = defaultdict(lambda: True)
    for org in records:
        if org.get("status") != "active":
            continue
        countries = {
            loc.get("geonames_details", {}).get("country_code") for loc in org.get("locations", [])
        }
        countries = {c.lower() for c in countries if c}
        if not countries:
            continue
        for name in org.get("names", []):
            form = normalize_text(name.get("value", ""))
            # Écarte les formes purement numériques (codes/numéros pris pour des
            # noms d'orgs) et les formes trop courtes (< 6 car. → faux positifs).
            if not form or form.isdigit() or len(form) < 6:
                continue
            form_countries[form] |= countries
            if "acronym" not in name.get("types", []):
                form_is_acronym[form] = False

    rows = sorted(
        (next(iter(cs)), form)
        for form, cs in form_countries.items()
        if len(cs) == 1 and not form_is_acronym[form]
    )
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as out:
        writer = csv.writer(out)
        writer.writerow(["iso_code", "form_normalized"])
        writer.writerows(rows)
    logger.info(f"{len(rows)} formes mono-pays hors acronymes → {CSV_PATH}")


def seed() -> None:
    """Insère les formes du CSV dans `place_name_forms` (idempotent)."""
    with open(CSV_PATH, encoding="utf-8") as f:
        rows = [(r["iso_code"], r["form_normalized"]) for r in csv.DictReader(f)]
    logger.info(f"{len(rows)} formes à insérer depuis {CSV_PATH}")

    stmt = text("""
        INSERT INTO place_name_forms (iso_code, form_normalized, kind)
        SELECT e->>'i', e->>'f', 'institution'
        FROM jsonb_array_elements(CAST(:payload AS jsonb)) e
        ON CONFLICT (form_normalized) DO NOTHING
    """)
    t0 = time.time()
    inserted = 0
    with get_sync_engine().connect() as conn:
        for i in range(0, len(rows), BATCH):
            batch = rows[i : i + BATCH]
            payload = json.dumps([{"i": iso, "f": form} for iso, form in batch])
            inserted += conn.execute(stmt, {"payload": payload}).rowcount
            conn.commit()
            logger.info(f"  {min(i + BATCH, len(rows))}/{len(rows)}")
    logger.info(f"Terminé : {inserted} formes insérées (nouvelles) en {time.time() - t0:.0f}s")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--build", action="store_true", help="(Re)générer le CSV depuis le dump ROR"
    )
    args = parser.parse_args()
    if args.build:
        build_csv()
    else:
        seed()


if __name__ == "__main__":
    main()
