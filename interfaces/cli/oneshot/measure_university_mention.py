# STATUS: oneshot (2026-10-27)
"""Mention de l'université dans les adresses des personnes RH, hors pipeline.

Deux ensembles de travaux, pour chaque personne RH, parus entre l'année qui suit son arrivée et l'année de fin de son contrat, plus `--tolerance` années :

- publications rattachées : la personne a une contribution dans la publication ;
- travaux rapprochés par le nom : contributions sources hors périmètre dont une adresse cite une structure du périmètre d'extraction absente du périmètre des personnes (CHU, écoles, centres associés), et dont le nom figure dans les formes de nom actives d'une personne RH, sous la forme « prénom nom » puis « nom prénom ». Une paire rejetée par l'administration est écartée.

Seules les sources qui donnent le texte de l'adresse comptent : OpenAlex, WoS, Crossref, DataCite. Un travail a une adresse exploitable quand une contribution source de la personne, dans ces sources, a une adresse. Il mentionne l'université quand une de ces adresses est rattachée à une structure racine du périmètre des personnes. Les adresses sans l'université sont classées : structure du périmètre des personnes (laboratoire seul), structure de l'Alliance, autre structure connue, aucune structure reconnue.

Un rapprochement par le nom reçoit un état :

- `sans publication` : l'enregistrement source n'est dans aucune publication ;
- `personne déjà dans la publication` : la personne a une contribution dans la publication, par une autre source ; le rapprochement est seulement compté ;
- `contribution source non alignée` : contribution source collective ou doublon d'auteur ;
- `contribution sans personne` ;
- `contribution d'une autre personne`.

Le rapport est une page HTML, `data/measures/university_mention.html`, construite sur le gabarit `measure_university_mention.html`. Elle donne les trois comptes par personne, le classement des adresses, les rapprochements par le nom, et les adresses sans l'université les plus fréquentes, avec une saisie de verdict. Lecture seule sur la base.

Usage :
    python -m interfaces.cli.oneshot.measure_university_mention [--tolerance 1] [--addresses 500]
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.sql_fragments import active_name_form

log = setup_logger("measure_university_mention", os.path.dirname(__file__))

_MEASURES = Path("data/measures")
_TEMPLATE = Path(__file__).with_suffix(".html")
_SOURCES = ("openalex", "wos", "crossref", "datacite")
_CATEGORIES = ("laboratoire", "alliance", "organisme", "aucune")

_ALREADY_PRESENT = "personne déjà dans la publication"
_UNIVERSITY = "université"


def _perimeter_code(config_key: str) -> str:
    return f"(SELECT value #>> '{{}}' FROM config WHERE key = '{config_key}')"


def _perimeter_structures(config_key: str) -> str:
    return f"""
        SELECT ps.structure_id FROM perimeter_structures ps
        JOIN perimeters p ON p.id = ps.perimeter_id
        WHERE p.code = {_perimeter_code(config_key)}
    """


_TEMP_TABLES = f"""
    CREATE TEMP TABLE university_structures AS
    SELECT unnest(root_structure_ids) AS structure_id FROM perimeters
    WHERE code = {_perimeter_code("perimeter_persons")};

    CREATE TEMP TABLE persons_structures AS
    {_perimeter_structures("perimeter_persons")};

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

    CREATE TEMP TABLE match_rows AS
    SELECT m.source_contribution_id, m.person_id, m.structure_ids,
           m.form_persons = 1 AND count(*) OVER (PARTITION BY m.source_contribution_id) = 1 AS unique_name,
           coalesce('p' || sr.publication_id, 'doi:' || lower(sr.doi), 'sr' || sr.id) AS work,
           sr.source::text AS source, sr.publication_year AS year,
           coalesce(sr.doc_type::text, '?') AS doc_type,
           sr.doi, left(sr.title, 200) AS title, sr.publication_id,
           pu.in_perimeter AS publication_in_perimeter,
           coalesce(sc.raw_author_name, concat_ws(', ', sc.raw_last_name, sc.raw_first_name)) AS raw_author,
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
    JOIN source_contributions sc ON sc.id = m.source_contribution_id
    JOIN source_records sr ON sr.id = m.source_record_id
    LEFT JOIN publications pu ON pu.id = sr.publication_id
    LEFT JOIN aligned_source_contributions al ON al.source_contribution_id = m.source_contribution_id
    LEFT JOIN contributions c ON c.id = al.contribution_id;

    CREATE TEMP TABLE linked_works AS
    SELECT c.person_id, 'p' || c.publication_id AS work, c.id AS contribution_id,
           p.publication_year AS year, coalesce(p.doc_type::text, '?') AS doc_type,
           p.doi, left(p.title, 200) AS title
    FROM contributions c
    JOIN publications p ON p.id = c.publication_id
    JOIN rh_periods rp ON rp.person_id = c.person_id
    WHERE p.publication_year BETWEEN rp.first_year AND rp.last_year + :tolerance;

    CREATE TEMP TABLE person_source_contributions AS
    SELECT lw.person_id, lw.work, sc.id AS source_contribution_id, sc.source::text AS source
    FROM linked_works lw
    JOIN aligned_source_contributions al ON al.contribution_id = lw.contribution_id
    JOIN source_contributions sc ON sc.id = al.source_contribution_id
    WHERE sc.source::text IN {_SOURCES}
    UNION
    SELECT person_id, work, source_contribution_id, source
    FROM match_rows
    WHERE state <> '{_ALREADY_PRESENT}';

    CREATE TEMP TABLE hal_prefixes AS
    SELECT DISTINCT acronym || ' - ' || name AS label FROM hal_structures WHERE acronym IS NOT NULL;

    CREATE TEMP TABLE hal_label_addresses AS
    SELECT DISTINCT a.id AS address_id
    FROM person_source_contributions psc
    JOIN source_contribution_addresses sca ON sca.source_contribution_id = psc.source_contribution_id
    JOIN addresses a ON a.id = sca.address_id
    WHERE psc.source = 'openalex'
      AND (a.raw_text ~ '\\(.* - [^()]+\\)$'
           OR regexp_replace(a.raw_text, ' \\(.*\\)$', '') IN (SELECT label FROM hal_prefixes));

    CREATE TEMP TABLE work_addresses AS
    SELECT psc.person_id, psc.work, psc.source, sca.address_id,
           psc.source = 'openalex' AND sca.address_id IN (SELECT address_id FROM hal_label_addresses) AS hal_label,
           CASE
               WHEN bool_or(ast.structure_id IN (SELECT structure_id FROM university_structures)) THEN '{_UNIVERSITY}'
               WHEN bool_or(ast.structure_id IN (SELECT structure_id FROM persons_structures)) THEN 'laboratoire'
               WHEN bool_or(ast.structure_id IN (SELECT structure_id FROM outer_structures)) THEN 'alliance'
               WHEN bool_or(ast.structure_id IS NOT NULL) THEN 'organisme'
               ELSE 'aucune'
           END AS category
    FROM person_source_contributions psc
    JOIN source_contribution_addresses sca ON sca.source_contribution_id = psc.source_contribution_id
    LEFT JOIN address_structures ast
        ON ast.address_id = sca.address_id AND ast.is_confirmed IS DISTINCT FROM false
    GROUP BY 1, 2, 3, 4, 5
"""

_PERSONS = """
    SELECT rp.person_id, pe.last_name || ' ' || pe.first_name AS name,
           hr.department_name, hr.start_date, hr.end_date
    FROM rh_periods rp
    JOIN persons pe ON pe.id = rp.person_id
    JOIN LATERAL (
        SELECT department_name, start_date, end_date FROM hr_records
        WHERE person_id = rp.person_id ORDER BY start_date DESC NULLS LAST LIMIT 1
    ) hr ON true
    ORDER BY pe.last_name, pe.first_name, rp.person_id
"""


def _perimeter_names(conn: Connection) -> dict[str, str]:
    rows = conn.execute(
        text("""
            SELECT c.key, p.name FROM config c
            JOIN perimeters p ON p.code = c.value #>> '{}'
            WHERE c.key IN ('perimeter_extraction', 'perimeter_persons')
        """)
    )
    return {r.key: r.name for r in rows}


def _structure_labels(conn: Connection) -> dict[int, str]:
    rows = conn.execute(text("SELECT id, coalesce(acronym, name) AS label FROM structures"))
    return {r.id: r.label for r in rows}


class _Indexer:
    """Position de chaque valeur dans une liste, pour des références compactes dans la page."""

    def __init__(self) -> None:
        self.values: list[Any] = []
        self._positions: dict[Any, int] = {}

    def __call__(self, value: Any) -> int:
        if value not in self._positions:
            self._positions[value] = len(self.values)
            self.values.append(value)
        return self._positions[value]


def _bits(values: set[str], universe: tuple[str, ...]) -> int:
    return sum(1 << i for i, v in enumerate(universe) if v in values)


class _WorkAddresses:
    """Adresses de la personne dans chaque travail : sources qui en donnent, sources qui mentionnent l'université, catégories et adresses sans l'université."""

    def __init__(self) -> None:
        self.exploitable: defaultdict[tuple[int, str], set[str]] = defaultdict(set)
        self.mentioning: defaultdict[tuple[int, str], set[str]] = defaultdict(set)
        self.categories: defaultdict[tuple[int, str], set[str]] = defaultdict(set)
        self.address_ids: defaultdict[tuple[int, str], set[int]] = defaultdict(set)

    def add(self, key: tuple[int, str], source: str, address_id: int, category: str) -> None:
        self.exploitable[key].add(source)
        if category == _UNIVERSITY:
            self.mentioning[key].add(source)
        else:
            self.categories[key].add(category)
            self.address_ids[key].add(address_id)

    def unmentioned(self, key: tuple[int, str]) -> bool:
        return bool(self.exploitable[key]) and not self.mentioning[key]

    def masks(self, key: tuple[int, str]) -> tuple[int, int, int]:
        return (
            _bits(self.exploitable[key], _SOURCES),
            _bits(self.mentioning[key], _SOURCES),
            _bits(self.categories[key], _CATEGORIES),
        )


def _build_payload(conn: Connection, tolerance: int, review_size: int) -> dict[str, Any]:
    persons = [dict(r._mapping) for r in conn.execute(text(_PERSONS))]
    person_index = {p["person_id"]: i for i, p in enumerate(persons)}
    doc_types = _Indexer()
    labels = _structure_labels(conn)

    log.info("Lecture des rapprochements par le nom…")
    match_rows = [dict(r._mapping) for r in conn.execute(text("SELECT * FROM match_rows"))]
    present = [r for r in match_rows if r["state"] == _ALREADY_PRESENT]
    missing = [r for r in match_rows if r["state"] != _ALREADY_PRESENT]

    works: dict[tuple[int, str], dict[str, Any]] = {}
    for r in conn.execute(text("SELECT * FROM linked_works")):
        works[(r.person_id, r.work)] = {
            "year": r.year,
            "doc_type": r.doc_type,
            "origin": 0,
            "unique": True,
            "title": r.title,
            "doi": r.doi,
        }
    for r in missing:
        works.setdefault(
            (r["person_id"], r["work"]),
            {
                "year": r["year"],
                "doc_type": r["doc_type"],
                "origin": 1,
                "unique": r["unique_name"],
                "title": r["title"],
                "doi": r["doi"],
            },
        )

    log.info("Lecture des adresses des travaux…")
    # Deux lectures : adresses d'éditeur seules (libellés HAL d'OpenAlex écartés), et toutes les adresses.
    publisher, every = _WorkAddresses(), _WorkAddresses()
    address_category: dict[int, tuple[str, bool]] = {}
    for r in conn.execute(text("SELECT * FROM work_addresses")):
        key = (r.person_id, r.work)
        address_category[r.address_id] = (r.category, r.hal_label)
        every.add(key, r.source, r.address_id, r.category)
        if not r.hal_label:
            publisher.add(key, r.source, r.address_id, r.category)

    unmentioned = [k for k in works if publisher.unmentioned(k) or every.unmentioned(k)]
    address_works: defaultdict[int, list[tuple[int, str]]] = defaultdict(list)
    for key in works:
        if publisher.unmentioned(key):
            for address_id in publisher.address_ids[key]:
                address_works[address_id].append(key)
    reviewed = sorted(address_works, key=lambda a: (-len(address_works[a]), a))[:review_size]
    referenced = set(reviewed) | {a for k in unmentioned for a in every.address_ids[k]}
    address_texts = dict(
        conn.execute(
            text("SELECT id, raw_text FROM addresses WHERE id = ANY(:ids)"),
            {"ids": sorted(referenced)},
        ).all()
    )
    addresses = _Indexer()

    def address_ref(address_id: int) -> int:
        return addresses((address_id, address_texts[address_id], *address_category[address_id]))

    details: list[list[Any]] = []
    for key in unmentioned:
        w = works[key]
        w["detail"] = len(details)
        details.append(
            [w["title"], w["doi"], [address_ref(a) for a in sorted(every.address_ids[key])]]
        )
    page_works = [
        [
            person_index[key[0]],
            w["year"],
            doc_types(w["doc_type"]),
            w["origin"],
            int(w["unique"]),
            *publisher.masks(key),
            *every.masks(key),
            w.get("detail", -1),
        ]
        for key, w in sorted(
            works.items(), key=lambda kv: (person_index[kv[0][0]], -(kv[1]["year"] or 0))
        )
    ]

    review = []
    for address_id in reviewed:
        keys = address_works[address_id]
        review.append(
            {
                "address": address_ref(address_id),
                "works": len(keys),
                "persons": sorted({persons[person_index[p]]["name"] for p, _ in keys})[:4],
                "person_count": len({p for p, _ in keys}),
            }
        )

    perimeters = _perimeter_names(conn)
    return {
        "date": datetime.now(UTC).date(),
        "tolerance": tolerance,
        "sources": _SOURCES,
        "categories": _CATEGORIES,
        "extraction_perimeter": perimeters.get("perimeter_extraction"),
        "persons_perimeter": perimeters.get("perimeter_persons"),
        "candidates": conn.execute(text("SELECT count(*) FROM candidates")).scalar_one(),
        "persons": [
            [p["name"], p["department_name"], str(p["start_date"] or ""), str(p["end_date"] or "")]
            for p in persons
        ],
        "doc_types": doc_types.values,
        "works": page_works,
        "details": details,
        "addresses": [[a[0], a[1], a[2]] for a in addresses.values],
        "review": review,
        "present": len(present),
        "matches": [
            {
                "person": person_index[r["person_id"]],
                "work": r["work"],
                "unique": r["unique_name"],
                "state": r["state"],
                "source": r["source"],
                "year": r["year"],
                "doc_type": r["doc_type"],
                "doi": r["doi"],
                "title": r["title"],
                "publication_id": r["publication_id"],
                "publication_in_perimeter": r["publication_in_perimeter"],
                "raw_author": r["raw_author"],
                "structures": [labels.get(s, str(s)) for s in r["structure_ids"]],
            }
            for r in missing
        ],
    }


def _write_page(path: Path, payload: dict[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))
    page = _TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", data.replace("</", "<\\/"))
    path.write_text(page, encoding="utf-8")
    log.info("Écrit : %s (%.1f Mo)", path, len(page.encode()) / 1e6)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tolerance", type=int, default=1, help="années après la fin du contrat")
    parser.add_argument(
        "--addresses", type=int, default=500, help="nombre d'adresses proposées à la vérification"
    )
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        log.info("Calcul des travaux des personnes RH et de leurs adresses…")
        for statement in _TEMP_TABLES.split(";"):
            if statement.strip():
                conn.execute(text(statement), {"tolerance": args.tolerance})
        payload = _build_payload(conn, args.tolerance, args.addresses)

    log.info(
        "Personnes RH : %d. Travaux : %d. Rapprochements par le nom hors des publications de la personne : %d.",
        len(payload["persons"]),
        len(payload["works"]),
        len(payload["matches"]),
    )
    _MEASURES.mkdir(parents=True, exist_ok=True)
    _write_page(_MEASURES / "university_mention.html", payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
