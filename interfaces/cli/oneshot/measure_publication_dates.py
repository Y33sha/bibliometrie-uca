# STATUS: oneshot (2026-10-30)
"""Champs de date des enregistrements sources, lus dans le raw store, pour mesurer leur précision et leurs écarts.

Deux étapes, rejouables séparément :

- `extract` lit chaque enregistrement source de la base et son payload dans le raw store. Il écrit un fichier CSV compressé, une ligne par champ de date renseigné : `source_record_id,publication_id,source,field,raw,value`. `value` est la date normalisée, `AAAA`, `AAAA-MM` ou `AAAA-MM-JJ` selon sa précision ; vide si le champ est illisible. Le champ `publication_year` reprend la colonne de `source_records`.
- `analyze` lit ce fichier et écrit un rapport Markdown.

Le script n'écrit ni dans la base ni dans le raw store.

Usage :
    uv run python -m interfaces.cli.oneshot.measure_publication_dates extract
    uv run python -m interfaces.cli.oneshot.measure_publication_dates analyze
"""

from __future__ import annotations

import argparse
import calendar
import csv
import gzip
import json
import os
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from itertools import combinations, islice
from pathlib import Path
from typing import NamedTuple

from sqlalchemy import text

from domain.dates import french_date_to_iso, today
from domain.types import JsonValue, as_int, as_mapping, as_sequence, as_str, at_path
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.raw_store import UnreadablePayloadError, get_raw_store

log = setup_logger("measure_publication_dates", os.path.dirname(__file__))

_DEFAULT_EXTRACT = Path("data/measures/source_record_dates.csv.gz")
_DEFAULT_REPORT = Path("data/measures/publication_dates.md")
_WORKERS = 4
_CHUNK = 500

_MONTHS = {m.upper(): i for i, m in enumerate(calendar.month_abbr) if m}
_ISO = re.compile(r"^(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?(?:$|T|\s)")
# Date WoS : mois abrégé facultatif (« OCT », « OCT-NOV », « SPR »), jour facultatif, année facultative.
_WOS = re.compile(r"^(?:([A-Z]{3})[A-Z-]*)?\s*(\d{1,2})?(?:-\d{1,2})?\s*(\d{4})?$")
# Date WoS année en tête : « 2026 AUG 31 ».
_WOS_YEAR_FIRST = re.compile(r"^(\d{4})\s+([A-Z]{3})\s*(\d{1,2})?$")


def _format(year: int | None, month: int | None = None, day: int | None = None) -> str | None:
    """Date `AAAA[-MM[-JJ]]`, tronquée au premier élément manquant ou invalide."""
    if year is None or not 1000 <= year <= 2100:
        return None
    if month is None or not 1 <= month <= 12:
        return f"{year:04d}"
    if day is None or not 1 <= day <= calendar.monthrange(year, month)[1]:
        return f"{year:04d}-{month:02d}"
    return f"{year:04d}-{month:02d}-{day:02d}"


def parse_iso(raw: str | None) -> str | None:
    m = _ISO.match((raw or "").strip())
    if not m:
        return None
    return _format(*(int(g) if g else None for g in m.groups()))


def parse_date_parts(value: JsonValue) -> str | None:
    """Date Crossref : `{"date-parts": [[année, mois, jour]]}`, mois et jour facultatifs."""
    parts = as_sequence(as_mapping(value).get("date-parts"))
    first = as_sequence(parts[0]) if parts else []
    year, month, day = (list(map(as_int, first)) + [None, None, None])[:3]
    return _format(year, month, day)


def parse_wos(raw: str | None, year: int | None = None) -> str | None:
    """Date WoS en mois abrégé (« OCT 10 2023 », « DEC 2024 », « 2025 », « 2026 AUG 31 ») ; `year` à défaut d'année dans le texte."""
    cleaned = (raw or "").strip().upper()
    if m := _WOS_YEAR_FIRST.match(cleaned):
        text_year, month_name, day = m.groups()
    elif m := _WOS.match(cleaned):
        month_name, day, text_year = m.groups()
    else:
        return None
    return _format(
        int(text_year) if text_year else year,
        _MONTHS.get(month_name or ""),
        int(day) if day else None,
    )


def _str_or_int(value: JsonValue) -> str | None:
    if (i := as_int(value)) is not None:
        return str(i)
    return as_str(value)


type Field = tuple[str, str | None, str | None]  # (champ, valeur brute, date normalisée)


def hal_fields(doc: Mapping[str, JsonValue]) -> Iterator[Field]:
    raw = as_str(doc.get("publicationDate_s"))
    yield "publicationDate_s", raw, parse_iso(raw)
    raw = _str_or_int(doc.get("producedDateY_i"))
    yield "producedDateY_i", raw, parse_iso(raw)


def openalex_fields(work: Mapping[str, JsonValue]) -> Iterator[Field]:
    raw = as_str(work.get("publication_date"))
    yield "publication_date", raw, parse_iso(raw)


def crossref_fields(msg: Mapping[str, JsonValue]) -> Iterator[Field]:
    for name in ("issued", "published-online", "published-print", "posted", "accepted"):
        value = msg.get(name)
        if value is not None:
            yield name, json.dumps(as_mapping(value).get("date-parts")), parse_date_parts(value)


def datacite_fields(payload: Mapping[str, JsonValue]) -> Iterator[Field]:
    attributes = at_path(payload, "attributes")
    for entry in as_sequence(attributes.get("dates")):
        d = as_mapping(entry)
        if as_str(d.get("dateType")) == "Issued":
            raw = as_str(d.get("date"))
            yield "Issued", raw, parse_iso(raw)
    raw = _str_or_int(attributes.get("publicationYear"))
    yield "publicationYear", raw, parse_iso(raw)


def scanr_fields(doc: Mapping[str, JsonValue]) -> Iterator[Field]:
    raw = as_str(doc.get("publicationDate"))
    yield "publicationDate", raw, parse_iso(raw)


def theses_fields(thesis: Mapping[str, JsonValue]) -> Iterator[Field]:
    raw = as_str(thesis.get("dateSoutenance"))
    yield "dateSoutenance", raw, french_date_to_iso(raw)


def wos_fields(raw: Mapping[str, JsonValue]) -> Iterator[Field]:
    """Champs de date WoS. Ligne d'export tabulé (balise `UT`) : `PY`, `PD`, `EA`. Payload de l'API : `pub_info`."""
    if "UT" in raw:
        year = as_str(raw.get("PY"))
        year_int = int(year) if year and year.isdigit() else None
        yield "export.PY", year, _format(year_int)
        if (pd := as_str(raw.get("PD"))) is not None:
            yield "export.PD", pd, parse_wos(pd, year_int)
        if (ea := as_str(raw.get("EA"))) is not None:
            yield "export.EA", ea, parse_wos(ea)
        return
    info = at_path(raw, "static_data", "summary", "pub_info")
    pubyear = _str_or_int(info.get("pubyear"))
    yield "api.pubyear", pubyear, parse_iso(pubyear)
    for name in ("coverdate", "early_access_date"):
        if (value := _str_or_int(info.get(name))) is not None:
            yield f"api.{name}", value, parse_wos(value)
    if (sortdate := as_str(info.get("sortdate"))) is not None:
        yield "api.sortdate", sortdate, parse_iso(sortdate)


_EXTRACTORS: dict[str, Callable[[Mapping[str, JsonValue]], Iterator[Field]]] = {
    "hal": hal_fields,
    "openalex": openalex_fields,
    "crossref": crossref_fields,
    "datacite": datacite_fields,
    "scanr": scanr_fields,
    "theses": theses_fields,
    "wos": wos_fields,
}


class Record(NamedTuple):
    id: int
    publication_id: int | None
    source: str
    source_id: str
    publication_year: int | None


type Row = tuple[int, int | None, str, str, str | None, str | None]


def _extract_chunk(records: Sequence[Record]) -> tuple[list[Row], int, int]:
    """Lignes de date d'un lot d'enregistrements sources, avec le nombre de payloads absents et illisibles."""
    store = get_raw_store()
    rows: list[Row] = []
    missing = unreadable = 0
    for r in records:
        base = (r.id, r.publication_id, r.source)
        year = None if r.publication_year is None else str(r.publication_year)
        rows.append((*base, "publication_year", year, year))
        try:
            payload = json.loads(store.get(r.source, r.source_id))
        except KeyError:
            missing += 1
            continue
        except UnreadablePayloadError, ValueError:
            unreadable += 1
            continue
        for name, raw, value in _EXTRACTORS[r.source](as_mapping(payload)):
            if raw is not None:
                rows.append((*base, name, raw, value))
    return rows, missing, unreadable


def _chunks(records: Iterable[Record]) -> Iterator[list[Record]]:
    it = iter(records)
    while chunk := list(islice(it, _CHUNK)):
        yield chunk


def extract(output: Path) -> None:
    with get_sync_engine().connect() as conn:
        records = [
            Record(*row)
            for row in conn.execute(
                text(
                    "SELECT id, publication_id, source::text, source_id, publication_year"
                    " FROM source_records ORDER BY source, id"
                )
            )
        ]
    log.info("%d enregistrements sources", len(records))
    output.parent.mkdir(parents=True, exist_ok=True)
    done = missing = unreadable = 0
    with (
        gzip.open(output, "wt", newline="", encoding="utf-8") as f,
        ProcessPoolExecutor(_WORKERS) as pool,
    ):
        writer = csv.writer(f)
        writer.writerow(("source_record_id", "publication_id", "source", "field", "raw", "value"))
        for rows, chunk_missing, chunk_unreadable in pool.map(_extract_chunk, _chunks(records)):
            writer.writerows(rows)
            done += _CHUNK
            missing += chunk_missing
            unreadable += chunk_unreadable
            if done % 20_000 == 0:
                log.info("%d / %d enregistrements sources", min(done, len(records)), len(records))
    log.info(
        "%d payloads absents, %d illisibles ; dates écrites dans %s", missing, unreadable, output
    )


# --- Analyse ---

# Champ de référence de chaque source pour les comparaisons entre sources, hors WoS (`_wos_reference`).
_REFERENCE = {
    "hal": ("publicationDate_s",),
    "openalex": ("publication_date",),
    "crossref": ("issued",),
    "datacite": ("Issued", "publicationYear"),
    "scanr": ("publicationDate",),
    "theses": ("dateSoutenance",),
}
# Sources dont le 1er du mois est suspect.
_FIRST_OF_MONTH_SOURCES = ("openalex", "scanr")


def _precision(value: str) -> str:
    return {4: "année", 7: "mois", 10: "jour"}[len(value)]


def _to_date(value: str) -> date:
    return date.fromisoformat(value)


def _pct(n: int, total: int) -> str:
    return f"{100 * n / total:.1f} %" if total else "—"


class SourceRecordDates(NamedTuple):
    id: int
    source: str
    fields: dict[str, str]  # champ -> date normalisée


def _load(path: Path) -> tuple[dict[int, SourceRecordDates], dict[int, list[int]], Counter[tuple]]:
    """Dates par enregistrement source, enregistrements sources par publication, et valeurs illisibles par (source, champ, valeur brute)."""
    records: dict[int, SourceRecordDates] = {}
    by_publication: dict[int, list[int]] = defaultdict(list)
    unparsed: Counter[tuple] = Counter()
    with gzip.open(path, "rt", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            record_id = int(row["source_record_id"])
            if record_id not in records:
                records[record_id] = SourceRecordDates(record_id, row["source"], {})
                if row["publication_id"]:
                    by_publication[int(row["publication_id"])].append(record_id)
            if row["value"]:
                records[record_id].fields.setdefault(row["field"], row["value"])
            else:
                unparsed[(row["source"], row["field"], row["raw"])] += 1
    return records, by_publication, unparsed


def _wos_early_access(fields: Mapping[str, str]) -> str | None:
    return fields.get("api.early_access_date") or fields.get("export.EA")


def _wos_cover(fields: Mapping[str, str]) -> str | None:
    return fields.get("api.coverdate") or fields.get("export.PD")


def _wos_reference(fields: Mapping[str, str]) -> str | None:
    """`sortdate` de l'API, à défaut la plus ancienne des dates d'accès anticipé et de parution, à défaut l'année."""
    if sortdate := fields.get("api.sortdate"):
        return sortdate
    if dates := [d for d in (_wos_early_access(fields), _wos_cover(fields)) if d]:
        return min(dates)
    return fields.get("api.pubyear") or fields.get("export.PY")


def _reference(record: SourceRecordDates) -> str | None:
    """Date de référence de l'enregistrement source : le premier champ renseigné parmi ceux de `_REFERENCE`."""
    if record.source == "wos":
        return _wos_reference(record.fields)
    return next(
        (record.fields[f] for f in _REFERENCE[record.source] if f in record.fields),
        None,
    )


def _table(header: Sequence[str], rows: Iterable[Sequence[object]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return lines + [""]


def _precision_section(records: dict[int, SourceRecordDates]) -> list[str]:
    counts: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    totals: Counter[str] = Counter(r.source for r in records.values())
    for r in records.values():
        for name, value in r.fields.items():
            c = counts[(r.source, name)]
            c[_precision(value)] += 1
            if len(value) == 10:
                c["01-01"] += value.endswith("-01-01")
                c["01 du mois"] += value.endswith("-01")
    rows = []
    for (source, name), c in sorted(counts.items()):
        filled = c["année"] + c["mois"] + c["jour"]
        rows.append(
            (
                source,
                name,
                _pct(filled, totals[source]),
                _pct(c["année"], filled),
                _pct(c["mois"], filled),
                _pct(c["jour"], filled),
                _pct(c["01-01"], c["jour"]),
                _pct(c["01 du mois"], c["jour"]),
            )
        )
    return [
        "## Précision des champs",
        "",
        "Part des enregistrements sources où le champ est lisible, puis précision. Les deux dernières colonnes portent sur les dates au jour.",
        "",
        *_table(
            ("Source", "Champ", "Renseigné", "Année", "Mois", "Jour", "1er janvier", "1er du mois"),
            rows,
        ),
    ]


def _unparsed_section(unparsed: Counter[tuple]) -> list[str]:
    by_field: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for (source, name, raw), n in unparsed.items():
        if name != "publication_year":
            by_field[(source, name)][raw] += n
    rows = [
        (source, name, sum(c.values()), ", ".join(f"`{raw}` ({n})" for raw, n in c.most_common(5)))
        for (source, name), c in sorted(by_field.items())
    ]
    return ["## Valeurs illisibles", "", *_table(("Source", "Champ", "Nombre", "Exemples"), rows)]


def _compare(a: str, b: str) -> str:
    """Accord de deux dates à leur précision commune."""
    common = min(len(a), len(b))
    if a[:common] == b[:common]:
        return "accord"
    if a[:4] != b[:4]:
        return "année différente"
    if a[:7] != b[:7]:
        return "mois différent"
    return "jour différent"


def _first_of_month_group(value: str) -> str:
    if value.endswith("-01-01"):
        return "1er janvier"
    if value.endswith("-01"):
        return "1er d'un autre mois"
    return "autre jour"


_FIRST_OF_MONTH_GROUPS = ("1er janvier", "1er d'un autre mois", "autre jour")


def _first_of_month_section(
    records: dict[int, SourceRecordDates], by_publication: dict[int, list[int]]
) -> list[str]:
    """Dates au 1er du mois d'OpenAlex et de ScanR, confrontées aux dates des autres sources de la même publication."""
    lines = [
        "## 1er du mois d'OpenAlex et de ScanR",
        "",
        "Chaque enregistrement source d'OpenAlex ou de ScanR rattaché à une publication est confronté aux dates de référence des enregistrements sources d'autres sources de la même publication, hors OpenAlex et ScanR. « Autre jour » sert de témoin. Le mois est confronté aux dates au mois ou au jour, le jour aux dates au jour.",
        "",
    ]
    publication_of = {rid: pid for pid, rids in by_publication.items() for rid in rids}
    rows = []
    for source in _FIRST_OF_MONTH_SOURCES:
        stats: dict[str, Counter[str]] = defaultdict(Counter)
        for r in records.values():
            value = _reference(r)
            if r.source != source or not value or len(value) != 10 or r.id not in publication_of:
                continue
            s = stats[_first_of_month_group(value)]
            s["total"] += 1
            others = [
                o
                for rid in by_publication[publication_of[r.id]]
                if (other := records[rid]).source not in _FIRST_OF_MONTH_SOURCES
                and (o := _reference(other))
            ]
            months = [o for o in others if len(o) >= 7]
            days = [o for o in others if len(o) == 10]
            if others:
                s["confrontés à l'année"] += 1
                s["même année"] += all(o[:4] == value[:4] for o in others)
            if months:
                s["confrontés au mois"] += 1
                s["même mois"] += any(o[:7] == value[:7] for o in months)
            if days:
                s["confrontés au jour"] += 1
                s["même jour"] += value in days
        for group in _FIRST_OF_MONTH_GROUPS:
            s = stats[group]
            rows.append(
                (
                    source,
                    group,
                    s["total"],
                    _pct(s["même année"], s["confrontés à l'année"]),
                    s["confrontés au mois"],
                    _pct(s["même mois"], s["confrontés au mois"]),
                    s["confrontés au jour"],
                    _pct(s["même jour"], s["confrontés au jour"]),
                )
            )
    return lines + _table(
        (
            "Source",
            "Date",
            "Enregistrements",
            "Toujours même année",
            "Confrontés au mois",
            "Un même mois",
            "Confrontés au jour",
            "Un même jour",
        ),
        rows,
    )


def _gap_bucket(days: int) -> str:
    days = abs(days)
    if days == 0:
        return "0 j"
    if days <= 7:
        return "≤ 7 j"
    if days <= 31:
        return "≤ 31 j"
    if days <= 365:
        return "≤ 1 an"
    return "> 1 an"


_BUCKETS = ("0 j", "≤ 7 j", "≤ 31 j", "≤ 1 an", "> 1 an")


def _pairs_section(
    records: dict[int, SourceRecordDates], by_publication: dict[int, list[int]]
) -> list[str]:
    """Écarts entre les dates de référence de deux enregistrements sources de sources différentes d'une même publication. Une paire de sources compte une fois par publication."""
    agreement: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    gaps: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for rids in by_publication.values():
        seen: set[tuple[str, str]] = set()
        refs = [(records[rid].source, v) for rid in rids if (v := _reference(records[rid]))]
        for (sa, va), (sb, vb) in combinations(sorted(refs), 2):
            if sa == sb or (sa, sb) in seen:
                continue
            seen.add((sa, sb))
            agreement[(sa, sb)][_compare(va, vb)] += 1
            if len(va) == len(vb) == 10:
                gaps[(sa, sb)][_gap_bucket((_to_date(vb) - _to_date(va)).days)] += 1
    rows = []
    for pair, c in sorted(agreement.items()):
        total = sum(c.values())
        rows.append(
            (
                " / ".join(pair),
                total,
                _pct(c["accord"], total),
                _pct(c["année différente"], total),
                _pct(c["mois différent"], total),
                _pct(c["jour différent"], total),
            )
        )
    gap_rows = []
    for pair, c in sorted(gaps.items()):
        total = sum(c.values())
        gap_rows.append((" / ".join(pair), total, *(_pct(c[b], total) for b in _BUCKETS)))
    return [
        "## Écarts entre sources",
        "",
        "Date de référence de chaque source : HAL `publicationDate_s`, OpenAlex `publication_date`, Crossref `issued`, DataCite `Issued` (à défaut `publicationYear`), ScanR `publicationDate`, theses.fr `dateSoutenance`, WoS `sortdate` (à défaut la plus ancienne des dates d'accès anticipé et de parution, à défaut l'année). Comparaison à la précision commune des deux dates.",
        "",
        *_table(
            (
                "Paire",
                "Publications",
                "Accord",
                "Année différente",
                "Mois différent",
                "Jour différent",
            ),
            rows,
        ),
        "Écart en jours, quand les deux dates sont au jour :",
        "",
        *_table(("Paire", "Publications", *_BUCKETS), gap_rows),
    ]


def _crossref_section(records: dict[int, SourceRecordDates]) -> list[str]:
    """Date en ligne et date papier de Crossref, et date `issued` rapportée à chacune."""
    issued_is: Counter[str] = Counter()
    gaps: Counter[str] = Counter()
    later: Counter[str] = Counter()
    total = 0
    for r in records.values():
        if r.source != "crossref":
            continue
        total += 1
        online, printed = r.fields.get("published-online"), r.fields.get("published-print")
        issued = r.fields.get("issued")
        key = (
            "en ligne et papier"
            if online and printed
            else "en ligne seule"
            if online
            else "papier seule"
            if printed
            else "aucune"
        )
        issued_is[key] += 1
        if issued and online and printed:
            earliest = min(online, printed)
            issued_is["issued = plus ancienne"] += issued == earliest
            if len(online) == len(printed) == 10:
                delta = (_to_date(printed) - _to_date(online)).days
                gaps[_gap_bucket(delta)] += 1
                later["papier après en ligne" if delta > 0 else "papier avant ou même jour"] += 1
                later["années différentes"] += online[:4] != printed[:4]
    both = issued_is["en ligne et papier"]
    day_pairs = sum(gaps.values())
    return [
        "## Crossref : date en ligne et date papier",
        "",
        *_table(
            ("Dates présentes", "Enregistrements"),
            [
                (k, _pct(issued_is[k], total))
                for k in ("en ligne et papier", "en ligne seule", "papier seule", "aucune")
            ],
        ),
        f"Quand les deux sont présentes, `issued` est la plus ancienne dans {_pct(issued_is['issued = plus ancienne'], both)} des cas.",
        "",
        f"Écart papier − en ligne, les deux au jour ({day_pairs} enregistrements) : papier après en ligne {_pct(later['papier après en ligne'], day_pairs)}, années différentes {_pct(later['années différentes'], day_pairs)}.",
        "",
        *_table(_BUCKETS, [[_pct(gaps[b], day_pairs) for b in _BUCKETS]]),
    ]


def _online_or_print_section(
    records: dict[int, SourceRecordDates], by_publication: dict[int, list[int]]
) -> list[str]:
    """Pour les publications où Crossref a une date en ligne et une date papier de mois différents, mois de la date de référence de chaque autre source rapporté à ces deux dates."""
    stats: dict[str, Counter[str]] = defaultdict(Counter)
    for rids in by_publication.values():
        crossref = [records[rid] for rid in rids if records[rid].source == "crossref"]
        if len(crossref) != 1:
            continue
        online = crossref[0].fields.get("published-online")
        printed = crossref[0].fields.get("published-print")
        if not (online and printed and len(online) >= 7 and len(printed) >= 7):
            continue
        if online[:7] == printed[:7]:
            continue
        seen: set[str] = set()
        for rid in rids:
            r = records[rid]
            ref = _reference(r)
            if r.source == "crossref" or r.source in seen or not ref or len(ref) < 7:
                continue
            seen.add(r.source)
            s = stats[r.source]
            s["total"] += 1
            if ref[:7] == online[:7]:
                s["en ligne"] += 1
            elif ref[:7] == printed[:7]:
                s["papier"] += 1
            else:
                s["autre"] += 1
    rows = [
        (
            source,
            s["total"],
            _pct(s["en ligne"], s["total"]),
            _pct(s["papier"], s["total"]),
            _pct(s["autre"], s["total"]),
        )
        for source, s in sorted(stats.items())
    ]
    return [
        "## Date en ligne ou date papier",
        "",
        "Publications où Crossref a une date en ligne et une date papier de mois différents. Mois de la date de référence de chaque autre source, quand elle est au moins au mois.",
        "",
        *_table(("Source", "Publications", "Mois en ligne", "Mois papier", "Autre mois"), rows),
    ]


def _year_column_section(records: dict[int, SourceRecordDates]) -> list[str]:
    """Année de la date de référence rapportée à `source_records.publication_year`."""
    stats: dict[str, Counter[str]] = defaultdict(Counter)
    for r in records.values():
        ref = _reference(r)
        year = r.fields.get("publication_year")
        if ref and year:
            stats[r.source]["total"] += 1
            stats[r.source]["accord"] += ref[:4] == year
    rows = [
        (source, s["total"], _pct(s["total"] - s["accord"], s["total"]))
        for source, s in sorted(stats.items())
    ]
    return [
        "## Année de la date et colonne `publication_year`",
        "",
        *_table(("Source", "Enregistrements", "Année différente"), rows),
    ]


def _wos_section(records: dict[int, SourceRecordDates]) -> list[str]:
    """Champs WoS : `sortdate` rapporté aux dates d'accès anticipé et de parution."""
    c: Counter[str] = Counter()
    for r in records.values():
        if r.source != "wos":
            continue
        if "export.PY" in r.fields:
            c["export"] += 1
        elif "api.pubyear" in r.fields:
            c["api"] += 1
        else:
            c["payload absent"] += 1
        early, cover = _wos_early_access(r.fields), _wos_cover(r.fields)
        sortdate = r.fields.get("api.sortdate")
        if sortdate and cover:
            earliest = min(d[:7] for d in (early, cover) if d)
            c["sortdate+coverdate"] += 1
            c["sortdate dans le mois le plus ancien"] += sortdate[:7] == earliest
            if len(cover) < 10 and not early:
                c["coverdate imprécise"] += 1
                c["sortdate au 1er"] += sortdate.endswith("-01")
        if early and cover:
            c["accès anticipé"] += 1
            c["accès anticipé avant"] += early[:7] < cover[:7]
            c["accès anticipé autre année"] += early[:4] != cover[:4]
    return [
        "## WoS",
        "",
        f"Payloads de l'API : {c['api']}. Lignes d'export tabulé : {c['export']}. Payloads absents du raw store : {c['payload absent']}.",
        "",
        f"API, `sortdate` et `coverdate` présents ({c['sortdate+coverdate']}) : `sortdate` tombe dans le mois le plus ancien des dates d'accès anticipé et de parution dans {_pct(c['sortdate dans le mois le plus ancien'], c['sortdate+coverdate'])} des cas. Sans accès anticipé, quand `coverdate` est à l'année ou au mois ({c['coverdate imprécise']}), `sortdate` tombe le 1er dans {_pct(c['sortdate au 1er'], c['coverdate imprécise'])} des cas.",
        "",
        f"Date d'accès anticipé et date de parution présentes ({c['accès anticipé']}) : accès anticipé antérieur au mois de parution {_pct(c['accès anticipé avant'], c['accès anticipé'])}, année différente {_pct(c['accès anticipé autre année'], c['accès anticipé'])}.",
        "",
    ]


def _hal_section(records: dict[int, SourceRecordDates]) -> list[str]:
    total = differ = 0
    for r in records.values():
        if r.source == "hal" and (d := r.fields.get("publicationDate_s")):
            if y := r.fields.get("producedDateY_i"):
                total += 1
                differ += d[:4] != y
    return [
        "## HAL",
        "",
        f"Année de `publicationDate_s` différente de `producedDateY_i` : {differ} sur {total} ({_pct(differ, total)}).",
        "",
    ]


def analyze(path: Path, report: Path) -> None:
    records, by_publication, unparsed = _load(path)
    log.info("%d enregistrements sources, %d publications", len(records), len(by_publication))
    lines = [
        "# Dates de publication des sources",
        "",
        f"Mesure du {today().isoformat()} sur {len(records)} enregistrements sources et {len(by_publication)} publications.",
        "",
        *_precision_section(records),
        *_unparsed_section(unparsed),
        *_year_column_section(records),
        *_first_of_month_section(records, by_publication),
        *_pairs_section(records, by_publication),
        *_crossref_section(records),
        *_online_or_print_section(records, by_publication),
        *_wos_section(records),
        *_hal_section(records),
    ]
    report.write_text("\n".join(lines), encoding="utf-8")
    log.info("Rapport écrit dans %s", report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("step", choices=("extract", "analyze"))
    parser.add_argument("--extract-file", type=Path, default=_DEFAULT_EXTRACT)
    parser.add_argument("--report", type=Path, default=_DEFAULT_REPORT)
    args = parser.parse_args()
    if args.step == "extract":
        extract(args.extract_file)
    else:
        analyze(args.extract_file, args.report)


if __name__ == "__main__":
    main()
