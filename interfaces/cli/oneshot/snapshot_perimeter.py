# STATUS: oneshot (2026-10-16)
"""Instantané (lecture seule) du périmètre et des pays, pour quantifier l'effet d'une renormalisation du stock.

L'instantané garde, à chaque niveau, les indices d'entrée dans le périmètre et les structures atteintes :

- contributions sources du périmètre ou rattachées à une structure : source, indices, couples (structure, indice) de `source_contribution_structures` ;
- contributions du périmètre, par couple (publication, personne) : indices ;
- publications : type, indices, structures (`publication_structures`), pays, titre ;
- adresses : nombre total, nombre sans contribution source.

L'instantané s'écrit en JSON compressé sous `data/snapshots/`. `--compare` confronte deux instantanés : entrées et sorties du périmètre, structures gagnées et perdues, pays gagnés, perdus et changés. Une contribution source absente du second instantané est cherchée en base, pour distinguer une contribution source supprimée d'une contribution source sortie du périmètre : la comparaison se lance donc sur la base dans l'état du second instantané.

Usage :
    uv run python -m interfaces.cli.oneshot.snapshot_perimeter
    uv run python -m interfaces.cli.oneshot.snapshot_perimeter --compare AVANT.json.gz APRES.json.gz
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("snapshot_perimeter", os.path.dirname(__file__))

_SNAPSHOTS = Path("data/snapshots")
_EXAMPLES = 5

_SOURCE_CONTRIBUTIONS = text("""
    WITH ids AS (
        SELECT id FROM source_contributions WHERE in_perimeter = true
        UNION
        SELECT DISTINCT source_contribution_id FROM source_contribution_structures
    )
    SELECT sc.id, sr.source::text AS source, sc.perimeter_evidence::text[] AS evidence
    FROM ids
    JOIN source_contributions sc ON sc.id = ids.id
    JOIN source_records sr ON sr.id = sc.source_record_id
""")

_SOURCE_CONTRIBUTION_STRUCTURES = text("""
    SELECT source_contribution_id, structure_id, evidence::text AS evidence
    FROM source_contribution_structures
""")

_CONTRIBUTIONS = text("""
    SELECT publication_id, person_id, perimeter_evidence::text[] AS evidence
    FROM contributions
    WHERE in_perimeter AND person_id IS NOT NULL
""")

_PUBLICATIONS = text("""
    SELECT p.id, p.doc_type::text AS doc_type, p.perimeter_evidence::text[] AS evidence,
           coalesce(ps.structure_ids, '{}') AS structure_ids,
           coalesce(p.countries, '{}') AS countries, left(p.title, 120) AS title
    FROM publications p
    LEFT JOIN (
        SELECT publication_id, array_agg(structure_id ORDER BY structure_id) AS structure_ids
        FROM publication_structures
        GROUP BY publication_id
    ) ps ON ps.publication_id = p.id
""")

_ADDRESSES = text("""
    SELECT count(*) AS total,
           count(*) FILTER (WHERE NOT EXISTS (
               SELECT 1 FROM source_contribution_addresses sca WHERE sca.address_id = a.id
           )) AS orphans
    FROM addresses a
""")

Snapshot = dict[str, Any]
"""`{"signatures": {id: [source, indices, [[structure_id, indice], …]]}, "contributions": {"publication:personne": indices}, "publications": {id: [type, indices, structures, pays, titre]}, "addresses": {"total": n, "orphans": n}}`"""


def snapshot() -> Snapshot:
    with get_sync_engine().connect() as conn:
        log.info("Contributions sources…")
        structures: defaultdict[int, list[list[object]]] = defaultdict(list)
        for r in conn.execute(_SOURCE_CONTRIBUTION_STRUCTURES):
            structures[r.source_contribution_id].append([r.structure_id, r.evidence])
        source_contributions = {
            str(r.id): [r.source, sorted(r.evidence), sorted(structures.get(r.id, []))]
            for r in conn.execute(_SOURCE_CONTRIBUTIONS)
        }
        log.info("Contributions…")
        contributions = {
            f"{r.publication_id}:{r.person_id}": sorted(r.evidence)
            for r in conn.execute(_CONTRIBUTIONS)
        }
        log.info("Publications…")
        publications = {
            str(r.id): [
                r.doc_type,
                sorted(r.evidence),
                list(r.structure_ids),
                sorted(r.countries),
                r.title,
            ]
            for r in conn.execute(_PUBLICATIONS)
        }
        addresses = conn.execute(_ADDRESSES).one()._asdict()
    return {
        "signatures": source_contributions,
        "contributions": contributions,
        "publications": publications,
        "addresses": addresses,
    }


def _in_perimeter(evidence: list[str] | None) -> bool:
    return bool(evidence)


def _log_tally(title: str, tally: Counter[str]) -> None:
    log.info("  %s : %d", title, sum(tally.values()))
    for key, n in tally.most_common():
        log.info("    %-50s %7d", key, n)


def _structure_labels(conn: Connection, ids: Iterable[int]) -> dict[int, str]:
    rows = conn.execute(
        text("SELECT id, coalesce(acronym, name) AS label FROM structures WHERE id = ANY(:ids)"),
        {"ids": sorted(set(ids))},
    )
    return {r.id: r.label for r in rows}


def _existing_source_contributions(conn: Connection, ids: Iterable[str]) -> set[str]:
    rows = conn.execute(
        text("SELECT id FROM source_contributions WHERE id = ANY(CAST(:ids AS int[]))"),
        {"ids": sorted(int(i) for i in ids)},
    )
    return {str(r.id) for r in rows}


def _compare_source_contributions(conn: Connection, before: Snapshot, after: Snapshot) -> None:
    b, a = before["signatures"], after["signatures"]
    in_b = {k for k, v in b.items() if _in_perimeter(v[1])}
    in_a = {k for k, v in a.items() if _in_perimeter(v[1])}
    log.info(
        "─── Contributions sources du périmètre : %d avant, %d après ───", len(in_b), len(in_a)
    )

    existing = _existing_source_contributions(conn, in_b - in_a)
    _log_tally("entrées, par source", Counter(a[k][0] for k in in_a - in_b))
    _log_tally("supprimées, par source", Counter(b[k][0] for k in in_b - in_a - existing))
    _log_tally("sorties, par source", Counter(b[k][0] for k in (in_b - in_a) & existing))

    gained: Counter[str] = Counter()
    lost: Counter[str] = Counter()
    evidence_changes: Counter[str] = Counter()
    for key in b.keys() & a.keys():
        sb, sa_ = b[key], a[key]
        if sb[1] != sa_[1]:
            evidence_changes[f"{sb[0]} {'+'.join(sb[1]) or '∅'} → {'+'.join(sa_[1]) or '∅'}"] += 1
        before_links = {tuple(x) for x in sb[2]}
        after_links = {tuple(x) for x in sa_[2]}
        for _, evidence in after_links - before_links:
            gained[f"{sa_[0]} {evidence}"] += 1
        for _, evidence in before_links - after_links:
            lost[f"{sb[0]} {evidence}"] += 1
    _log_tally("contributions sources dont les indices changent", evidence_changes)
    _log_tally("liens à une structure gagnés, par source et indice", gained)
    _log_tally("liens à une structure perdus, par source et indice", lost)


def _compare_contributions(before: Snapshot, after: Snapshot) -> None:
    b, a = before["contributions"], after["contributions"]
    log.info("─── Contributions du périmètre : %d avant, %d après ───", len(b), len(a))
    log.info("  entrées : %d, sorties : %d", len(a.keys() - b.keys()), len(b.keys() - a.keys()))
    changes = Counter(
        f"{'+'.join(b[k])} → {'+'.join(a[k])}" for k in b.keys() & a.keys() if b[k] != a[k]
    )
    _log_tally("contributions dont les indices changent", changes)


def _describe_publication(key: str, record: list[Any]) -> str:
    return f"{key} ({record[0]}) « {record[4]} »"


def _compare_publications(conn: Connection, before: Snapshot, after: Snapshot) -> None:
    b, a = before["publications"], after["publications"]
    in_b = {k for k, v in b.items() if _in_perimeter(v[1])}
    in_a = {k for k, v in a.items() if _in_perimeter(v[1])}
    log.info("─── Publications du périmètre : %d avant, %d après ───", len(in_b), len(in_a))
    for title, keys, side in (
        ("entrées", in_a - in_b, a),
        ("sorties", (in_b - in_a) & a.keys(), b),
        ("supprimées", in_b - a.keys(), b),
    ):
        _log_tally(f"{title}, par type", Counter(side[k][0] for k in keys))
        for key in sorted(keys)[:_EXAMPLES]:
            log.info("    · %s", _describe_publication(key, side[key]))

    common = (in_b | in_a) & b.keys() & a.keys()
    structure_changes: Counter[str] = Counter()
    structure_moves: Counter[tuple[int, str]] = Counter()
    examples: defaultdict[str, list[str]] = defaultdict(list)
    for key in sorted(common):
        sb, sa_ = set(b[key][2]), set(a[key][2])
        if sb == sa_:
            continue
        change = (
            "structures gagnées"
            if sb < sa_
            else "structures perdues"
            if sa_ < sb
            else "structures remplacées"
        )
        label = f"{a[key][0]} : {change}"
        structure_changes[label] += 1
        for s in sa_ - sb:
            structure_moves[(s, "gagnée")] += 1
        for s in sb - sa_:
            structure_moves[(s, "perdue")] += 1
        if len(examples[label]) < _EXAMPLES:
            examples[label].append(
                f"{_describe_publication(key, a[key])} : {sorted(sb)} → {sorted(sa_)}"
            )
    _log_tally("publications dont les structures changent, par type", structure_changes)
    for label, lines in examples.items():
        log.info("  %s", label)
        for line in lines:
            log.info("    · %s", line)
    labels = _structure_labels(conn, (s for s, _ in structure_moves))
    _log_tally(
        "structures gagnées et perdues",
        Counter({f"{labels.get(s, s)} {way}": n for (s, way), n in structure_moves.items()}),
    )


def _compare_countries(before: Snapshot, after: Snapshot) -> None:
    b, a = before["publications"], after["publications"]
    log.info("─── Pays des publications ───")
    tally: Counter[str] = Counter()
    examples: defaultdict[str, list[str]] = defaultdict(list)
    for key in sorted(b.keys() & a.keys()):
        cb, ca = set(b[key][3]), set(a[key][3])
        if cb == ca:
            continue
        change = "pays gagnés" if cb < ca else "pays perdus" if ca < cb else "pays changés"
        scope = "périmètre" if _in_perimeter(a[key][1]) else "hors périmètre"
        label = f"{change} ({scope})"
        tally[label] += 1
        if len(examples[label]) < _EXAMPLES:
            examples[label].append(
                f"{_describe_publication(key, a[key])} : {sorted(cb)} → {sorted(ca)}"
            )
    _log_tally("publications dont les pays changent", tally)
    for label, lines in examples.items():
        log.info("  %s", label)
        for line in lines:
            log.info("    · %s", line)


def _compare(before: Snapshot, after: Snapshot) -> None:
    log.info("─── Adresses : %s avant, %s après ───", before["addresses"], after["addresses"])
    with get_sync_engine().connect() as conn:
        _compare_source_contributions(conn, before, after)
        _compare_contributions(before, after)
        _compare_publications(conn, before, after)
    _compare_countries(before, after)


def _load(path: str) -> Snapshot:
    return json.loads(gzip.decompress(Path(path).read_bytes()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compare", nargs=2, metavar=("AVANT", "APRES"))
    args = parser.parse_args()
    if args.compare:
        _compare(_load(args.compare[0]), _load(args.compare[1]))
        return 0
    data = snapshot()
    _SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    path = _SNAPSHOTS / f"perimeter_{datetime.now(UTC):%Y%m%d_%H%M}.json.gz"
    path.write_bytes(gzip.compress(json.dumps(data, ensure_ascii=False).encode()))
    log.info(
        "Instantané écrit : %s (%d contributions sources, %d contributions, %d publications)",
        path,
        len(data["signatures"]),
        len(data["contributions"]),
        len(data["publications"]),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
