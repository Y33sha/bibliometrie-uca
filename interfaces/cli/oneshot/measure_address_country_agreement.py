# STATUS: oneshot (2026-10-13)
"""Accord des moyens de détection du pays d'une adresse, à partir des candidats de `measure_address_country_candidates`.

Compare l'ensemble des pays de chaque moyen, adresse par adresse :

- à `addresses.countries` : identique, sur-ensemble (pays en trop), sous-ensemble (pays manquants), recouvrement, disjoint ; et le nombre d'adresses sans pays retenu où le moyen propose un pays ;
- à chaque autre moyen, sur les adresses que les deux couvrent.

Compare aussi à `addresses.countries` les pays que compose la préséance du domaine (`retained_countries`) : pays identique, gagné, perdu ou changé. Les moyens écartés de la préséance (`similarity`) n'y entrent pas.

`addresses.countries` est lui-même produit par une partie des moyens (ScanR, nom de pays, nom de lieu) : leur accord avec lui est surestimé. L'accord entre moyens deux à deux reste la mesure indépendante.

Le code `xx` (adresse arbitrée sans pays) est retiré des ensembles comparés.

Écrit un rapport Markdown et un échantillon de désaccords avec `addresses.countries`, à revoir à la main : par moyen, des adresses tirées au hasard, avec leur texte et les candidats de tous les moyens. Lecture seule sur la base.

Usage :
    uv run python -m interfaces.cli.oneshot.measure_address_country_agreement
"""

from __future__ import annotations

import argparse
import csv
import gzip
import os
import random
from collections import defaultdict
from collections.abc import Iterable
from itertools import combinations
from pathlib import Path

from sqlalchemy import Connection, text

from domain.countries import NO_COUNTRY_CODE, normalize_country_code
from domain.country_detection import CountryDetectionMethod, retained_countries
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("measure_address_country_agreement", os.path.dirname(__file__))

_MEASURES = Path("data/measures")

_OUTCOMES = ("identical", "superset", "subset", "overlap", "disjoint")
_OUTCOME_HEADERS = "Identique | Sur-ensemble | Sous-ensemble | Recouvrement | Disjoint"

type CountrySets = dict[int, frozenset[str]]


def _number(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _percent(n: int, total: int) -> str:
    return f"{100 * n / total:.1f} %" if total else "—"


def _outcome_cells(counts: dict[str, int], total: int) -> str:
    return " | ".join(_percent(counts[o], total) for o in _OUTCOMES)


def load_candidates(path: Path) -> dict[str, CountrySets]:
    sets: dict[str, dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["country_code"] != NO_COUNTRY_CODE:
                sets[row["method"]][int(row["address_id"])].add(row["country_code"])
    return {m: {a: frozenset(c) for a, c in by_address.items()} for m, by_address in sets.items()}


def load_retained(conn: Connection) -> tuple[CountrySets, dict[int, str]]:
    """Pays retenus (`addresses.countries`, `xx` retiré) et texte brut de chaque adresse."""
    retained: CountrySets = {}
    raw_text: dict[int, str] = {}
    for r in conn.execute(text("SELECT id, raw_text, countries FROM addresses")):
        raw_text[r.id] = r.raw_text
        codes = frozenset(
            code
            for c in r.countries or ()
            if (code := normalize_country_code(c)) and code != NO_COUNTRY_CODE
        )
        if codes:
            retained[r.id] = codes
    return retained, raw_text


def compare(a: frozenset[str], b: frozenset[str]) -> str:
    """Relation de l'ensemble `a` à l'ensemble `b`."""
    if a == b:
        return "identical"
    if a > b:
        return "superset"
    if a < b:
        return "subset"
    return "overlap" if a & b else "disjoint"


def retained_table(candidates: dict[str, CountrySets], retained: CountrySets, total: int) -> str:
    lines = [
        (
            f"| Moyen | Adresses couvertes | Plusieurs pays | Avec pays retenu | {_OUTCOME_HEADERS} "
            "| Sans pays retenu |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for method, sets in sorted(candidates.items()):
        counts = dict.fromkeys(_OUTCOMES, 0)
        without = 0
        for address_id, codes in sets.items():
            if address_id in retained:
                counts[compare(codes, retained[address_id])] += 1
            else:
                without += 1
        compared = sum(counts.values())
        several = sum(1 for codes in sets.values() if len(codes) > 1)
        lines.append(
            f"| `{method}` | {_number(len(sets))} ({_percent(len(sets), total)}) "
            f"| {_percent(several, len(sets))} | {_number(compared)} "
            f"| {_outcome_cells(counts, compared)} | {_number(without)} |"
        )
    return "\n".join(lines)


def pairwise_table(candidates: dict[str, CountrySets]) -> str:
    lines = [
        f"| Moyen A | Moyen B | Adresses communes | {_OUTCOME_HEADERS} |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for m1, m2 in combinations(sorted(candidates), 2):
        s1, s2 = candidates[m1], candidates[m2]
        common = s1.keys() & s2.keys()
        counts = dict.fromkeys(_OUTCOMES, 0)
        for address_id in common:
            counts[compare(s1[address_id], s2[address_id])] += 1
        lines.append(
            f"| `{m1}` | `{m2}` | {_number(len(common))} | {_outcome_cells(counts, len(common))} |"
        )
    return "\n".join(lines)


def precedence_table(
    candidates: dict[str, CountrySets], retained: CountrySets, address_ids: Iterable[int]
) -> str:
    """Pays composés par `retained_countries`, comparés à `addresses.countries` sur les adresses `address_ids`. Les candidats d'une adresse supprimée depuis leur calcul sont ignorés."""
    methods = {m: CountryDetectionMethod(m) for m in candidates if m in CountryDetectionMethod}
    by_address: defaultdict[int, dict[CountryDetectionMethod, frozenset[str]]] = defaultdict(dict)
    for name, method in methods.items():
        for address_id, codes in candidates[name].items():
            by_address[address_id][method] = codes
    counts = dict.fromkeys(("identical", "gained", "lost", "changed"), 0)
    for address_id in address_ids:
        composed = retained_countries(by_address.get(address_id, {}))
        before = retained.get(address_id, frozenset())
        if composed == before:
            counts["identical"] += 1
        elif not before:
            counts["gained"] += 1
        elif not composed:
            counts["lost"] += 1
        else:
            counts["changed"] += 1
    total = sum(counts.values())
    return (
        "| Identique | Pays gagné | Pays perdu | Pays changé |\n|---|---|---|---|\n| "
        + " | ".join(f"{_number(counts[k])} ({_percent(counts[k], total)})" for k in counts)
        + " |"
    )


def write_disagreements(
    path: Path,
    candidates: dict[str, CountrySets],
    retained: CountrySets,
    raw_text: dict[int, str],
    per_method: int,
) -> None:
    rng = random.Random(0)  # noqa: S311 - tirage reproductible d'un échantillon
    methods = sorted(candidates)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(("method", "address_id", "raw_text", "retained", *methods))
        for method in methods:
            disjoint = sorted(
                a
                for a, codes in candidates[method].items()
                if a in retained and not codes & retained[a]
            )
            for address_id in rng.sample(disjoint, min(per_method, len(disjoint))):
                writer.writerow(
                    (
                        method,
                        address_id,
                        raw_text[address_id],
                        ",".join(sorted(retained[address_id])),
                        *(",".join(sorted(candidates[m].get(address_id, ()))) for m in methods),
                    )
                )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--candidates", type=Path, default=_MEASURES / "address_country_candidates.csv.gz"
    )
    parser.add_argument("--sample", type=int, default=40, help="désaccords tirés par moyen")
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        retained, raw_text = load_retained(conn)
    # Une adresse supprimée depuis le calcul des candidats sort de la mesure.
    candidates = {
        method: {a: codes for a, codes in sets.items() if a in raw_text}
        for method, sets in load_candidates(args.candidates).items()
    }
    total = len(raw_text)
    log.info("%d adresses, %d avec pays retenu", total, len(retained))

    report = _MEASURES / "address_country_agreement.md"
    report.write_text(
        "# Accord des moyens de détection du pays\n\n"
        f"{_number(total)} adresses, dont {_number(len(retained))} avec pays retenu. "
        "Chaque relation se lit de l'ensemble du moyen (A) vers l'ensemble de référence (B).\n\n"
        "## Avec `addresses.countries`\n\n"
        + retained_table(candidates, retained, total)
        + "\n\n## Entre moyens\n\n"
        + pairwise_table(candidates)
        + "\n\n## Préséance (`retained_countries`) contre `addresses.countries`\n\n"
        + precedence_table(candidates, retained, raw_text.keys())
        + "\n",
        encoding="utf-8",
    )
    sample = _MEASURES / "address_country_disagreements.csv"
    write_disagreements(sample, candidates, retained, raw_text, args.sample)
    log.info("Rapport : %s ; désaccords : %s", report, sample)


if __name__ == "__main__":
    main()
