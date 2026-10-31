# STATUS: oneshot (2026-10-31)
"""Mesure du statut open access des publications du périmètre déduit de leurs copies, de leur revue et du verdict d'Unpaywall.

Arbre de décision :

1. Copie ouverte chez l'éditeur, sous licence ouverte : `hybrid` pour une revue absente du DOAJ, `diamond` pour une revue du DOAJ sans APC, `gold` avec APC.
2. Sinon, copie d'archive ou de serveur de preprints ouverte : `green`.
3. Sinon, copie ouverte chez l'éditeur sans licence ouverte : `bronze`.
4. Sinon : `embargoed` avec une copie sous embargo actif ou l'embargo déclaré par theses.fr ; `closed` avec une copie, un verdict ou un statut `closed` déclaré ; `unknown` sans rien.

Le verdict d'Unpaywall relève les copies : `gold`, `hybrid` ou `diamond` valent une copie ouverte chez l'éditeur sous licence, `bronze` une copie ouverte chez l'éditeur sans licence, `green` une copie d'archive ouverte.

Les copies ouvertes suivent `open_copies`. Les pages descriptives sont écartées. Pour une communication ou un poster, un dépôt HAL à annexe compte comme copie d'archive ouverte, d'après l'API HAL (`data/measures/hal_annexes.tsv`, écrit par `data/measures/fetch_hal_annexes.py`).

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

from domain.platforms.platform import PlatformType, is_descriptive_page
from domain.publications.access import Copy, open_copies
from domain.publications.identifiers import extract_hal_id_from_url
from domain.publications.licenses import OPEN_LICENSES
from domain.publications.metadata import OA_RANK
from domain.sources.registry import Source
from infrastructure.db.engine import build_sync_engine
from infrastructure.read_models.publications.copies import publication_copies

_DEFAULT_OUTPUT = Path("data/measures/oa_floor.tsv")
_ARCHIVE_TYPES = frozenset({PlatformType.REPOSITORY, PlatformType.PREPRINT_SERVER})
_ANNEX_DOC_TYPES = frozenset({"conference", "poster"})

_PUBLICATIONS = text("""
    SELECT p.id, p.oa_status::text AS cur, u.oa_status::text AS upw, p.doc_type::text AS doc_type,
           coalesce(s.is_in_doaj, false) AS in_doaj, s.oa_model::text AS oa_model
    FROM publications p
    LEFT JOIN sources.unpaywall u ON u.doi = lower(p.doi::text)
    LEFT JOIN serials s ON s.id = p.serial_id
    WHERE p.in_perimeter
""")

_DECLARED = text("""
    SELECT sr.publication_id AS pid, sr.source::text AS source, sr.oa_status::text AS oa_status
    FROM source_records sr JOIN publications p ON p.id = sr.publication_id AND p.in_perimeter
    WHERE sr.oa_status IN ('closed', 'embargoed')
""")

_EMBARGOED = text("""
    SELECT DISTINCT sr.publication_id AS pid
    FROM source_record_locations l
    JOIN source_records sr ON sr.id = l.source_record_id
    JOIN publications p ON p.id = sr.publication_id AND p.in_perimeter
    WHERE l.embargo_until > current_date
""")


@dataclass(slots=True)
class _Facts:
    id: int
    cur: str
    upw: str | None
    doc_type: str | None
    in_doaj: bool
    oa_model: str | None
    copies: list[Copy] = field(default_factory=list)
    """Copies, ouvertes ou non, hors pages descriptives."""
    declared_closed: bool = False
    theses_embargo: bool = False
    embargoed_copy: bool = False


@dataclass(frozen=True, slots=True)
class _Access:
    """Accès constatés : copie ouverte chez l'éditeur, sous licence ouverte ou non, copie d'archive ouverte."""

    publisher: bool = False
    licensed: bool = False
    archive: bool = False

    def raised_by(self, verdict: str | None) -> _Access:
        if verdict in ("gold", "hybrid", "diamond"):
            return replace(self, publisher=True, licensed=True)
        if verdict == "bronze":
            return replace(self, publisher=True)
        if verdict == "green":
            return replace(self, archive=True)
        return self


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


def _open(f: _Facts) -> list[Copy]:
    copies = open_copies(f.copies)
    if f.doc_type in _ANNEX_DOC_TYPES:
        with_file = _hal_deposits_with_file()
        copies += [
            replace(c, is_oa=True)
            for c in f.copies
            if c.described_by_platform
            and not c.is_oa
            and extract_hal_id_from_url(c.url) in with_file
        ]
    return copies


def _access(f: _Facts) -> _Access:
    copies = _open(f)
    publisher = [c for c in copies if c.platform_type not in _ARCHIVE_TYPES]
    return _Access(
        publisher=bool(publisher),
        licensed=any(c.license in OPEN_LICENSES for c in publisher),
        archive=any(c.platform_type in _ARCHIVE_TYPES for c in copies),
    )


def _status(f: _Facts, access: _Access) -> str:
    if access.publisher and access.licensed:
        if not f.in_doaj:
            return "hybrid"
        return "diamond" if f.oa_model == "diamond" else "gold"
    if access.archive:
        return "green"
    if access.publisher:
        return "bronze"
    if f.embargoed_copy or f.theses_embargo:
        return "embargoed"
    if f.copies or f.upw or f.declared_closed:
        return "closed"
    return "unknown"


def _facts(conn: Connection) -> list[_Facts]:
    facts = {
        r.id: _Facts(r.id, r.cur or "unknown", r.upw, r.doc_type, r.in_doaj, r.oa_model)
        for r in conn.execute(_PUBLICATIONS)
    }
    for r in conn.execute(_DECLARED):
        if r.oa_status == "closed":
            facts[r.pid].declared_closed = True
        elif r.source == Source.THESES:
            facts[r.pid].theses_embargo = True
    for r in conn.execute(_EMBARGOED):
        facts[r.pid].embargoed_copy = True
    for pid, copies in publication_copies(conn, list(facts)).items():
        facts[pid].copies = [c for c in copies if not is_descriptive_page(c.url)]
    return list(facts.values())


def _print_transitions(title: str, before: Sequence[str], after: Sequence[str]) -> None:
    matrix = Counter((b, a) for b, a in zip(before, after, strict=True) if b != a)
    print(f"\n{title} : {sum(matrix.values())} publications changent de statut")
    for (b, a), n in matrix.most_common(20):
        print(f"  {b:10s} -> {a:10s} {n}")


def _print_unpaywall_agreement(facts: Sequence[_Facts], accesses: Sequence[_Access]) -> None:
    """Confronte les copies seules au verdict d'Unpaywall, sur les publications à verdict."""
    open_level = Counter()
    publisher_level = Counter()
    for f, a in zip(facts, accesses, strict=True):
        if f.upw is None:
            continue
        copies_open = a.publisher or a.archive
        verdict_open = f.upw in ("gold", "hybrid", "diamond", "bronze", "green")
        open_level[(copies_open, verdict_open)] += 1
        if copies_open and verdict_open:
            verdict_publisher = f.upw != "green"
            publisher_level[(a.publisher, verdict_publisher)] += 1
    label = {True: "ouvert", False: "fermé"}
    print("\nAccord avec Unpaywall, ouvert ou fermé (copies seules / verdict)")
    for (c, v), n in sorted(open_level.items(), key=lambda x: -x[1]):
        print(f"  copies {label[c]:7s} / verdict {label[v]:7s} {n}")
    side = {True: "éditeur ouvert", False: "archive seule"}
    print("\nAccord avec Unpaywall, publications ouvertes des deux côtés (copies / verdict)")
    for (c, v), n in sorted(publisher_level.items(), key=lambda x: -x[1]):
        print(f"  copies {side[c]:15s} / verdict {side[v]:15s} {n}")


def simulate(conn: Connection, output: Path) -> None:
    """Écrit le statut actuel, le statut des copies seules et le statut relevé par Unpaywall de chaque publication, puis affiche les passages, la répartition et l'accord avec Unpaywall."""
    facts = _facts(conn)
    accesses = [_access(f) for f in facts]
    columns = {
        "actuel": [f.cur for f in facts],
        "copies": [_status(f, a) for f, a in zip(facts, accesses, strict=True)],
        "copies_unpaywall": [
            _status(f, a.raised_by(f.upw)) for f, a in zip(facts, accesses, strict=True)
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(["id", "unpaywall", "doc_type", *columns])
        for i, f in enumerate(facts):
            writer.writerow([f.id, f.upw, f.doc_type, *(col[i] for col in columns.values())])
    print(f"{len(facts)} publications")
    _print_transitions("actuel -> copies seules", columns["actuel"], columns["copies"])
    _print_transitions(
        "copies seules -> relevé par Unpaywall", columns["copies"], columns["copies_unpaywall"]
    )
    print("\nRépartition : actuel, copies seules, relevé par Unpaywall")
    for status in sorted(OA_RANK, key=OA_RANK.__getitem__, reverse=True):
        counts = [col.count(status) for col in columns.values()]
        print(f"  {status:10s} " + " ".join(f"{n:7d}" for n in counts))
    _print_unpaywall_agreement(facts, accesses)


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
