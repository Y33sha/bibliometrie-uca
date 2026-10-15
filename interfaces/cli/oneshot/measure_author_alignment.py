# STATUS: oneshot (2026-10-15)
"""Alignement des listes d'auteurs d'une même publication entre sources : mesure, phase 1 du chantier `DATA_alignement-auteurs.md`.

Pour chaque publication dont les notices viennent d'au moins deux sources, et pour chaque paire de notices de sources différentes :

- longueur des deux listes d'auteurs ;
- accord de la position : une signature de la première notice trouve-t-elle, dans la seconde, un nom compatible (`names_compatible`) à la même position, à une autre position, ou nulle part ;
- accord des identifiants forts (`STRONG_IDENTIFIER_TYPES`, hors identifiants neutralisés) : deux signatures qui partagent un identifiant sont-elles à la même position, et leurs noms sont-ils compatibles ; deux signatures à la même position portent-elles deux valeurs différentes du même type.

Les notices theses.fr, sans position d'auteur, sont écartées, ainsi que les signatures sans le rôle `author`. Les publications de plus de `--full-max` auteurs sont échantillonnées (`--sample-large`).

Écrit un rapport Markdown et un échantillon de désaccords à relire à la main. Lecture seule sur la base.

Usage :
    python -m interfaces.cli.oneshot.measure_author_alignment
"""

from __future__ import annotations

import argparse
import csv
import os
import random
from collections import Counter, defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

from sqlalchemy import Connection, text

from domain.persons.matching import STRONG_IDENTIFIER_TYPES
from domain.persons.name_matching import names_compatible
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("measure_author_alignment", os.path.dirname(__file__))

_MEASURES = Path("data/measures")
_BUCKETS = (
    (5, "1-5"),
    (10, "6-10"),
    (20, "11-20"),
    (50, "21-50"),
    (100, "51-100"),
    (500, "101-500"),
)
_LARGE = ">500"
_BATCH = 500
_STRONG = tuple(str(t) for t in STRONG_IDENTIFIER_TYPES)


@dataclass(frozen=True, slots=True)
class Signature:
    position: int
    last_name: str
    first_name: str
    raw_name: str
    identifiers: dict[str, str]


def bucket(size: int) -> str:
    """Tranche de taille d'une liste d'auteurs."""
    return next((label for limit, label in _BUCKETS if size <= limit), _LARGE)


def _publication_ids(conn: Connection, full_max: int, sample_large: int, seed: int) -> list[int]:
    """Publications à notices d'au moins deux sources, hors theses.fr : toutes jusqu'à `full_max` auteurs, un échantillon au-delà."""
    rows = conn.execute(
        text("""
            WITH multi AS (
                SELECT publication_id FROM source_publications
                WHERE publication_id IS NOT NULL AND source <> 'theses'
                GROUP BY 1 HAVING count(DISTINCT source) >= 2
            )
            SELECT sp.publication_id, max(n.n) AS size
            FROM source_publications sp
            JOIN multi m USING (publication_id)
            JOIN LATERAL (
                SELECT count(*) AS n FROM source_authorships sa WHERE sa.source_publication_id = sp.id
            ) n ON true
            WHERE sp.source <> 'theses'
            GROUP BY 1
        """)
    ).all()
    small = [r.publication_id for r in rows if r.size <= full_max]
    large = [r.publication_id for r in rows if r.size > full_max]
    rng = random.Random(seed)  # noqa: S311 - tirage reproductible d'un échantillon
    sampled = rng.sample(large, min(sample_large, len(large)))
    log.info(
        "%d publications jusqu'à %d auteurs, %d au-delà dont %d échantillonnées",
        len(small),
        full_max,
        len(large),
        len(sampled),
    )
    return small + sampled


def _notices(
    conn: Connection, publication_ids: Sequence[int]
) -> Iterator[tuple[int, dict[tuple[int, str], list[Signature]]]]:
    """Notices de chaque publication : `(id de notice, source)` → signatures d'auteur triées par position."""
    for start in range(0, len(publication_ids), _BATCH):
        ids = list(publication_ids[start : start + _BATCH])
        rows = conn.execute(
            text("""
                SELECT sp.publication_id, sp.id AS notice_id, sp.source::text AS source,
                       sa.author_position, aik.last_name_normalized AS ln,
                       coalesce(aik.first_name_normalized, '') AS fn,
                       coalesce(sa.raw_author_name, concat_ws(' ', sa.raw_first_name, sa.raw_last_name)) AS raw_name,
                       aik.person_identifiers, sa.neutralized_identifiers
                FROM source_publications sp
                JOIN source_authorships sa ON sa.source_publication_id = sp.id
                JOIN author_identifying_keys aik ON aik.id = sa.identity_id
                WHERE sp.publication_id = ANY(:ids) AND sp.source <> 'theses'
                  AND 'author' = ANY(sa.roles) AND sa.author_position IS NOT NULL
            """),
            {"ids": ids},
        )
        by_pub: dict[int, dict[tuple[int, str], list[Signature]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for r in rows:
            neutralized = set((r.neutralized_identifiers or {}).keys())
            identifiers = {
                t: str(v)
                for t, v in (r.person_identifiers or {}).items()
                if t in _STRONG and t not in neutralized and v
            }
            by_pub[r.publication_id][(r.notice_id, r.source)].append(
                Signature(r.author_position, r.ln, r.fn, r.raw_name or "", identifiers)
            )
        for pub_id, notices in by_pub.items():
            yield pub_id, {k: sorted(v, key=lambda s: s.position) for k, v in notices.items()}


def _words(s: Signature) -> set[str]:
    return {w for w in f"{s.first_name} {s.last_name}".split() if len(w) > 1}


@dataclass
class Tally:
    pairs: int = 0
    same_length: int = 0
    signatures: int = 0
    same_position: int = 0
    shifted: int = 0
    absent: int = 0
    shared_ids: int = 0
    shared_ids_same_position: int = 0
    shared_ids_names_compatible: int = 0
    conflicting_ids_same_position: int = 0
    conflicting_ids_names_compatible: int = 0

    def add(self, other: Tally) -> None:
        for name in self.__dataclass_fields__:
            setattr(self, name, getattr(self, name) + getattr(other, name))


def _compare(
    a: list[Signature],
    b: list[Signature],
    samples: list[dict[str, object]],
    context: dict[str, object],
) -> Tally:
    """Compare la liste `a` à la liste `b`. Un désaccord sur sept est gardé dans `samples`."""
    tally = Tally()
    tally.pairs += 1
    tally.same_length += len(a) == len(b)
    by_position = {s.position: s for s in b}
    by_word: dict[str, list[Signature]] = defaultdict(list)
    for s in b:
        for w in _words(s):
            by_word[w].append(s)
    by_identifier = {(t, v): s for s in b for t, v in s.identifiers.items()}
    for s in a:
        tally.signatures += 1
        other = by_position.get(s.position)
        if other is not None and names_compatible(
            s.last_name, s.first_name, other.last_name, other.first_name
        ):
            tally.same_position += 1
            outcome = "même position"
        else:
            candidates = {id(c): c for w in _words(s) for c in by_word.get(w, ())}.values()
            found = [
                c
                for c in candidates
                if names_compatible(s.last_name, s.first_name, c.last_name, c.first_name)
            ]
            if found:
                tally.shifted += 1
                nearest = min(found, key=lambda c: abs(c.position - s.position))
                outcome = f"décalée de {nearest.position - s.position}"
            else:
                tally.absent += 1
                outcome = "absente"
            if len(samples) < 5000 and random.random() < 1 / 7:  # noqa: S311 - échantillon de relecture
                samples.append(
                    {
                        **context,
                        "position": s.position,
                        "nom": s.raw_name,
                        "même_position_autre_notice": other.raw_name if other else "",
                        "résultat": outcome,
                    }
                )
        for (t, v), match in ((k, by_identifier.get(k)) for k in s.identifiers.items()):
            if match is not None:
                tally.shared_ids += 1
                tally.shared_ids_same_position += match.position == s.position
                tally.shared_ids_names_compatible += names_compatible(
                    s.last_name, s.first_name, match.last_name, match.first_name
                )
            elif other is not None and other.identifiers.get(t) not in (None, v):
                tally.conflicting_ids_same_position += 1
                tally.conflicting_ids_names_compatible += names_compatible(
                    s.last_name, s.first_name, other.last_name, other.first_name
                )
    return tally


def measure(
    conn: Connection, publication_ids: Sequence[int]
) -> tuple[dict[str, Tally], dict[str, Tally], Counter[str], list[dict[str, object]]]:
    """Accords par tranche de taille et par paire de sources, écarts de longueur, échantillon de désaccords."""
    by_bucket: dict[str, Tally] = defaultdict(Tally)
    by_sources: dict[str, Tally] = defaultdict(Tally)
    length_gaps: Counter[str] = Counter()
    samples: list[dict[str, object]] = []
    for done, (pub_id, notices) in enumerate(_notices(conn, publication_ids), 1):
        for (ka, a), (kb, b) in combinations(sorted(notices.items(), key=lambda kv: kv[0][1]), 2):
            if ka[1] == kb[1]:
                continue
            # La liste la plus courte se compare à la plus longue : une liste tronquée ne compte pas en auteurs absents.
            if len(a) > len(b):
                (ka, a), (kb, b) = (kb, b), (ka, a)
            label = bucket(len(b))
            gap = len(b) - len(a)
            length_gaps[f"{label}|{'0' if gap == 0 else '1-2' if gap <= 2 else '3+'}"] += 1
            pair = "–".join(sorted((ka[1], kb[1])))
            context = {
                "publication_id": pub_id,
                "sources": f"{ka[1]}→{kb[1]}",
                "tranche": label,
                "longueurs": f"{len(a)}/{len(b)}",
            }
            tally = _compare(a, b, samples, context)
            by_bucket[label].add(tally)
            by_sources[pair].add(tally)
        if done % 5000 == 0:
            log.info("%d publications traitées", done)
    return by_bucket, by_sources, length_gaps, samples


def _pct(n: int, d: int) -> str:
    return f"{100 * n / d:.1f} %" if d else "—"


def report(
    by_bucket: dict[str, Tally], by_sources: dict[str, Tally], length_gaps: Counter[str]
) -> str:
    labels = [label for _, label in _BUCKETS] + [_LARGE]
    lines = ["# Alignement des auteurs entre sources : mesure", ""]
    lines += ["## Accord de la position, par taille de liste", ""]
    lines += [
        "| Auteurs | Paires de notices | Longueurs égales | Signatures | Même position | Décalée | Absente |",
        "|---|---|---|---|---|---|---|",
    ]
    for label in labels:
        t = by_bucket.get(label)
        if t:
            lines.append(
                f"| {label} | {t.pairs} | {_pct(t.same_length, t.pairs)} | {t.signatures} | {_pct(t.same_position, t.signatures)} | {_pct(t.shifted, t.signatures)} | {_pct(t.absent, t.signatures)} |"
            )
    lines += [
        "",
        "## Écarts de longueur entre les deux listes",
        "",
        "| Auteurs | Écart 0 | 1-2 | 3 et plus |",
        "|---|---|---|---|",
    ]
    for label in labels:
        counts = [length_gaps.get(f"{label}|{g}", 0) for g in ("0", "1-2", "3+")]
        if sum(counts):
            lines.append(f"| {label} | " + " | ".join(_pct(c, sum(counts)) for c in counts) + " |")
    lines += [
        "",
        "## Identifiants forts",
        "",
        "| Auteurs | Identifiants partagés | À la même position | Noms compatibles | Identifiants différents à la même position | Dont noms compatibles |",
        "|---|---|---|---|---|---|",
    ]
    for label in labels:
        t = by_bucket.get(label)
        if t:
            lines.append(
                f"| {label} | {t.shared_ids} | {_pct(t.shared_ids_same_position, t.shared_ids)} | {_pct(t.shared_ids_names_compatible, t.shared_ids)} | {t.conflicting_ids_same_position} | {t.conflicting_ids_names_compatible} |"
            )
    lines += [
        "",
        "## Accord de la position, par paire de sources",
        "",
        "| Sources | Paires de notices | Signatures | Même position | Décalée | Absente |",
        "|---|---|---|---|---|---|",
    ]
    for pair, t in sorted(by_sources.items(), key=lambda kv: -kv[1].signatures):
        lines.append(
            f"| {pair} | {t.pairs} | {t.signatures} | {_pct(t.same_position, t.signatures)} | {_pct(t.shifted, t.signatures)} | {_pct(t.absent, t.signatures)} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Mesure de l'alignement des auteurs entre sources")
    parser.add_argument(
        "--full-max", type=int, default=500, help="Taille maximale des listes mesurées en entier"
    )
    parser.add_argument(
        "--sample-large", type=int, default=150, help="Publications échantillonnées au-delà"
    )
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    random.seed(args.seed)
    _MEASURES.mkdir(parents=True, exist_ok=True)
    with get_sync_engine().connect() as conn:
        ids = _publication_ids(conn, args.full_max, args.sample_large, args.seed)
        by_bucket, by_sources, length_gaps, samples = measure(conn, ids)
    report_path = _MEASURES / "author_alignment.md"
    report_path.write_text(report(by_bucket, by_sources, length_gaps), encoding="utf-8")
    samples_path = _MEASURES / "author_alignment_disagreements.csv"
    with samples_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(samples[0]) if samples else ["publication_id"])
        writer.writeheader()
        writer.writerows(samples)
    log.info("Rapport : %s ; désaccords : %s (%d lignes)", report_path, samples_path, len(samples))


if __name__ == "__main__":
    main()
