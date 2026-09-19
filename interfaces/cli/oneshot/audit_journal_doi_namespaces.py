# STATUS: oneshot (2026-09-19)
"""Audit des espaces de noms DOI des revues, avant leur table.

Apprend les espaces de noms (`domain.journals.doi_namespaces`) sur les couples (DOI, revue) de tous les enregistrements, puis mesure leurs trois usages :

1. enregistrements sans revue dont le DOI tombe dans un espace retenu, et publications sans revue qui en recevraient une ;
2. paires de revues qui se partagent un espace de noms, candidates à la fusion ;
3. enregistrements dont la revue contredit l'espace de noms de leur DOI.

Lecture seule.

Usage :
    python -m interfaces.cli.oneshot.audit_journal_doi_namespaces [--min-dois 5] [--min-share 0.9]
"""

from __future__ import annotations

import argparse
import os
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence

from sqlalchemy import Row, text

from domain.journals.doi_namespaces import (
    DoiNamespace,
    learn_namespaces,
    namespace_candidates,
    resolve_journal,
)
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("audit_journal_doi_namespaces", os.path.dirname(__file__))

_RECORDS = text("""
    SELECT s.id, s.source::text AS source, s.doi, s.journal_id, s.publication_id,
           p.journal_id AS publication_journal_id
    FROM source_publications s
    LEFT JOIN publications p ON p.id = s.publication_id
    WHERE s.doi IS NOT NULL
""")
_TITLES = text("SELECT id, title FROM journals")

type Record = Row[tuple[object, ...]]


def _missing_journals(
    records: Sequence[Record], namespaces: Mapping[str, DoiNamespace], titles: Mapping[int, str]
) -> None:
    attachable = [
        (r, ns)
        for r in records
        if r.journal_id is None and (ns := resolve_journal(r.doi, namespaces)) is not None
    ]
    gained = {
        r.publication_id: ns.journal_id
        for r, ns in attachable
        if r.publication_id and r.publication_journal_id is None
    }
    log.info(
        "1. %d enregistrements sans revue rattachables ; %d publications sans revue en recevraient une",
        len(attachable),
        len(gained),
    )
    by_journal = Counter(gained.values())
    for journal_id, n in by_journal.most_common(20):
        log.info("   %5d → %d « %s »", n, journal_id, titles.get(journal_id))


def _shared_namespaces(
    records: Sequence[Record], titles: Mapping[int, str], *, min_dois: int, min_share: float
) -> None:
    """Deux revues réunissent un espace à plus de `min_share`, et leurs DOI s'y mêlent au niveau suivant (même volume, même année). Deux revues que le niveau suivant sépare (`acs.est.`, `acs.jpcc.`) ne se partagent pas l'espace."""
    votes: dict[str, Counter[int]] = defaultdict(Counter)
    dois: dict[str, set[str]] = defaultdict(set)
    children: dict[str, dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
    for r in records:
        if r.journal_id is None:
            continue
        candidates = namespace_candidates(r.doi)
        for i, candidate in enumerate(candidates):
            votes[candidate][r.journal_id] += 1
            dois[candidate].add(r.doi)
            children[candidate][r.journal_id].add(
                candidates[i + 1] if i + 1 < len(candidates) else r.doi
            )
    pairs: Counter[tuple[int, int]] = Counter()
    examples: dict[tuple[int, int], str] = {}
    for candidate, counter in votes.items():
        total = len(dois[candidate])
        top = counter.most_common(2)
        if total < min_dois or len(top) < 2 or top[1][1] < 2:
            continue
        (a, count_a), (b, count_b) = top
        if (count_a + count_b) / total < min_share or count_a / total >= min_share:
            continue
        if not children[candidate][a] & children[candidate][b]:
            continue
        pair = (min(a, b), max(a, b))
        if pairs[pair] < total:
            pairs[pair] = total
            examples[pair] = candidate
    log.info("2. %d paires de revues qui se partagent un espace de noms", len(pairs))
    for (a, b), n in pairs.most_common(40):
        log.info(
            "   %5d %s : %d « %s » / %d « %s »",
            n,
            examples[(a, b)],
            a,
            titles.get(a),
            b,
            titles.get(b),
        )


def _contradicted_journals(
    records: Sequence[Record], namespaces: Mapping[str, DoiNamespace], titles: Mapping[int, str]
) -> None:
    contradicted = []
    for r in records:
        if r.journal_id is None:
            continue
        ns = resolve_journal(r.doi, namespaces)
        if ns is not None and ns.journal_id != r.journal_id:
            contradicted.append((r, ns))
    log.info("3. %d enregistrements dont la revue contredit l'espace de noms", len(contradicted))
    for source, n in Counter(r.source for r, _ in contradicted).most_common():
        log.info("   %s : %d", source, n)
    for (journal_id, ns_journal), n in Counter(
        (r.journal_id, ns.journal_id) for r, ns in contradicted
    ).most_common(40):
        log.info("   %4d « %s » → « %s »", n, titles.get(journal_id), titles.get(ns_journal))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-dois", type=int, default=5)
    parser.add_argument("--min-share", type=float, default=0.9)
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        records = conn.execute(_RECORDS).all()
        titles = {r.id: r.title for r in conn.execute(_TITLES)}

    namespaces = learn_namespaces(
        ((r.doi, r.journal_id) for r in records if r.journal_id is not None),
        min_dois=args.min_dois,
        min_share=args.min_share,
    )
    per_journal = Counter(ns.journal_id for ns in namespaces.values())
    log.info(
        "%d espaces de noms retenus pour %d revues (%d revues en ont plusieurs)",
        len(namespaces),
        len(per_journal),
        sum(1 for n in per_journal.values() if n > 1),
    )
    _missing_journals(records, namespaces, titles)
    _shared_namespaces(records, titles, min_dois=args.min_dois, min_share=args.min_share)
    _contradicted_journals(records, namespaces, titles)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
