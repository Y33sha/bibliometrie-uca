# STATUS: oneshot (2026-11-05)
"""Ajout des colonnes « Citations » et « FWCI » aux listes CSV des rapports bibliométriques par unité, avec les valeurs des tableaux d'impact de ces rapports.

Dans ces tableaux, le nombre de citations d'une publication est le maximum des nombres de citations de ses enregistrements sources. Le FWCI est le maximum des FWCI de ses enregistrements sources OpenAlex. Les deux colonnes s'insèrent devant « Top citations ».

Une ligne du CSV désigne une publication par les liens de sa colonne « Sources », à défaut par son DOI. Une ligne sans publication, ou rattachée à plusieurs publications, garde des cellules vides et figure dans le bilan. Un fichier pourvu de la colonne « Citations » reste intact.

Usage :
    uv run python -m interfaces.cli.oneshot.add_impact_columns_to_reports [--dry-run] DOSSIER
"""

import argparse
import csv
import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from sqlalchemy import Connection, text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("add_impact_columns_to_reports", os.path.dirname(__file__))

CITATIONS = "Citations"
FWCI = "FWCI"
BEFORE = "Top citations"
DOI_PREFIX = "https://doi.org/"


@dataclass(frozen=True, slots=True)
class RowKeys:
    source_ids: tuple[tuple[str, str], ...]
    """Couples `(source, identifiant)` tirés des liens de la colonne « Sources »."""
    doi: str | None


def row_keys(row: dict[str, str]) -> RowKeys:
    """Identifiants de la publication d'une ligne. Le dernier segment d'un lien vers une source est l'identifiant encodé."""
    links: dict[str, str] = json.loads(row["Sources"]) if row.get("Sources") else {}
    doi = row.get("DOI", "").removeprefix(DOI_PREFIX) or None
    return RowKeys(
        tuple((source, unquote(url.rsplit("/", 1)[1])) for source, url in links.items()),
        doi,
    )


def publications_by_source_id(
    conn: Connection, keys: set[tuple[str, str]]
) -> dict[tuple[str, str], int]:
    rows = conn.execute(
        text("""
            SELECT sr.source::text AS source, sr.source_id, sr.publication_id
            FROM source_records sr
            JOIN unnest(CAST(:sources AS text[]), CAST(:ids AS text[])) AS k(source, source_id)
              ON sr.source::text = k.source AND sr.source_id = k.source_id
            WHERE sr.publication_id IS NOT NULL
        """),
        {"sources": [s for s, _ in keys], "ids": [i for _, i in keys]},
    ).all()
    return {(r.source, r.source_id): r.publication_id for r in rows}


def publications_by_doi(conn: Connection, dois: set[str]) -> dict[str, set[int]]:
    rows = conn.execute(
        text("SELECT doi, id FROM publications WHERE doi = ANY(:dois)"),
        {"dois": list(dois)},
    ).all()
    found: dict[str, set[int]] = {}
    for r in rows:
        found.setdefault(r.doi, set()).add(r.id)
    return found


@dataclass(frozen=True, slots=True)
class ReportImpact:
    citations: int | None
    fwci: float | None


def report_impacts(conn: Connection, publication_ids: set[int]) -> dict[int, ReportImpact]:
    """Citations et FWCI des publications, calculés comme dans les tableaux d'impact des rapports."""
    rows = conn.execute(
        text("""
            SELECT sp.publication_id,
                   max((sp.impact->>'cited_by_count')::int) AS citations,
                   max((sp.impact->>'fwci')::float) FILTER (WHERE sp.source = 'openalex') AS fwci
            FROM source_records sp
            WHERE sp.publication_id = ANY(:ids)
            GROUP BY 1
        """),
        {"ids": list(publication_ids)},
    ).all()
    return {r.publication_id: ReportImpact(r.citations, r.fwci) for r in rows}


def format_fwci(fwci: float | None) -> str:
    return "" if fwci is None else f"{fwci:.2f}"


@dataclass(slots=True)
class FileReport:
    rows: int = 0
    unmatched: int = 0
    ambiguous: int = 0


def add_columns(conn: Connection, path: Path, *, dry_run: bool) -> FileReport | None:
    """Ajoute les deux colonnes au CSV `path`. Renvoie `None` pour un fichier déjà pourvu des colonnes."""
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = list(reader.fieldnames or [])
        rows = list(reader)
    if CITATIONS in header:
        return None

    keys = [row_keys(row) for row in rows]
    by_source_id = publications_by_source_id(conn, {k for ks in keys for k in ks.source_ids})
    by_doi = publications_by_doi(conn, {ks.doi for ks in keys if ks.doi})
    matches = [
        {by_source_id[k] for k in ks.source_ids if k in by_source_id}
        or (by_doi.get(ks.doi, set()) if ks.doi else set())
        for ks in keys
    ]
    impacts = report_impacts(conn, {pid for m in matches for pid in m})

    report = FileReport(rows=len(rows))
    for row, match in zip(rows, matches, strict=True):
        impact = ReportImpact(None, None)
        if not match:
            report.unmatched += 1
            log.warning("%s : sans publication : %s", path.name, row.get("Titre"))
        elif len(match) > 1:
            report.ambiguous += 1
            log.warning(
                "%s : plusieurs publications %s : %s", path.name, sorted(match), row.get("Titre")
            )
        else:
            impact = impacts.get(next(iter(match)), impact)
        row[CITATIONS] = "" if impact.citations is None else str(impact.citations)
        row[FWCI] = format_fwci(impact.fwci)

    position = header.index(BEFORE)
    header[position:position] = [CITATIONS, FWCI]
    if not dry_run:
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            writer.writerows(rows)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory", type=Path, help="dossier des rapports, parcouru récursivement")
    parser.add_argument("--dry-run", action="store_true", help="bilan sans écriture")
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        for path in sorted(args.directory.rglob("*.csv")):
            report = add_columns(conn, path, dry_run=args.dry_run)
            if report is None:
                log.info("%s : colonnes déjà présentes", path)
            else:
                log.info(
                    "%s : %d lignes, %d sans publication, %d rattachées à plusieurs publications",
                    path,
                    report.rows,
                    report.unmatched,
                    report.ambiguous,
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
