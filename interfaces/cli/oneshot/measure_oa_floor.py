# STATUS: oneshot (2026-10-30)
"""Mesure, décision par décision, du statut open access des publications du périmètre tiré de leurs copies.

Chaque étape ajoute une décision à l'étape précédente :

1. `regle_actuelle` : règle en place (`publication_oa_status`), recalculée sur l'état de la base.
2. `plancher_copies` : le statut ouvert vient des copies ouvertes ; les statuts ouverts déclarés par les sources sont ignorés. Une copie d'archive ou de serveur de preprints donne `green`. Une autre copie ouverte compte côté éditeur : `full_oa` donne `gold`, `diamond` donne `diamond`, `subscription` donne `hybrid` avec une licence ouverte, `bronze` sans ; hors revue, `bronze`. Un `gold` d'Unpaywall dans une revue `diamond` devient `diamond`. Sans statut, sans copie et sans verdict : `unknown`. Le verdict d'Unpaywall l'emporte comme dans la règle en place : sauf face à `diamond`, `embargoed` ou une copie d'archive ouverte.
3. `verdict_releve` : le verdict d'Unpaywall relève le statut, sans l'abaisser.
4. `embargo_copies` : l'embargo actif d'une copie donne `embargoed` ; le statut `embargoed` déclaré par HAL est ignoré.

Quatre options se mesurent sur l'étape 4 :

- `annexes_hal` : un dépôt HAL sans fichier principal, dit ouvert par HAL, compte comme copie d'archive ouverte. Son enregistrement source HAL est sans statut.
- `annexes_communications` : une communication ou un poster dont le dépôt HAL a un fichier, même seulement une annexe, compte comme copie d'archive ouverte. Le type de dépôt vient de l'API HAL (`data/measures/hal_annexes.tsv`, écrit par `data/measures/fetch_hal_annexes.py`).
- `verdict_doi` : un verdict `green` ou `closed` d'Unpaywall ferme les copies `doi.org` du DOI de la publication.
- `revue_ouverte` : une publication d'une revue `full_oa` est au moins `gold`, d'une revue `diamond` au moins `diamond`, même sans copie ouverte.

Les pages descriptives sont écartées des copies, comme à la normalisation.

- `simulate` écrit le statut de chaque publication à chaque étape, puis affiche les passages dus à chaque étape.
- `hosts` liste les domaines des copies ouvertes des publications passées d'un statut à un autre entre deux étapes.

Le script n'écrit pas dans la base.

Usage :
    uv run python -m interfaces.cli.oneshot.measure_oa_floor simulate
    uv run python -m interfaces.cli.oneshot.measure_oa_floor hosts regle_actuelle plancher_copies "green>bronze"
"""

import argparse
import csv
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from functools import cache
from pathlib import Path
from urllib.parse import unquote, urlparse

from sqlalchemy import Connection, text

from domain.platforms.platform import PlatformType, is_descriptive_page
from domain.publications.access import Copy, open_copies
from domain.publications.identifiers import extract_hal_id_from_url
from domain.publications.licenses import OPEN_LICENSES
from domain.publications.metadata import (
    OA_OPEN_STATUSES,
    OA_RANK,
    best_oa_status,
    publication_oa_status,
)
from domain.sources.registry import Source
from infrastructure.db.engine import build_sync_engine
from infrastructure.read_models.publications.copies import publication_copies

_DEFAULT_OUTPUT = Path("data/measures/oa_floor.tsv")
_ARCHIVE_TYPES = frozenset({PlatformType.REPOSITORY, PlatformType.PREPRINT_SERVER})
_DOI_HOSTS = frozenset({"doi.org", "dx.doi.org"})

_PUBLICATIONS = text("""
    SELECT p.id, p.oa_status::text AS cur, lower(p.doi::text) AS doi, u.oa_status::text AS upw,
           s.oa_model::text AS oa_model, p.doc_type::text AS doc_type
    FROM publications p
    LEFT JOIN sources.unpaywall u ON u.doi = lower(p.doi::text)
    LEFT JOIN serials s ON s.id = p.serial_id
    WHERE p.in_perimeter
""")

_SOURCE_STATUSES = text("""
    SELECT sr.publication_id AS pid, sr.source::text AS source, sr.oa_status::text AS oa_status
    FROM source_records sr JOIN publications p ON p.id = sr.publication_id AND p.in_perimeter
""")

_EMBARGOED = text("""
    SELECT DISTINCT sr.publication_id AS pid
    FROM source_record_locations l
    JOIN source_records sr ON sr.id = l.source_record_id
    JOIN publications p ON p.id = sr.publication_id AND p.in_perimeter
    WHERE l.embargo_until > current_date
""")


@dataclass(frozen=True, slots=True)
class _Signal:
    source: str
    oa_status: str | None


@dataclass(slots=True)
class _Facts:
    id: int
    cur: str
    doi: str | None
    upw: str | None
    oa_model: str | None
    doc_type: str | None
    signals: list[_Signal] = field(default_factory=list)
    copies: list[Copy] = field(default_factory=list)
    """Copies, ouvertes ou non, hors pages descriptives."""
    embargoed_copy: bool = False


def _is_archive(copy: Copy) -> bool:
    return copy.platform_type in _ARCHIVE_TYPES


def _floor(f: _Facts, copies: Sequence[Copy]) -> str | None:
    """Renvoie le statut tiré des copies ouvertes et du modèle de la revue, `None` sans copie ouverte."""
    best = "green" if any(_is_archive(c) for c in copies) else None
    publisher_side = [c for c in copies if not _is_archive(c)]
    if publisher_side:
        if f.oa_model == "diamond":
            side = "diamond"
        elif f.oa_model == "full_oa":
            side = "gold"
        elif f.oa_model == "subscription" and any(
            c.license in OPEN_LICENSES for c in publisher_side
        ):
            side = "hybrid"
        else:
            side = "bronze"
        best = best_oa_status([best, side])
    return best


def _verdict(f: _Facts) -> str | None:
    return "diamond" if f.upw == "gold" and f.oa_model == "diamond" else f.upw


def _is_publication_doi_copy(f: _Facts, copy: Copy) -> bool:
    parts = urlparse(copy.url)
    return (
        (parts.hostname or "") in _DOI_HOSTS
        and f.doi is not None
        and unquote(parts.path).lstrip("/").lower() == f.doi
    )


@dataclass(frozen=True, slots=True)
class _Rules:
    verdict_raises: bool = False
    embargo_on_copies: bool = False
    hal_annexes: bool = False
    hal_deposits_with_file: frozenset[str] | None = None
    """Dépôts HAL à fichier ou à annexe, d'après l'API HAL : leur copie compte comme ouverte pour une communication ou un poster."""
    verdict_closes_doi_copies: bool = False
    open_journal: bool = False


def _open(f: _Facts, rules: _Rules) -> list[Copy]:
    copies = open_copies(f.copies)
    if rules.hal_deposits_with_file is not None and f.doc_type in ("conference", "poster"):
        copies += [
            replace(c, is_oa=True)
            for c in f.copies
            if c.described_by_platform
            and not c.is_oa
            and extract_hal_id_from_url(c.url) in rules.hal_deposits_with_file
        ]
    if rules.hal_annexes and any(s.source == Source.HAL and s.oa_status is None for s in f.signals):
        copies += [
            replace(c, is_oa=True) for c in f.copies if c.described_by_platform and not c.is_oa
        ]
    if rules.verdict_closes_doi_copies and f.upw in ("green", "closed"):
        copies = [c for c in copies if not _is_publication_doi_copy(f, c)]
    return copies


def _status(f: _Facts, rules: _Rules) -> str:
    """Renvoie le statut de la publication selon les règles des étapes 2 et suivantes."""
    declared = [s for s in f.signals if s.oa_status not in OA_OPEN_STATUSES]
    if rules.embargo_on_copies:
        declared = [
            s for s in declared if not (s.source == Source.HAL and s.oa_status == "embargoed")
        ]
    open_ = _open(f, rules)
    statuses = [_floor(f, open_), *(s.oa_status for s in declared)]
    if rules.embargo_on_copies and f.embargoed_copy:
        statuses.append("embargoed")
    if f.copies:
        statuses.append("closed")
    if rules.open_journal and f.oa_model in ("full_oa", "diamond"):
        statuses.append("gold" if f.oa_model == "full_oa" else "diamond")
    from_copies = best_oa_status(statuses) or "unknown"
    verdict = _verdict(f)
    if verdict is None:
        return from_copies
    if rules.verdict_raises:
        return best_oa_status([from_copies, verdict]) or "unknown"
    if from_copies == "diamond" and verdict == "gold":
        return from_copies
    if verdict in ("closed", "unknown") and (
        from_copies == "embargoed" or any(_is_archive(c) for c in open_)
    ):
        return from_copies
    return verdict


_STEPS: dict[str, Callable[[_Facts], str]] = {
    "regle_actuelle": lambda f: publication_oa_status(f.signals, f.upw),
    "plancher_copies": lambda f: _status(f, _Rules()),
    "verdict_releve": lambda f: _status(f, _Rules(verdict_raises=True)),
    "embargo_copies": lambda f: _status(f, _Rules(verdict_raises=True, embargo_on_copies=True)),
}
_OPTIONS: dict[str, Callable[[_Facts], str]] = {
    "annexes_hal": lambda f: _status(
        f, _Rules(verdict_raises=True, embargo_on_copies=True, hal_annexes=True)
    ),
    "annexes_communications": lambda f: _status(
        f,
        _Rules(
            verdict_raises=True,
            embargo_on_copies=True,
            hal_deposits_with_file=_hal_deposits_with_file(),
        ),
    ),
    "verdict_doi": lambda f: _status(
        f, _Rules(verdict_raises=True, embargo_on_copies=True, verdict_closes_doi_copies=True)
    ),
    "revue_ouverte": lambda f: _status(
        f, _Rules(verdict_raises=True, embargo_on_copies=True, open_journal=True)
    ),
}
_LAST_STEP = list(_STEPS)[-1]


@cache
def _hal_deposits_with_file() -> frozenset[str]:
    path = Path("data/measures/hal_annexes.tsv")
    if not path.exists():
        return frozenset()
    with path.open(encoding="utf-8") as fh:
        return frozenset(
            r["hal_id"].lower()
            for r in csv.DictReader(fh, delimiter="	")
            if r["submit_type"] in ("file", "annex")
        )


def _facts(conn: Connection) -> list[_Facts]:
    facts = {
        r.id: _Facts(r.id, r.cur or "unknown", r.doi, r.upw, r.oa_model, r.doc_type)
        for r in conn.execute(_PUBLICATIONS)
    }
    for r in conn.execute(_SOURCE_STATUSES):
        facts[r.pid].signals.append(_Signal(r.source, r.oa_status))
    for r in conn.execute(_EMBARGOED):
        facts[r.pid].embargoed_copy = True
    for pid, copies in publication_copies(conn, list(facts)).items():
        facts[pid].copies = [c for c in copies if not is_descriptive_page(c.url)]
    return list(facts.values())


def _print_transitions(title: str, before: Sequence[str], after: Sequence[str]) -> None:
    matrix = Counter((b, a) for b, a in zip(before, after, strict=True) if b != a)
    print(f"\n{title} : {sum(matrix.values())} publications changent de statut")
    for (b, a), n in matrix.most_common():
        print(f"  {b:10s} -> {a:10s} {n}")


def simulate(conn: Connection, output: Path) -> None:
    """Écrit le statut de chaque publication à chaque étape, puis affiche les passages dus à chaque étape."""
    facts = _facts(conn)
    columns: dict[str, list[str]] = {"actuel": [f.cur for f in facts]}
    for name, step in (_STEPS | _OPTIONS).items():
        columns[name] = [step(f) for f in facts]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(["id", "unpaywall", "oa_model", "doc_type", *columns])
        for i, f in enumerate(facts):
            writer.writerow(
                [f.id, f.upw, f.oa_model, f.doc_type, *(col[i] for col in columns.values())]
            )
    print(f"{len(facts)} publications")
    previous = "actuel"
    for name in _STEPS:
        _print_transitions(f"{previous} -> {name}", columns[previous], columns[name])
        previous = name
    for name in _OPTIONS:
        _print_transitions(f"{_LAST_STEP} -> {name}", columns[_LAST_STEP], columns[name])
    print("\nRépartition : actuel, puis dernière étape")
    for status in sorted(OA_RANK, key=OA_RANK.__getitem__, reverse=True):
        before, after = columns["actuel"].count(status), columns[_LAST_STEP].count(status)
        print(f"  {status:10s} {before:7d} {after:7d}")


def hosts(conn: Connection, output: Path, before: str, after: str, transition: str) -> None:
    """Liste les domaines des copies ouvertes des publications passées de `b` à `a` (`transition` = `b>a`) entre les étapes `before` et `after`."""
    b, a = transition.split(">")
    with output.open(encoding="utf-8") as fh:
        ids = [
            int(r["id"])
            for r in csv.DictReader(fh, delimiter="\t")
            if (r[before], r[after]) == (b, a)
        ]
    print(f"{len(ids)} publications")
    counts: Counter[str] = Counter()
    examples: dict[str, str] = {}
    publications: dict[str, set[int]] = defaultdict(set)
    for pid, copies in publication_copies(conn, ids).items():
        for c in open_copies(copies):
            if is_descriptive_page(c.url):
                continue
            kind = "archive" if _is_archive(c) else "éditeur"
            key = f"{kind} {urlparse(c.url).netloc} [{c.platform or '-'}]"
            counts[key] += 1
            publications[key].add(pid)
            examples.setdefault(key, f"{pid} {c.url}")
    for key, _ in counts.most_common(30):
        print(f"{len(publications[key]):6d}  {key}  {examples[key]}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT)
    sub = parser.add_subparsers(dest="step", required=True)
    sub.add_parser("simulate")
    hosts_parser = sub.add_parser("hosts")
    hosts_parser.add_argument("before")
    hosts_parser.add_argument("after")
    hosts_parser.add_argument("transition")
    args = parser.parse_args()
    with build_sync_engine().connect() as conn:
        if args.step == "simulate":
            simulate(conn, args.output)
        else:
            hosts(conn, args.output, args.before, args.after, args.transition)


if __name__ == "__main__":
    main()
