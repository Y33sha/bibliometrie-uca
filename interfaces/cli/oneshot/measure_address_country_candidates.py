# STATUS: oneshot (2026-10-13)
"""Candidats pays de chaque adresse du stock, par moyen de détection, pour mesurer la justesse de chaque moyen.

Chaque moyen s'exécute sur toutes les adresses, indépendamment des autres moyens et de `addresses.countries` :

- `country_name` : nom de pays en fin d'adresse (détecteur de `detect_by_country_name`) ;
- `institution`, `city` : nom de lieu de cette nature, cherché dans tout le texte (`PlaceNameDetector`) ;
- `similarity` : pays le plus fréquent parmi les adresses à pays qui contiennent celle-ci, ses jumelles (même `normalized_text`) exclues ;
- `ror` : pays des organisations ROR rattachées à l'adresse ;
- `source_scanr`, `source_openalex` : pays que la source rattache à l'auteur, lus dans les payloads du raw store, pour chaque adresse de l'auteur. Seuls les documents présents dans `staging` comptent.

Le script lit la base et le raw store, et n'écrit ni dans l'une ni dans l'autre. Il écrit un fichier CSV compressé, une ligne par candidat : `address_id,country_code,method`. Le journal donne, par moyen, le nombre de candidats et d'adresses couvertes.

Usage :
    python -m interfaces.cli.oneshot.measure_address_country_candidates
    python -m interfaces.cli.oneshot.measure_address_country_candidates --methods ror,city
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import NamedTuple

import ahocorasick
from sqlalchemy import Connection, text

from domain.countries import PlaceNameKind, normalize_country_code
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.raw_store import UnreadablePayloadError, get_raw_store
from pipeline.ingestion.common.source_contributions import AuthorRecord
from pipeline.ingestion.openalex.normalize import build_openalex_author_records
from pipeline.ingestion.scanr.normalize import build_scanr_author_records
from pipeline.transformation.countries.detect_by_country_name import (
    _match_trailing_country,
    load_country_forms,
)
from pipeline.transformation.countries.place_name_detector import PlaceNameDetector

log = setup_logger("measure_address_country_candidates", os.path.dirname(__file__))

_DEFAULT_OUTPUT = Path("data/measures/address_country_candidates.csv.gz")

# Taille d'un lot de cibles de la similarité : borne la mémoire de l'automate, comme la phase `countries`.
_SIMILARITY_BATCH = 50_000

type Candidate = tuple[int, str]


class Address(NamedTuple):
    id: int
    raw_text: str
    normalized_text: str
    countries: tuple[str, ...]


def _codes(raw: Iterable[str | None]) -> set[str]:
    return {code for c in raw if (code := normalize_country_code(c))}


def load_addresses(conn: Connection) -> list[Address]:
    rows = conn.execute(
        text("SELECT id, raw_text, normalized_text, countries FROM addresses ORDER BY id")
    ).all()
    return [
        Address(r.id, r.raw_text, r.normalized_text or "", tuple(sorted(_codes(r.countries or ()))))
        for r in rows
    ]


def country_name_candidates(conn: Connection, addresses: list[Address]) -> Iterator[Candidate]:
    forms = load_country_forms(conn)
    max_tokens = max((form.count(" ") + 1 for form in forms), default=1)
    for address in addresses:
        iso = _match_trailing_country(address.normalized_text, forms, max_tokens)
        if code := normalize_country_code(iso):
            yield address.id, code


def place_candidates(
    conn: Connection, addresses: list[Address], kind: PlaceNameKind
) -> Iterator[Candidate]:
    rows = conn.execute(
        text("SELECT form_normalized, iso_code FROM place_name_forms WHERE kind = :kind"),
        {"kind": kind.value},
    ).all()
    detector = PlaceNameDetector({r.form_normalized: r.iso_code for r in rows})
    for address in addresses:
        for code in _codes(detector.detect(address.normalized_text)):
            yield address.id, code


def similarity_candidates(addresses: list[Address]) -> Iterator[Candidate]:
    """Pour chaque texte normalisé, le ou les pays les plus fréquents parmi les adresses à pays dont le texte le contient au mot près, ce texte lui-même exclu."""
    pool = [
        (a.normalized_text, a.countries) for a in addresses if a.countries and a.normalized_text
    ]
    ids_by_text: dict[str, list[int]] = defaultdict(list)
    for address in addresses:
        if address.normalized_text:
            ids_by_text[address.normalized_text].append(address.id)
    targets = list(ids_by_text)
    for start in range(0, len(targets), _SIMILARITY_BATCH):
        batch = targets[start : start + _SIMILARITY_BATCH]
        automaton = ahocorasick.Automaton()
        for target in batch:
            automaton.add_word(f" {target} ", target)
        automaton.make_automaton()
        counts: dict[str, Counter[str]] = defaultdict(Counter)
        for pool_text, codes in pool:
            matched = {target for _end, target in automaton.iter(f" {pool_text} ")}
            matched.discard(pool_text)
            for target in matched:
                counts[target].update(codes)
        for target, counter in counts.items():
            top = max(counter.values())
            for code in (c for c, n in counter.items() if n == top):
                for address_id in ids_by_text[target]:
                    yield address_id, code
        log.info("similarité : %d / %d textes", start + len(batch), len(targets))


def ror_candidates(conn: Connection) -> Iterator[Candidate]:
    rows = conn.execute(
        text("""
            SELECT DISTINCT scr.address_id, ro.country_code
            FROM source_contribution_rors scr
            JOIN ror_organizations ro USING (ror_id)
            WHERE scr.address_id IS NOT NULL
        """)
    )
    for r in rows:
        if code := normalize_country_code(r.country_code):
            yield r.address_id, code


def source_candidates(
    conn: Connection,
    addresses: list[Address],
    source: str,
    build_records: Callable[[dict], list[AuthorRecord]],
) -> Iterator[Candidate]:
    """Pays que la source rattache à chaque affiliation, posés sur l'adresse de son texte."""
    id_by_raw_text = {a.raw_text: a.id for a in addresses}
    staged = set(
        conn.execute(
            text("SELECT source_id FROM staging WHERE source = CAST(:s AS source_type)"),
            {"s": source},
        ).scalars()
    )
    store = get_raw_store()
    read = unreadable = 0
    for source_id in store.iter_keys(source):
        if source_id not in staged:
            continue
        try:
            payload = json.loads(store.get(source, source_id))
        except UnreadablePayloadError, ValueError:
            unreadable += 1
            continue
        read += 1
        if read % 10_000 == 0:
            log.info("%s : %d payloads lus", source, read)
        for author in build_records(payload):
            for address in author.addresses or ():
                address_id = id_by_raw_text.get(address.text)
                if address_id is None:
                    continue
                for code in _codes(address.countries or []):
                    yield address_id, code
    log.info("%s : %d payloads lus, %d illisibles", source, read, unreadable)


def main() -> None:
    methods_all = (
        "country_name",
        "institution",
        "city",
        "similarity",
        "ror",
        "source_scanr",
        "source_openalex",
    )
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--methods", default=",".join(methods_all))
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT)
    args = parser.parse_args()
    methods = [m for m in args.methods.split(",") if m]
    unknown = set(methods) - set(methods_all)
    if unknown:
        parser.error(f"moyens inconnus : {', '.join(sorted(unknown))}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with get_sync_engine().connect() as conn:
        addresses = load_addresses(conn)
        log.info("%d adresses", len(addresses))
        producers: dict[str, Callable[[], Iterable[Candidate]]] = {
            "country_name": lambda: country_name_candidates(conn, addresses),
            "institution": lambda: place_candidates(conn, addresses, PlaceNameKind.INSTITUTION),
            "city": lambda: place_candidates(conn, addresses, PlaceNameKind.CITY),
            "similarity": lambda: similarity_candidates(addresses),
            "ror": lambda: ror_candidates(conn),
            "source_scanr": lambda: source_candidates(
                conn, addresses, "scanr", build_scanr_author_records
            ),
            "source_openalex": lambda: source_candidates(
                conn, addresses, "openalex", build_openalex_author_records
            ),
        }
        with gzip.open(args.output, "wt", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(("address_id", "country_code", "method"))
            for method in methods:
                log.info("Moyen %s", method)
                candidates = set(producers[method]())
                writer.writerows((a, c, method) for a, c in sorted(candidates))
                covered = len({a for a, _ in candidates})
                log.info(
                    "%s : %d candidats, %d adresses (%.1f %%)",
                    method,
                    len(candidates),
                    covered,
                    100 * covered / len(addresses) if addresses else 0,
                )
    log.info("Candidats écrits dans %s", args.output)


if __name__ == "__main__":
    main()
