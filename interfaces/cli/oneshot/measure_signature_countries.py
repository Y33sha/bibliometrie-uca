# STATUS: oneshot (2026-10-16)
"""Pays des contributions sources, hors pipeline : contradictions entre leurs sources, et effet sur les pays des publications.

Le pays d'une contribution source réunit trois sources :

- `adresse` : pays retenu de ses adresses, composé par `retained_countries` à partir du fichier de `measure_address_country_candidates` ; il inclut les ROR de l'affiliation de l'adresse ;
- `ror` : pays des organisations ROR de la contribution source sans texte d'affiliation ;
- `hal` : pays des structures HAL de la contribution source (`ref.hal_structures.country_code`).

Le rapport donne, par source d'enregistrement, la couverture de chacune, leurs relations deux à deux, et les pays des publications qu'en tire chaque règle — adresses seules, ou les trois sources — comparés à `publications.countries`. Un échantillon de contributions sources dont l'adresse contredit le ROR ou la structure HAL s'écrit à part, pour une revue à la main. Lecture seule sur la base.

Usage :
    uv run python -m interfaces.cli.oneshot.measure_signature_countries
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
from collections import defaultdict
from pathlib import Path

from sqlalchemy import Connection, text

from domain.countries import NO_COUNTRY_CODE
from domain.country_detection import CountryDetectionMethod, retained_countries
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("measure_signature_countries", os.path.dirname(__file__))

_MEASURES = Path("data/measures")
_BATCH = 20_000
_SAMPLE = 40

_SOURCE_CONTRIBUTION_TABLES = """
    CREATE TEMP TABLE sig_addr AS
    SELECT sca.source_contribution_id AS source_contribution_id, array_agg(DISTINCT c ORDER BY c) AS countries
    FROM source_contribution_addresses sca
    JOIN addr_retained r ON r.address_id = sca.address_id
    CROSS JOIN LATERAL unnest(r.countries) c
    GROUP BY 1;

    CREATE TEMP TABLE sig_ror AS
    SELECT scr.source_contribution_id AS source_contribution_id,
           array_agg(DISTINCT ro.country_code::text ORDER BY ro.country_code::text) AS countries
    FROM source_contribution_rors scr
    JOIN ror_organizations ro ON ro.ror_id = scr.ror_id
    WHERE scr.address_id IS NULL
    GROUP BY 1;

    CREATE TEMP TABLE sig_hal AS
    SELECT h.source_contribution_id AS source_contribution_id,
           array_agg(DISTINCT hs.country_code::text ORDER BY hs.country_code::text) AS countries
    FROM source_contribution_hal_structures h
    JOIN hal_structures hs ON hs.hal_structure_id = h.hal_structure_id
    WHERE hs.country_code IS NOT NULL
    GROUP BY 1;

    CREATE TEMP TABLE sig_all AS
    SELECT s.source_contribution_id, sr.source::text AS source, sr.publication_id,
           a.countries AS addr, r.countries AS ror, h.countries AS hal
    FROM (SELECT source_contribution_id FROM sig_addr UNION SELECT source_contribution_id FROM sig_ror UNION SELECT source_contribution_id FROM sig_hal) s
    JOIN source_contributions sc ON sc.id = s.source_contribution_id
    JOIN source_records sr ON sr.id = sc.source_record_id
    LEFT JOIN sig_addr a ON a.source_contribution_id = s.source_contribution_id
    LEFT JOIN sig_ror r ON r.source_contribution_id = s.source_contribution_id
    LEFT JOIN sig_hal h ON h.source_contribution_id = s.source_contribution_id;
"""

_COVERAGE = """
    SELECT source, count(*) AS total,
           count(addr) AS addr, count(ror) AS ror, count(hal) AS hal,
           count(*) FILTER (WHERE addr IS NULL) AS sans_adresse
    FROM sig_all GROUP BY 1 ORDER BY 2 DESC
"""

_RELATION = """
    SELECT source,
           count(*) AS communes,
           count(*) FILTER (WHERE {a} = {b}) AS identique,
           count(*) FILTER (WHERE {a} <> {b} AND {a} @> {b}) AS sur_ensemble,
           count(*) FILTER (WHERE {a} <> {b} AND {a} <@ {b}) AS sous_ensemble,
           count(*) FILTER (WHERE NOT {a} @> {b} AND NOT {a} <@ {b} AND {a} && {b}) AS recouvrement,
           count(*) FILTER (WHERE NOT {a} && {b}) AS disjoint
    FROM sig_all WHERE {a} IS NOT NULL AND {b} IS NOT NULL
    GROUP BY 1 ORDER BY 2 DESC
"""

_PUBLICATIONS = """
    WITH rule AS (
        SELECT publication_id AS pid, array_agg(DISTINCT c ORDER BY c) AS countries
        FROM sig_all
        CROSS JOIN LATERAL unnest({columns}) c
        WHERE publication_id IS NOT NULL
        GROUP BY 1
    )
    SELECT p.in_perimeter,
           count(*) FILTER (WHERE coalesce(p.countries, '{{}}') = coalesce(r.countries, '{{}}')) AS identique,
           count(*) FILTER (WHERE p.countries IS NULL AND r.countries IS NOT NULL) AS gagne,
           count(*) FILTER (WHERE p.countries IS NOT NULL AND r.countries IS NULL) AS perdu,
           count(*) FILTER (WHERE p.countries IS NOT NULL AND r.countries IS NOT NULL
                              AND p.countries <> r.countries) AS change
    FROM publications p
    LEFT JOIN rule r ON r.pid = p.id
    GROUP BY 1 ORDER BY 1 DESC
"""

_DISAGREEMENTS = """
    SELECT s.source_contribution_id, s.source, s.addr, s.{other} AS other,
           (SELECT string_agg(a.raw_text, ' | ') FROM source_contribution_addresses sca
              JOIN addresses a ON a.id = sca.address_id WHERE sca.source_contribution_id = s.source_contribution_id) AS addresses,
           {names} AS other_names,
           p.title
    FROM sig_all s
    LEFT JOIN publications p ON p.id = s.publication_id
    WHERE s.addr IS NOT NULL AND s.{other} IS NOT NULL AND NOT s.addr && s.{other}
    ORDER BY md5(s.source_contribution_id::text)
    LIMIT :limit
"""

_OTHER_NAMES = {
    "ror": """(SELECT string_agg(ro.name || ' (' || ro.country_code || ')', ' | ')
               FROM source_contribution_rors scr JOIN ror_organizations ro ON ro.ror_id = scr.ror_id
               WHERE scr.source_contribution_id = s.source_contribution_id AND scr.address_id IS NULL)""",
    "hal": """(SELECT string_agg(hs.name || ' (' || coalesce(hs.country_code, '?') || ')', ' | ')
               FROM source_contribution_hal_structures h
               JOIN hal_structures hs ON hs.hal_structure_id = h.hal_structure_id
               WHERE h.source_contribution_id = s.source_contribution_id)""",
}


def load_retained(conn: Connection, path: Path) -> int:
    """Charge dans la table temporaire `addr_retained` le pays retenu de chaque adresse existante, composé de ses candidats. Retourne le nombre d'adresses à pays."""
    existing = set(conn.execute(text("SELECT id FROM addresses")).scalars())
    candidates: defaultdict[int, defaultdict[CountryDetectionMethod, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    methods = {m.value for m in CountryDetectionMethod}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            address_id = int(row["address_id"])
            if (
                row["method"] in methods
                and address_id in existing
                and row["country_code"] != NO_COUNTRY_CODE
            ):
                candidates[address_id][CountryDetectionMethod(row["method"])].append(
                    row["country_code"]
                )
    rows = [
        {"id": address_id, "c": sorted(codes)}
        for address_id, by_method in candidates.items()
        if (codes := retained_countries(by_method))
    ]
    conn.execute(
        text("CREATE TEMP TABLE addr_retained (address_id int PRIMARY KEY, countries text[])")
    )
    for start in range(0, len(rows), _BATCH):
        conn.execute(
            text("""
                INSERT INTO addr_retained
                SELECT (e->>'id')::int, ARRAY(SELECT jsonb_array_elements_text(e->'c'))
                FROM jsonb_array_elements(CAST(:payload AS jsonb)) e
            """),
            {"payload": json.dumps(rows[start : start + _BATCH])},
        )
    return len(rows)


def _table(rows: list, headers: list[str]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += [
        "| "
        + " | ".join(f"{v:,}".replace(",", " ") if isinstance(v, int) else str(v) for v in r)
        + " |"
        for r in rows
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--candidates", type=Path, default=_MEASURES / "address_country_candidates.csv.gz"
    )
    args = parser.parse_args()
    sections: list[str] = ["# Pays des contributions sources\n"]
    with get_sync_engine().connect() as conn:
        log.info("adresses à pays retenu : %d", load_retained(conn, args.candidates))
        conn.execute(text(_SOURCE_CONTRIBUTION_TABLES))
        log.info(
            "contributions sources à pays : %d",
            conn.execute(text("SELECT count(*) FROM sig_all")).scalar(),
        )

        coverage = conn.execute(text(_COVERAGE)).all()
        sections.append(
            "## Couverture par source d'enregistrement\n\n"
            + _table(
                [tuple(r) for r in coverage],
                [
                    "Source",
                    "Contributions sources à pays",
                    "Adresse",
                    "ROR sans adresse",
                    "Structure HAL",
                    "Sans adresse",
                ],
            )
        )
        for a, b in (("addr", "ror"), ("addr", "hal"), ("ror", "hal")):
            rows = conn.execute(text(_RELATION.format(a=a, b=b))).all()
            sections.append(
                f"## `{a}` contre `{b}`\n\n"
                + _table(
                    [tuple(r) for r in rows],
                    [
                        "Source",
                        "Communes",
                        "Identique",
                        "Sur-ensemble",
                        "Sous-ensemble",
                        "Recouvrement",
                        "Disjoint",
                    ],
                )
            )
        for label, columns in (
            ("adresses seules", "addr"),
            (
                "adresses, ROR sans adresse et structures HAL",
                "coalesce(addr, '{}') || coalesce(ror, '{}') || coalesce(hal, '{}')",
            ),
        ):
            rows = conn.execute(text(_PUBLICATIONS.format(columns=columns))).all()
            sections.append(
                f"## Pays des publications : {label}, contre `publications.countries`\n\n"
                + _table(
                    [tuple(r) for r in rows],
                    ["Périmètre", "Identique", "Pays gagné", "Pays perdu", "Pays changé"],
                )
            )

        sample = _MEASURES / "signature_country_disagreements.csv"
        with sample.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                (
                    "kind",
                    "source_contribution_id",
                    "source",
                    "addr",
                    "other",
                    "addresses",
                    "other_names",
                    "title",
                )
            )
            for other, names in _OTHER_NAMES.items():
                for r in conn.execute(
                    text(_DISAGREEMENTS.format(other=other, names=names)), {"limit": _SAMPLE}
                ):
                    writer.writerow(
                        (
                            f"addr/{other}",
                            r.source_contribution_id,
                            r.source,
                            ",".join(r.addr),
                            ",".join(r.other),
                            r.addresses,
                            r.other_names,
                            r.title,
                        )
                    )

    report = _MEASURES / "signature_countries.md"
    report.write_text("\n\n".join(sections) + "\n", encoding="utf-8")
    log.info("Rapport : %s ; désaccords : %s", report, sample)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
