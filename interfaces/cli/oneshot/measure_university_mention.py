# STATUS: oneshot (2026-10-27)
"""Contributions sources hors périmètre rapprochées par le nom des personnes RH, hors pipeline.

Une contribution source est candidate quand elle est hors périmètre, et qu'une de ses adresses cite une structure du périmètre d'extraction absente du périmètre des personnes (CHU, écoles, centres associés). Seules les sources qui donnent le texte de l'adresse comptent : OpenAlex, WoS, Crossref, DataCite.

Le nom de la contribution source est cherché dans les formes de nom actives des personnes RH, sous la forme « prénom nom » puis « nom prénom », comme dans la phase `persons`. L'enregistrement source paraît entre l'année qui suit l'arrivée de la personne et l'année de fin de son contrat, plus `--tolerance` années. Une paire rejetée par l'administration est écartée.

Chaque rapprochement reçoit un état :

- `sans publication` : l'enregistrement source n'est dans aucune publication ;
- `personne déjà dans la publication` : la personne a une contribution dans la publication, par une autre source ;
- `contribution source non alignée` : contribution source collective ou doublon d'auteur ;
- `contribution sans personne` ;
- `contribution d'une autre personne`.

Le rapport donne les volumes par état, source, structure et année, en distinguant les noms qui désignent une seule personne. Tous les rapprochements s'écrivent dans un CSV, et un échantillon de noms univoques dans un second, pour le contrôle des homonymes à la main. Lecture seule sur la base.

Usage :
    python -m interfaces.cli.oneshot.measure_university_mention [--tolerance 1] [--sample 50]
"""

from __future__ import annotations

import argparse
import csv
import os
import random
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.sql_fragments import active_name_form

log = setup_logger("measure_university_mention", os.path.dirname(__file__))

_MEASURES = Path("data/measures")
_SOURCES = ("openalex", "wos", "crossref", "datacite")
_TOP = 20

_ALREADY_PRESENT = "personne déjà dans la publication"
_UNIQUE = "nom univoque"
_AMBIGUOUS = "nom ambigu"


def _perimeter_structures(config_key: str) -> str:
    return f"""
        SELECT ps.structure_id FROM perimeter_structures ps
        JOIN perimeters p ON p.id = ps.perimeter_id
        WHERE p.code = (SELECT value #>> '{{}}' FROM config WHERE key = '{config_key}')
    """


_TEMP_TABLES = f"""
    CREATE TEMP TABLE outer_structures AS
    {_perimeter_structures("perimeter_extraction")}
    EXCEPT
    {_perimeter_structures("perimeter_persons")};

    CREATE TEMP TABLE rh_periods AS
    SELECT r.person_id,
           min(coalesce(extract(year FROM r.start_date)::int + 1, 0)) AS first_year,
           max(coalesce(extract(year FROM r.end_date)::int, 9999)) AS last_year
    FROM hr_records r
    JOIN persons p ON p.id = r.person_id
    WHERE p.exclusion IS NULL
    GROUP BY 1;

    CREATE TEMP TABLE rh_forms AS
    SELECT DISTINCT pnf.name_form, pnf.person_id
    FROM person_name_forms pnf
    JOIN rh_periods rp ON rp.person_id = pnf.person_id
    WHERE {active_name_form("pnf")};

    CREATE TEMP TABLE form_person_counts AS
    SELECT pnf.name_form, count(DISTINCT pnf.person_id) AS persons
    FROM person_name_forms pnf
    JOIN persons p ON p.id = pnf.person_id
    WHERE {active_name_form("pnf")} AND p.exclusion IS NULL
      AND pnf.name_form IN (SELECT name_form FROM rh_forms)
    GROUP BY 1;

    CREATE TEMP TABLE candidates AS
    SELECT sc.id AS source_contribution_id, sc.source_record_id, sc.contributor_information_id,
           array_agg(DISTINCT ast.structure_id ORDER BY ast.structure_id) AS structure_ids
    FROM source_contributions sc
    JOIN source_contribution_addresses sca ON sca.source_contribution_id = sc.id
    JOIN address_structures ast ON ast.address_id = sca.address_id
    WHERE NOT sc.in_perimeter
      AND NOT sc.collective
      AND sc.source::text IN {_SOURCES}
      AND ast.is_confirmed IS DISTINCT FROM false
      AND ast.structure_id IN (SELECT structure_id FROM outer_structures)
    GROUP BY 1, 2, 3;

    CREATE TEMP TABLE matches AS
    WITH named AS (
        SELECT c.source_contribution_id, c.source_record_id, c.structure_ids,
               ci.author_name_normalized AS name_form
        FROM candidates c
        JOIN contributor_information ci ON ci.id = c.contributor_information_id
        UNION
        SELECT c.source_contribution_id, c.source_record_id, c.structure_ids,
               concat_ws(' ', nullif(ci.last_name_normalized, ''), nullif(ci.first_name_normalized, ''))
        FROM candidates c
        JOIN contributor_information ci ON ci.id = c.contributor_information_id
    )
    SELECT DISTINCT ON (n.source_contribution_id, f.person_id)
           n.source_contribution_id, n.source_record_id, n.structure_ids, n.name_form,
           f.person_id, fpc.persons AS form_persons
    FROM named n
    JOIN rh_forms f ON f.name_form = n.name_form
    JOIN form_person_counts fpc ON fpc.name_form = n.name_form
    JOIN rh_periods rp ON rp.person_id = f.person_id
    JOIN source_records sr ON sr.id = n.source_record_id
    WHERE sr.publication_year BETWEEN rp.first_year AND rp.last_year + :tolerance
      AND NOT EXISTS (
          SELECT 1 FROM rejected_contributions rej
          WHERE rej.source_record_id = n.source_record_id AND rej.person_id = f.person_id
      )
    ORDER BY n.source_contribution_id, f.person_id, fpc.persons;
"""

_MATCHES = f"""
    SELECT m.source_contribution_id, m.person_id, m.name_form, m.form_persons, m.structure_ids,
           count(*) OVER (PARTITION BY m.source_contribution_id) AS rh_candidates,
           pe.last_name, pe.first_name, hr.department_name, hr.role_title,
           hr.start_date, hr.end_date,
           sr.id AS source_record_id, sr.source::text AS source, sr.publication_year,
           coalesce(sr.doc_type::text, '?') AS doc_type,
           sr.doi, left(sr.title, 200) AS title, sr.publication_id,
           pu.in_perimeter AS publication_in_perimeter,
           coalesce(sc.raw_author_name, concat_ws(', ', sc.raw_last_name, sc.raw_first_name)) AS raw_author,
           (SELECT string_agg(a.raw_text, ' | ' ORDER BY a.id)
            FROM source_contribution_addresses sca JOIN addresses a ON a.id = sca.address_id
            WHERE sca.source_contribution_id = m.source_contribution_id) AS addresses,
           CASE
               WHEN sr.publication_id IS NULL THEN 'sans publication'
               WHEN EXISTS (
                   SELECT 1 FROM contributions c2
                   WHERE c2.publication_id = sr.publication_id AND c2.person_id = m.person_id
               ) THEN '{_ALREADY_PRESENT}'
               WHEN al.contribution_id IS NULL THEN 'contribution source non alignée'
               WHEN c.person_id IS NULL THEN 'contribution sans personne'
               ELSE 'contribution d''une autre personne'
           END AS state
    FROM matches m
    JOIN persons pe ON pe.id = m.person_id
    JOIN LATERAL (
        SELECT department_name, role_title, start_date, end_date FROM hr_records
        WHERE person_id = m.person_id ORDER BY start_date DESC NULLS LAST LIMIT 1
    ) hr ON true
    JOIN source_contributions sc ON sc.id = m.source_contribution_id
    JOIN source_records sr ON sr.id = m.source_record_id
    LEFT JOIN publications pu ON pu.id = sr.publication_id
    LEFT JOIN aligned_source_contributions al ON al.source_contribution_id = m.source_contribution_id
    LEFT JOIN contributions c ON c.id = al.contribution_id
"""


def _name_kind(row: dict[str, Any]) -> str:
    return _UNIQUE if row["form_persons"] == 1 and row["rh_candidates"] == 1 else _AMBIGUOUS


def _work_key(row: dict[str, Any]) -> str:
    """Clé d'un travail, commune aux enregistrements sources d'une même publication ou d'un même DOI."""
    if row["publication_id"] is not None:
        return f"p{row['publication_id']}"
    if row["doi"]:
        return f"doi:{row['doi'].lower()}"
    return f"sr{row['source_record_id']}"


def _log_tally(title: str, tally: Counter[Any]) -> None:
    log.info("  %s : %d", title, sum(tally.values()))
    for key, n in sorted(tally.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        log.info("    %-60s %7d", key, n)


def _structure_labels(conn: Connection) -> dict[int, str]:
    rows = conn.execute(text("SELECT id, coalesce(acronym, name) AS label FROM structures"))
    return {r.id: r.label for r in rows}


def _report(rows: list[dict[str, Any]], labels: dict[int, str], rh_persons: int) -> None:
    missing = [r for r in rows if r["state"] != _ALREADY_PRESENT]
    log.info(
        "─── Rapprochements : %d, dont %d hors des publications de la personne ───",
        len(rows),
        len(missing),
    )
    _log_tally("par état et nom", Counter(f"{r['state']} · {_name_kind(r)}" for r in rows))

    log.info("─── Hors des publications de la personne ───")
    works = {(r["person_id"], _work_key(r)) for r in missing}
    unique_works = {(r["person_id"], _work_key(r)) for r in missing if _name_kind(r) == _UNIQUE}
    log.info(
        "  couples (personne, travail) : %d, dont %d par un nom univoque",
        len(works),
        len(unique_works),
    )
    persons = {r["person_id"] for r in missing}
    log.info("  personnes RH concernées : %d sur %d", len(persons), rh_persons)
    _log_tally("par source", Counter(r["source"] for r in missing))
    _log_tally("par type de document", Counter(r["doc_type"] for r in missing))
    _log_tally(
        "par structure citée",
        Counter(labels.get(s, str(s)) for r in missing for s in r["structure_ids"]),
    )
    _log_tally("par année", Counter(r["publication_year"] for r in missing))
    _log_tally(
        "publication dans le périmètre",
        Counter(
            "sans publication"
            if r["publication_id"] is None
            else str(r["publication_in_perimeter"])
            for r in missing
        ),
    )

    by_person = Counter(
        f"{r['last_name']} {r['first_name']} ({r['department_name'] or '?'})"
        for r in {
            (r["person_id"], _work_key(r)): r for r in missing if _name_kind(r) == _UNIQUE
        }.values()
    )
    log.info("  personnes aux nombres de travaux les plus élevés, noms univoques :")
    for label, n in by_person.most_common(_TOP):
        log.info("    %-60s %7d", label, n)


_CSV_FIELDS = (
    "state",
    "name_kind",
    "person_id",
    "last_name",
    "first_name",
    "department_name",
    "role_title",
    "start_date",
    "end_date",
    "source",
    "source_record_id",
    "publication_id",
    "publication_in_perimeter",
    "publication_year",
    "doc_type",
    "doi",
    "title",
    "raw_author",
    "name_form",
    "form_persons",
    "rh_candidates",
    "structures",
    "addresses",
)


def _write_csv(path: Path, rows: list[dict[str, Any]], labels: dict[int, str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow(
                {
                    **r,
                    "name_kind": _name_kind(r),
                    "structures": ", ".join(labels.get(s, str(s)) for s in r["structure_ids"]),
                }
            )
    log.info("Écrit : %s (%d lignes)", path, len(rows))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tolerance", type=int, default=1, help="années après la fin du contrat")
    parser.add_argument(
        "--sample", type=int, default=50, help="taille de l'échantillon à contrôler"
    )
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        log.info("Rapprochement des contributions sources hors périmètre et des personnes RH…")
        for statement in _TEMP_TABLES.split(";"):
            if statement.strip():
                conn.execute(text(statement), {"tolerance": args.tolerance})
        candidates = conn.execute(text("SELECT count(*) FROM candidates")).scalar_one()
        rh_persons = conn.execute(text("SELECT count(*) FROM rh_periods")).scalar_one()
        log.info(
            "Contributions sources candidates : %d. Personnes RH : %d.", candidates, rh_persons
        )
        log.info("Lecture des rapprochements…")
        rows = [dict(r._mapping) for r in conn.execute(text(_MATCHES))]
        labels = _structure_labels(conn)

    rows.sort(
        key=lambda r: (r["last_name"], r["first_name"], r["person_id"], r["publication_year"] or 0)
    )
    _report(rows, labels, rh_persons)

    _MEASURES.mkdir(parents=True, exist_ok=True)
    _write_csv(_MEASURES / "university_mention_matches.csv", rows, labels)
    pool = [r for r in rows if r["state"] != _ALREADY_PRESENT and _name_kind(r) == _UNIQUE]
    rng = random.Random(args.seed)  # noqa: S311 - tirage reproductible d'un échantillon
    sample = rng.sample(pool, min(args.sample, len(pool)))
    _write_csv(_MEASURES / "university_mention_sample.csv", sample, labels)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
