# STATUS: oneshot (2026-10-31)
"""Mesure du statut open access des publications du périmètre déduit de leurs copies, de leur revue et du verdict d'Unpaywall (`domain.publications.open_access`).

Les pages descriptives sont écartées des copies. Pour une communication ou un poster, un dépôt HAL à annexe compte comme copie d'archive ouverte, d'après l'API HAL (`data/measures/hal_annexes.tsv`, écrit par `data/measures/fetch_hal_annexes.py`) : les payloads HAL du stock sont sans annexes.

`simulate` écrit le statut actuel, le statut déduit des copies seules et le statut relevé par Unpaywall de chaque publication. Il affiche les passages, la répartition, et l'accord entre les copies seules et le verdict d'Unpaywall. Le script n'écrit pas dans la base.

Usage :
    uv run python -m interfaces.cli.oneshot.measure_oa_floor simulate
"""

import argparse
import csv
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from functools import cache
from pathlib import Path

from sqlalchemy import Connection, text

from domain.platforms.platform import is_descriptive_page
from domain.publications.access import Copy
from domain.publications.identifiers import extract_hal_id_from_url
from domain.publications.metadata import OA_OPEN_STATUSES, OA_RANK, OaStatus
from domain.publications.open_access import (
    OpenAccessFacts,
    copies_facts,
    decide_oa_status,
    is_restricted,
)
from infrastructure.db.engine import build_sync_engine
from infrastructure.read_models.publications.copies import publication_copies
from infrastructure.sql_fragments import under_active_embargo

_DEFAULT_OUTPUT = Path("data/measures/oa_floor.tsv")
_ANNEX_DOC_TYPES = frozenset({"conference", "poster"})

_PUBLICATIONS = text("""
    SELECT p.id, p.oa_status::text AS cur, u.oa_status::text AS upw, p.doc_type::text AS doc_type,
           p.serial_id IS NOT NULL AS has_serial, s.oa_model::text AS oa_model, p.source_extras
    FROM publications p
    LEFT JOIN sources.unpaywall u ON u.doi = lower(p.doi::text)
    LEFT JOIN serials s ON s.id = p.serial_id
    WHERE p.in_perimeter
""")

_EMBARGOED = text(f"""
    SELECT DISTINCT sr.publication_id AS pid
    FROM source_records sr JOIN publications p ON p.id = sr.publication_id AND p.in_perimeter
    WHERE {under_active_embargo("sr")}
""")


@dataclass(slots=True)
class _Publication:
    id: int
    cur: str
    upw: str | None
    doc_type: str | None
    has_serial: bool
    oa_model: str | None
    restricted: bool
    copies: list[Copy] = field(default_factory=list)
    """Copies, ouvertes ou non, hors pages descriptives."""
    embargoed: bool = False


@cache
def _hal_deposits_with_file() -> frozenset[str]:
    path = Path("data/measures/hal_annexes.tsv")
    if not path.exists():
        return frozenset()
    with path.open(encoding="utf-8") as fh:
        return frozenset(
            r["hal_id"].lower()
            for r in csv.DictReader(fh, delimiter="\t")
            if r["submit_type"] in ("file", "annex")
        )


def _copies(p: _Publication) -> list[Copy]:
    """Renvoie les copies de la publication ; pour une communication ou un poster, la copie d'un dépôt HAL à annexe est ouverte."""
    if p.doc_type not in _ANNEX_DOC_TYPES:
        return p.copies
    with_file = _hal_deposits_with_file()
    return [
        replace(c, is_oa=True)
        if c.described_by_platform and extract_hal_id_from_url(c.url) in with_file
        else c
        for c in p.copies
    ]


def _facts(p: _Publication) -> OpenAccessFacts:
    facts = copies_facts(_copies(p))
    return replace(
        facts,
        embargoed=p.embargoed,
        informed=facts.informed or p.restricted,
    )


def _status(p: _Publication, facts: OpenAccessFacts) -> str:
    return decide_oa_status(facts, has_serial=p.has_serial, serial_oa_model=p.oa_model)


def _publications(conn: Connection) -> list[_Publication]:
    publications = {
        r.id: _Publication(
            r.id,
            r.cur or "unknown",
            r.upw,
            r.doc_type,
            r.has_serial,
            r.oa_model,
            is_restricted(r.doc_type, r.source_extras),
        )
        for r in conn.execute(_PUBLICATIONS)
    }
    for r in conn.execute(_EMBARGOED):
        publications[r.pid].embargoed = True
    for pid, copies in publication_copies(conn, list(publications)).items():
        publications[pid].copies = [c for c in copies if not is_descriptive_page(c.url)]
    return list(publications.values())


def _print_transitions(title: str, before: Sequence[str], after: Sequence[str]) -> None:
    matrix = Counter((b, a) for b, a in zip(before, after, strict=True) if b != a)
    print(f"\n{title} : {sum(matrix.values())} publications changent de statut")
    for (b, a), n in matrix.most_common(20):
        print(f"  {b:10s} -> {a:10s} {n}")


def _print_unpaywall_agreement(
    publications: Sequence[_Publication], facts: Sequence[OpenAccessFacts]
) -> None:
    """Confronte les copies seules au verdict d'Unpaywall, sur les publications à verdict."""
    open_level: Counter[tuple[bool, bool]] = Counter()
    publisher_level: Counter[tuple[bool, bool]] = Counter()
    for p, f in zip(publications, facts, strict=True):
        if p.upw is None:
            continue
        copies_open = f.publisher_open or f.archive_open
        verdict_open = p.upw in OA_OPEN_STATUSES
        open_level[(copies_open, verdict_open)] += 1
        if copies_open and verdict_open:
            publisher_level[(f.publisher_open, p.upw != OaStatus.GREEN)] += 1
    label = {True: "ouvert", False: "fermé"}
    print("\nAccord avec Unpaywall, ouvert ou fermé (copies seules / verdict)")
    for (c, v), n in open_level.most_common():
        print(f"  copies {label[c]:7s} / verdict {label[v]:7s} {n}")
    side = {True: "éditeur ouvert", False: "archive seule"}
    print("\nAccord avec Unpaywall, publications ouvertes des deux côtés (copies / verdict)")
    for (c, v), n in publisher_level.most_common():
        print(f"  copies {side[c]:15s} / verdict {side[v]:15s} {n}")


def simulate(conn: Connection, output: Path) -> None:
    """Écrit le statut actuel, le statut des copies seules et le statut relevé par Unpaywall de chaque publication, puis affiche les passages, la répartition et l'accord avec Unpaywall."""
    publications = _publications(conn)
    facts = [_facts(p) for p in publications]
    columns = {
        "actuel": [p.cur for p in publications],
        "copies": [_status(p, f) for p, f in zip(publications, facts, strict=True)],
        "copies_unpaywall": [
            _status(p, f.raised_by(p.upw)) for p, f in zip(publications, facts, strict=True)
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(["id", "unpaywall", "doc_type", *columns])
        for i, p in enumerate(publications):
            writer.writerow([p.id, p.upw, p.doc_type, *(col[i] for col in columns.values())])
    print(f"{len(publications)} publications")
    _print_transitions("actuel -> copies seules", columns["actuel"], columns["copies"])
    _print_transitions(
        "copies seules -> relevé par Unpaywall", columns["copies"], columns["copies_unpaywall"]
    )
    print("\nRépartition : actuel, copies seules, relevé par Unpaywall")
    for status in sorted(OA_RANK, key=OA_RANK.__getitem__, reverse=True):
        counts = [col.count(status) for col in columns.values()]
        print(f"  {status:10s} " + " ".join(f"{n:7d}" for n in counts))
    _print_unpaywall_agreement(publications, facts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT)
    sub = parser.add_subparsers(dest="step", required=True)
    sub.add_parser("simulate")
    args = parser.parse_args()
    with build_sync_engine().connect() as conn:
        simulate(conn, args.output)


if __name__ == "__main__":
    main()
