# STATUS: oneshot (2026-10-15)
"""Alignement des listes d'auteurs d'une même publication entre sources : mesure, phase 1 du chantier `DATA_alignement-auteurs.md`.

Pour chaque publication dont les notices viennent d'au moins deux sources, et pour chaque paire de notices de sources différentes :

- longueur des deux listes d'auteurs ;
- accord de la position : une signature de la première notice trouve-t-elle, dans la seconde, un nom compatible (`names_compatible`) à la même position, à une autre position, ou nulle part ;
- accord des identifiants forts (`STRONG_PERSON_IDENTIFIER_TYPES`, hors identifiants neutralisés) : deux signatures qui partagent un identifiant sont-elles à la même position, et leurs noms sont-ils compatibles ; deux signatures à la même position ont-elles deux valeurs différentes du même type ;
- ambiguïté : nombre de noms compatibles trouvés pour une signature décalée.

L'accord se mesure aussi sans les paires dépendantes, où une notice recopie un dépôt HAL. Sur les publications à trois sources indépendantes ou plus, un vote désigne la source dont le prénom s'écarte à une position donnée.

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

from domain.persons.matching import STRONG_PERSON_IDENTIFIER_TYPES
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
_STRONG = tuple(str(t) for t in STRONG_PERSON_IDENTIFIER_TYPES)


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


type NoticeKey = tuple[int, str, bool]


def _notices(
    conn: Connection, publication_ids: Sequence[int]
) -> Iterator[tuple[int, dict[NoticeKey, list[Signature]]]]:
    """Notices de chaque publication : `(id de notice, source, issue de HAL)` → signatures d'auteur individuelles triées par position.

    Une notice est issue de HAL quand elle recopie un dépôt HAL : notice scanR à identifiant `hal…`, notice OpenAlex dont la première URL, celle de la location principale, est une page HAL.
    """
    for start in range(0, len(publication_ids), _BATCH):
        ids = list(publication_ids[start : start + _BATCH])
        rows = conn.execute(
            text(r"""
                SELECT sp.publication_id, sp.id AS notice_id, sp.source::text AS source,
                       (sp.source = 'scanr' AND sp.source_id LIKE 'hal%')
                       OR (sp.source = 'openalex' AND coalesce(sp.urls[1], '') ~ '(hal\.science|archives-ouvertes\.fr)')
                           AS from_hal,
                       sa.author_position, aik.last_name_normalized AS ln,
                       coalesce(aik.first_name_normalized, '') AS fn,
                       coalesce(sa.raw_author_name, concat_ws(' ', sa.raw_first_name, sa.raw_last_name)) AS raw_name,
                       aik.person_identifiers, sa.neutralized_identifiers
                FROM source_publications sp
                JOIN source_authorships sa ON sa.source_publication_id = sp.id
                JOIN author_identifying_keys aik ON aik.id = sa.identity_id
                WHERE sp.publication_id = ANY(:ids) AND sp.source <> 'theses'
                  AND 'author' = ANY(sa.roles) AND sa.author_position IS NOT NULL
                  AND NOT sa.collective
            """),
            {"ids": ids},
        )
        by_pub: dict[int, dict[NoticeKey, list[Signature]]] = defaultdict(lambda: defaultdict(list))
        for r in rows:
            neutralized = set((r.neutralized_identifiers or {}).keys())
            identifiers = {
                t: str(v)
                for t, v in (r.person_identifiers or {}).items()
                if t in _STRONG and t not in neutralized and v
            }
            by_pub[r.publication_id][(r.notice_id, r.source, bool(r.from_hal))].append(
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
    shifted_ambiguous: int = 0
    absent: int = 0
    shared_ids: int = 0
    shared_ids_same_position: int = 0
    shared_ids_names_compatible: int = 0
    conflicting_ids_same_position: int = 0
    conflicting_ids_names_compatible: int = 0

    def add(self, other: Tally) -> None:
        for name in self.__dataclass_fields__:
            setattr(self, name, getattr(self, name) + getattr(other, name))


def _compatible(x: Signature, y: Signature) -> bool:
    return names_compatible(x.last_name, x.first_name, y.last_name, y.first_name)


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
        if other is not None and _compatible(s, other):
            tally.same_position += 1
            outcome = "même position"
        else:
            candidates = {id(c): c for w in _words(s) for c in by_word.get(w, ())}.values()
            found = [c for c in candidates if _compatible(s, c)]
            if found:
                tally.shifted += 1
                tally.shifted_ambiguous += len(found) > 1
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
                tally.shared_ids_names_compatible += _compatible(s, match)
            elif other is not None and other.identifiers.get(t) not in (None, v):
                tally.conflicting_ids_same_position += 1
                tally.conflicting_ids_names_compatible += _compatible(s, other)
    return tally


def _dependent(ka: NoticeKey, kb: NoticeKey) -> bool:
    """Vrai quand une notice recopie l'autre, ou quand les deux recopient le même dépôt HAL."""
    return (ka[1] == "hal" and kb[2]) or (kb[1] == "hal" and ka[2]) or (ka[2] and kb[2])


@dataclass
class Outliers:
    """Positions où les noms de trois sources ou plus partagent le nom de famille sans être tous compatibles."""

    groups: Counter[str]
    outlier: Counter[str]
    no_majority: int = 0


def _first_name_outliers(notices: dict[NoticeKey, list[Signature]], outliers: Outliers) -> None:
    """Pour chaque position commune à trois sources ou plus, au même nom de famille et aux noms pas tous compatibles : la source dont le nom s'écarte de tous les autres, eux compatibles entre eux.

    Une notice par source, la plus longue. Les notices recopiées d'un dépôt HAL sont écartées, pour que le vote compte des sources indépendantes.
    """
    by_source: dict[str, list[Signature]] = {}
    for (_, source, from_hal), sigs in notices.items():
        if not from_hal and len(sigs) > len(by_source.get(source, [])):
            by_source[source] = sigs
    if len(by_source) < 3:
        return
    positions: dict[int, dict[str, Signature]] = defaultdict(dict)
    for source, sigs in by_source.items():
        for s in sigs:
            positions[s.position][source] = s
    for group in positions.values():
        if len(group) < 3 or len({s.last_name for s in group.values()}) > 1:
            continue
        if all(_compatible(x, y) for x, y in combinations(group.values(), 2)):
            continue
        for source in group:
            outliers.groups[source] += 1
        candidates = [
            source
            for source, s in group.items()
            if not any(_compatible(s, o) for src, o in group.items() if src != source)
            and all(
                _compatible(x, y)
                for x, y in combinations([o for src, o in group.items() if src != source], 2)
            )
        ]
        if len(candidates) == 1:
            outliers.outlier[candidates[0]] += 1
        else:
            outliers.no_majority += 1


def measure(
    conn: Connection, publication_ids: Sequence[int]
) -> tuple[
    dict[str, Tally],
    dict[str, Tally],
    dict[str, Tally],
    Counter[str],
    Outliers,
    list[dict[str, object]],
]:
    """Accords par tranche de taille (toutes paires, paires indépendantes) et par paire de sources, écarts de longueur, sources qui s'écartent, échantillon de désaccords."""
    by_bucket: dict[str, Tally] = defaultdict(Tally)
    by_bucket_independent: dict[str, Tally] = defaultdict(Tally)
    by_sources: dict[str, Tally] = defaultdict(Tally)
    length_gaps: Counter[str] = Counter()
    outliers = Outliers(Counter(), Counter())
    samples: list[dict[str, object]] = []
    for done, (pub_id, notices) in enumerate(_notices(conn, publication_ids), 1):
        _first_name_outliers(notices, outliers)
        for (ka, a), (kb, b) in combinations(sorted(notices.items(), key=lambda kv: kv[0][1]), 2):
            if ka[1] == kb[1]:
                continue
            # La liste la plus courte se compare à la plus longue : une liste tronquée ne compte pas en auteurs absents.
            if len(a) > len(b):
                (ka, a), (kb, b) = (kb, b), (ka, a)
            label = bucket(len(b))
            gap = len(b) - len(a)
            length_gaps[f"{label}|{'0' if gap == 0 else '1-2' if gap <= 2 else '3+'}"] += 1
            dependent = _dependent(ka, kb)
            pair = "–".join(sorted((ka[1], kb[1]))) + (" (recopie de HAL)" if dependent else "")
            context = {
                "publication_id": pub_id,
                "sources": f"{ka[1]}→{kb[1]}",
                "tranche": label,
                "longueurs": f"{len(a)}/{len(b)}",
            }
            tally = _compare(a, b, samples, context)
            by_bucket[label].add(tally)
            by_sources[pair].add(tally)
            if not dependent:
                by_bucket_independent[label].add(tally)
        if done % 5000 == 0:
            log.info("%d publications traitées", done)
    return by_bucket, by_bucket_independent, by_sources, length_gaps, outliers, samples


def _pct(n: int, d: int) -> str:
    return f"{100 * n / d:.1f} %" if d else "—"


def _position_table(by_bucket: dict[str, Tally], labels: list[str]) -> list[str]:
    lines = [
        "| Auteurs | Paires de notices | Longueurs égales | Signatures | Même position | Décalée | Décalée, plusieurs noms compatibles | Absente |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for label in labels:
        t = by_bucket.get(label)
        if t:
            lines.append(
                f"| {label} | {t.pairs} | {_pct(t.same_length, t.pairs)} | {t.signatures} | {_pct(t.same_position, t.signatures)} | {_pct(t.shifted, t.signatures)} | {_pct(t.shifted_ambiguous, t.shifted)} | {_pct(t.absent, t.signatures)} |"
            )
    return lines


def report(
    by_bucket: dict[str, Tally],
    by_bucket_independent: dict[str, Tally],
    by_sources: dict[str, Tally],
    length_gaps: Counter[str],
    outliers: Outliers,
) -> str:
    labels = [label for _, label in _BUCKETS] + [_LARGE]
    lines = ["# Alignement des auteurs entre sources : mesure", ""]
    lines += ["## Accord de la position, par taille de liste", ""]
    lines += _position_table(by_bucket, labels)
    lines += ["", "## Accord de la position, paires indépendantes", ""]
    lines += [
        "Sans les paires où une notice recopie un dépôt HAL : notice scanR à identifiant `hal…`, notice OpenAlex dont la location principale est HAL.",
        "",
    ]
    lines += _position_table(by_bucket_independent, labels)
    lines += [
        "",
        "## Prénom incompatible à la même position",
        "",
        f"Positions communes à trois sources indépendantes ou plus, au même nom de famille, aux noms pas tous compatibles. Sans source unique qui s'écarte : {outliers.no_majority}.",
        "",
        "| Source | Positions en désaccord | Source qui s'écarte | Part |",
        "|---|---|---|---|",
    ]
    for source, n in outliers.groups.most_common():
        lines.append(
            f"| {source} | {n} | {outliers.outlier[source]} | {_pct(outliers.outlier[source], n)} |"
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
        by_bucket, by_bucket_independent, by_sources, length_gaps, outliers, samples = measure(
            conn, ids
        )
    report_path = _MEASURES / "author_alignment.md"
    report_path.write_text(
        report(by_bucket, by_bucket_independent, by_sources, length_gaps, outliers),
        encoding="utf-8",
    )
    samples_path = _MEASURES / "author_alignment_disagreements.csv"
    with samples_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(samples[0]) if samples else ["publication_id"])
        writer.writeheader()
        writer.writerows(samples)
    log.info("Rapport : %s ; désaccords : %s (%d lignes)", report_path, samples_path, len(samples))


if __name__ == "__main__":
    main()
