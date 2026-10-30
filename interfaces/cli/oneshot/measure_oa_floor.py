# STATUS: oneshot (2026-10-30)
"""Simulation du statut open access des publications du périmètre, tiré des copies ouvertes et relevé par le verdict d'Unpaywall.

Le plancher d'une publication vient de sa meilleure copie ouverte. Les fiches de catalogue sont écartées, comme à la normalisation. Une copie d'archive ou de serveur de preprints donne `green`. Une autre copie ouverte est comptée côté éditeur : le modèle de la revue décide. Une revue `full_oa` donne `gold`, une revue `diamond` donne `diamond`. Une revue `subscription` donne `hybrid` avec une licence ouverte, `bronze` sans. Le verdict d'Unpaywall relève ce plancher, jamais ne l'abaisse. Un `gold` d'Unpaywall dans une revue `diamond` devient `diamond`.

Chaque étape est rejouable séparément :

- `simulate` écrit, pour chaque publication, son statut actuel et le statut simulé, puis affiche la matrice des passages.
- `hosts` lit ce fichier et liste les domaines des copies ouvertes des publications d'une ou plusieurs transitions (`closed>green`…).

Le script n'écrit pas dans la base.

Usage :
    uv run python -m interfaces.cli.oneshot.measure_oa_floor simulate
    uv run python -m interfaces.cli.oneshot.measure_oa_floor hosts "green>bronze" ["closed>green" …]
"""

import argparse
import csv
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import Connection, text

from domain.platforms.platform import PlatformType, is_catalog_record
from domain.platforms.registry import platform_type_of_copy
from domain.publications.metadata import OA_RANK
from infrastructure.db.engine import build_sync_engine

_DEFAULT_OUTPUT = Path("data/measures/oa_floor.tsv")
_ARCHIVE_TYPES = frozenset({PlatformType.REPOSITORY, PlatformType.PREPRINT_SERVER})
_OPEN_LICENSE_PREFIXES = ("cc", "public_domain", "pd")

_PUBLICATIONS = text("""
    SELECT p.id, p.oa_status::text AS cur, p.doc_type::text AS doc_type, u.oa_status::text AS upw,
           s.oa_model::text AS oa_model
    FROM publications p
    LEFT JOIN sources.unpaywall u ON u.doi = p.doi::text
    LEFT JOIN serials s ON s.id = p.serial_id
    WHERE p.in_perimeter
""")

_OPEN_COPIES = text("""
    SELECT sr.publication_id AS pid, sr.source::text AS source, l.url, l.license::text AS license,
           pl.openalex_id, pl.platform_type::text AS ptype, pl.name
    FROM source_record_locations l
    JOIN source_records sr ON sr.id = l.source_record_id
    JOIN publications p ON p.id = sr.publication_id AND p.in_perimeter
    LEFT JOIN platforms pl ON pl.id = l.platform_id
    WHERE l.is_oa AND (CAST(:ids AS int[]) IS NULL OR sr.publication_id = ANY(:ids))
""")


def _is_archive(url: str, openalex_id: str | None, ptype: str | None) -> bool:
    """Vrai pour une copie d'archive ou de serveur de preprints, d'après le registre des plateformes, à défaut la plateforme OpenAlex."""
    platform_type = platform_type_of_copy(url, openalex_id) or (
        PlatformType(ptype) if ptype else None
    )
    return platform_type in _ARCHIVE_TYPES


def _rank_max(*statuses: str) -> str:
    return max(statuses, key=lambda s: OA_RANK[s])


def _floor(p, copies: Sequence[tuple[bool, bool]]) -> str:
    """Renvoie le statut tiré des copies ouvertes `(archive, licence ouverte)` et du modèle de la revue."""
    best = "closed"
    if any(archive for archive, _ in copies):
        best = "green"
    publisher_side = [licensed for archive, licensed in copies if not archive]
    if publisher_side:
        if p.oa_model == "diamond":
            best = "diamond"
        elif p.oa_model == "full_oa":
            best = "gold"
        elif p.oa_model == "subscription":
            best = "hybrid" if any(publisher_side) else "bronze"
        else:
            best = _rank_max(best, "bronze")
    return best


def _simulated(p, copies: Sequence[tuple[bool, bool]]) -> str:
    """Renvoie le plancher des copies, relevé par le verdict d'Unpaywall. Sans copie ouverte ni verdict, le statut est fermé, ou inconnu s'il l'est déjà."""
    if not copies and p.upw is None:
        return "unknown" if p.cur == "unknown" else "closed"
    verdict = p.upw or "closed"
    if verdict == "gold" and p.oa_model == "diamond":
        verdict = "diamond"
    return _rank_max(_floor(p, copies), verdict)


def simulate(conn: Connection, output: Path) -> None:
    """Écrit le statut actuel et le statut simulé de chaque publication, puis affiche la matrice des passages."""
    copies: dict[int, list[tuple[bool, bool]]] = defaultdict(list)
    for r in conn.execute(_OPEN_COPIES, {"ids": None}):
        if is_catalog_record(r.url):
            continue
        licensed = bool(r.license) and r.license.lower().startswith(_OPEN_LICENSE_PREFIXES)
        copies[r.pid].append((_is_archive(r.url, r.openalex_id, r.ptype), licensed))
    matrix: Counter[tuple[str, str]] = Counter()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(["id", "actuel", "simule", "unpaywall", "doc_type", "oa_model"])
        for p in conn.execute(_PUBLICATIONS):
            new = _simulated(p, copies.get(p.id, []))
            matrix[(p.cur, new)] += 1
            writer.writerow([p.id, p.cur, new, p.upw, p.doc_type, p.oa_model])
    total = sum(matrix.values())
    same = sum(n for (cur, new), n in matrix.items() if cur == new)
    print(f"{total} publications, {same} au statut inchangé ({100 * same / total:.1f} %)")
    for (cur, new), n in matrix.most_common():
        if cur != new:
            print(f"  {cur:10s} -> {new:10s} {n}")


def hosts(conn: Connection, output: Path, transitions: Sequence[str]) -> None:
    """Liste les domaines des copies ouvertes des publications passées par l'une des transitions `actuel>simulé`."""
    wanted = {tuple(t.split(">")) for t in transitions}
    with output.open(encoding="utf-8") as fh:
        ids = [
            int(r["id"])
            for r in csv.DictReader(fh, delimiter="\t")
            if (r["actuel"], r["simule"]) in wanted
        ]
    print(f"{len(ids)} publications")
    counts: Counter[str] = Counter()
    examples: dict[str, str] = {}
    for r in conn.execute(_OPEN_COPIES, {"ids": ids}):
        kind = "archive" if _is_archive(r.url, r.openalex_id, r.ptype) else "autre"
        key = f"{r.source} {kind} {urlparse(r.url).netloc} [{r.name or '-'}]"
        counts[key] += 1
        examples.setdefault(key, r.url)
    for key, n in counts.most_common(30):
        print(f"{n:6d}  {key}  {examples[key]}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT)
    sub = parser.add_subparsers(dest="step", required=True)
    sub.add_parser("simulate")
    hosts_parser = sub.add_parser("hosts")
    hosts_parser.add_argument("transitions", nargs="+")
    args = parser.parse_args()
    with build_sync_engine().connect() as conn:
        if args.step == "simulate":
            simulate(conn, args.output)
        else:
            hosts(conn, args.output, args.transitions)


if __name__ == "__main__":
    main()
