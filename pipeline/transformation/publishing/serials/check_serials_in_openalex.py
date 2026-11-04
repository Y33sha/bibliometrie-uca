"""Sous-étape de la phase `publishing` : métadonnées des revues dans OpenAlex.

Sont cherchées les métadonnées des revues jamais cherchées, ou cherchées depuis plus de `serial_openalex_recheck_after_days` jours. Une revue à ISSN prend la source OpenAlex de ses ISSN, celle qui a le plus de works quand ses ISSN en désignent plusieurs. Une revue sans ISSN prend la source la plus fréquente parmi ses enregistrements sources OpenAlex sans ISSN. La recherche pose l'identifiant OpenAlex de la revue et son type s'il est inconnu. Elle réécrit ses appartenances aux listes de `serial_lists`. Une source retenue par plusieurs revues donne son identifiant à celle qui a le plus de publications, et ses listes à toutes.

Les requêtes à OpenAlex sont injectées (`pipeline/ingestion/openalex/sources.py`). Les revues d'un lot en échec restent à chercher, comme celles des lots suivants quand le circuit-breaker de la source coupe.
"""

import json
import logging
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Connection, text

from domain.entity_resolution import most_frequent
from domain.serials.openalex_sources import Claimant, holder, main_source, serial_type_of_source
from domain.serials.serial import ManualField, SerialType
from domain.sources.openalex import OpenAlexSource, OpenAlexSourceList
from pipeline.http.circuit_breaker import source_tripped
from pipeline.ingestion.openalex.sources import SOURCES_BATCH, SourceFilter
from pipeline.runtime.observability.log_format import BRANCH, quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import Progress, track_progress

LABEL = "Métadonnées des revues dans OpenAlex"
"""Libellé de la sous-étape dans le journal de la phase."""

FetchSources = Callable[[SourceFilter, Sequence[str]], list[OpenAlexSource] | None]
"""`(filtre, valeurs) -> sources` : sources OpenAlex d'un lot d'ISSN ou d'identifiants, `None` si la requête échoue."""

FetchSourceLists = Callable[[], list[OpenAlexSourceList] | None]
"""Listes de revues d'OpenAlex, `None` si la requête échoue."""

_TO_SEARCH = text("""
    SELECT s.id, s.publication_count,
           coalesce(array_agg(i.issn ORDER BY i.issn) FILTER (WHERE i.issn IS NOT NULL), '{}')
               AS issns
    FROM serials s
    LEFT JOIN serial_issns i ON i.serial_id = s.id
    WHERE s.openalex_checked_at IS NULL
       OR s.openalex_checked_at < now() - make_interval(days => :days)
    GROUP BY s.id
    ORDER BY s.id
""")

_RECORD_SOURCES = text("""
    SELECT serial_id, biblio->'journal'->>'openalex_id' AS openalex_id
    FROM source_records
    WHERE source = 'openalex' AND serial_id = ANY(:ids)
      AND biblio->'journal'->>'openalex_id' IS NOT NULL
      AND coalesce(jsonb_array_length(biblio->'journal'->'issns'), 0) = 0
""")
"""Source des enregistrements sources OpenAlex sans ISSN des revues `ids`."""

_HOLDERS = text(
    "SELECT openalex_id, id, publication_count FROM serials WHERE openalex_id = ANY(:ids)"
)

_LIST_CODES = text("SELECT code FROM serial_lists")

_WRITE_LISTS = text("""
    UPDATE serial_lists l
    SET maintainer = t.maintainer, url = t.url, edition = CAST(t.edition AS date)
    FROM jsonb_to_recordset(CAST(:rows AS jsonb))
        AS t(code text, maintainer text, url text, edition text)
    WHERE l.code = t.code
""")

_CLEAR_IDS = text(
    "UPDATE serials SET openalex_id = NULL WHERE id = ANY(:ids) AND openalex_id IS NOT NULL"
)

_WRITE_IDS = text("""
    UPDATE serials s SET openalex_id = t.openalex_id
    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS t(id integer, openalex_id text)
    WHERE s.id = t.id
""")

_WRITE_TYPES = text(f"""
    UPDATE serials s SET serial_type = CAST(t.serial_type AS serial_type)
    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS t(id integer, serial_type text)
    WHERE s.id = t.id AND s.serial_type = '{SerialType.UNKNOWN.value}'
      AND NOT '{ManualField.SERIAL_TYPE.value}' = ANY(s.manual_fields)
""")

_DELETE_ENTRIES = text("DELETE FROM serial_list_entries WHERE serial_id = ANY(:ids)")

_INSERT_ENTRIES = text("""
    INSERT INTO serial_list_entries (serial_id, list_code)
    SELECT t.serial_id, t.list_code
    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS t(serial_id integer, list_code text)
""")

_MARK_SEARCHED = text("UPDATE serials SET openalex_checked_at = :at WHERE id = ANY(:ids)")


@dataclass(frozen=True, slots=True)
class _Serial:
    id: int
    publication_count: int
    issns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Search:
    """Résultat de la recherche des métadonnées d'une revue dans OpenAlex."""

    source_id: str | None
    """Identifiant OpenAlex réclamé par la revue."""
    source: OpenAlexSource | None
    """Source qui donne le type de la revue."""
    listed_in: frozenset[str]


_NOT_FOUND = _Search(None, None, frozenset())


def run_check_serials_in_openalex(
    conn: Connection,
    logger: logging.Logger,
    *,
    fetch_sources: FetchSources,
    fetch_source_lists: FetchSourceLists,
    recheck_after_days: int,
) -> PhaseMetrics:
    """Cherche dans OpenAlex les métadonnées des revues à chercher, et met à jour l'organisme, l'URL et l'édition des listes de `serial_lists`."""
    serials = [
        _Serial(r.id, r.publication_count, tuple(r.issns))
        for r in conn.execute(_TO_SEARCH, {"days": recheck_after_days})
    ]
    metrics = PhaseMetrics()
    if not serials:
        return metrics
    metrics.add(seen=len(serials))
    _refresh_lists(conn, fetch_source_lists)

    votes = _record_sources(conn, [s.id for s in serials if not s.issns])
    issns = sorted({i for s in serials for i in s.issns})
    voted_ids = sorted(set(votes.values()))
    with track_progress(
        len(issns) + len(voted_ids), f"{BRANCH}{LABEL}", logger, erase=True
    ) as progress:
        issn_sources, fetched_issns = _fetch(fetch_sources, "issn", issns, progress)
        id_sources, fetched_ids = _fetch(fetch_sources, "openalex", voted_ids, progress)

    by_issn: dict[str, list[OpenAlexSource]] = {}
    for source in issn_sources:
        for issn in source.issns:
            by_issn.setdefault(issn, []).append(source)
    by_id = {s.id: s for s in id_sources}
    searches: dict[int, _Search] = {}
    for serial in serials:
        if serial.issns:
            if set(serial.issns) <= fetched_issns:
                searches[serial.id] = _search_by_issns(serial.issns, by_issn)
        elif (source_id := votes.get(serial.id)) is None:
            searches[serial.id] = _NOT_FOUND
        elif source_id in fetched_ids:
            source = by_id.get(source_id)
            listed_in = frozenset(source.listed_in) if source else frozenset()
            searches[serial.id] = _Search(source_id, source, listed_in)

    _write(conn, serials, searches, set(conn.execute(_LIST_CODES).scalars()))
    found = sum(1 for s in searches.values() if s.source is not None)
    metrics.add(updated=len(searches), openalex_found=found)
    metrics.report = (
        f"{quantity(len(searches), 'revue cherchée', 'revues cherchées')}, "
        f"{quantity(found, 'trouvée', 'trouvées')}"
    )
    return metrics


def _refresh_lists(conn: Connection, fetch_source_lists: FetchSourceLists) -> None:
    """Met à jour l'organisme, l'URL et l'édition des listes de `serial_lists` d'après OpenAlex. Un échec laisse les listes en l'état."""
    source_lists = fetch_source_lists()
    if not source_lists:
        return
    rows = [
        {
            "code": s.code,
            "maintainer": s.maintainer,
            "url": s.url,
            "edition": s.edition.isoformat() if s.edition else None,
        }
        for s in source_lists
    ]
    conn.execute(_WRITE_LISTS, {"rows": json.dumps(rows)})


def _record_sources(conn: Connection, serial_ids: list[int]) -> dict[int, str]:
    """Renvoie la source la plus fréquente parmi les enregistrements sources OpenAlex sans ISSN de chaque revue."""
    counts: dict[int, Counter[str]] = {}
    for r in conn.execute(_RECORD_SOURCES, {"ids": serial_ids}):
        counts.setdefault(r.serial_id, Counter())[r.openalex_id] += 1
    return {serial_id: most_frequent(c) for serial_id, c in counts.items()}


def _fetch(
    fetch_sources: FetchSources, key: SourceFilter, values: list[str], progress: Progress
) -> tuple[list[OpenAlexSource], set[str]]:
    """Renvoie les sources des lots aboutis, et les valeurs de ces lots. Les requêtes s'arrêtent quand le circuit-breaker coupe."""
    sources: list[OpenAlexSource] = []
    fetched: set[str] = set()
    for start in range(0, len(values), SOURCES_BATCH):
        if source_tripped():
            break
        batch = values[start : start + SOURCES_BATCH]
        found = fetch_sources(key, batch)
        progress.advance(len(batch))
        if found is not None:
            sources.extend(found)
            fetched.update(batch)
    return sources, fetched


def _search_by_issns(issns: tuple[str, ...], by_issn: dict[str, list[OpenAlexSource]]) -> _Search:
    found = {s.id: s for issn in issns for s in by_issn.get(issn, ())}
    main = main_source(found.values())
    if main is None:
        return _NOT_FOUND
    return _Search(main.id, main, frozenset(c for s in found.values() for c in s.listed_in))


def _write(
    conn: Connection, serials: list[_Serial], searches: dict[int, _Search], list_codes: set[str]
) -> None:
    """Écrit l'identifiant OpenAlex, le type et les appartenances des revues cherchées, et la date de leur recherche."""
    searched_ids = sorted(searches)
    if not searched_ids:
        return
    publication_counts = {s.id: s.publication_count for s in serials}
    claims: dict[str, list[Claimant]] = {}
    for serial_id, search in searches.items():
        if search.source_id is not None:
            claims.setdefault(search.source_id, []).append(
                Claimant(serial_id, publication_counts[serial_id])
            )
    holders = {
        r.openalex_id: Claimant(r.id, r.publication_count)
        for r in conn.execute(_HOLDERS, {"ids": sorted(claims)})
    }
    assigned: dict[int, str] = {}
    dispossessed: list[int] = []
    for source_id, claimants in claims.items():
        candidates = list(claimants)
        current = holders.get(source_id)
        if current is not None and current.serial_id not in searches:
            candidates.append(current)
        winner = holder(candidates)
        if winner in searches:
            assigned[winner] = source_id
            if current is not None and current.serial_id not in searches:
                dispossessed.append(current.serial_id)

    # Les identifiants s'effacent avant d'être réécrits : un identifiant appartient à une seule revue.
    conn.execute(_CLEAR_IDS, {"ids": searched_ids + dispossessed})
    if assigned:
        rows = [{"id": i, "openalex_id": s} for i, s in sorted(assigned.items())]
        conn.execute(_WRITE_IDS, {"rows": json.dumps(rows)})
    types = [
        {"id": serial_id, "serial_type": serial_type.value}
        for serial_id, search in sorted(searches.items())
        if search.source and (serial_type := serial_type_of_source(search.source.type))
    ]
    if types:
        conn.execute(_WRITE_TYPES, {"rows": json.dumps(types)})
    conn.execute(_DELETE_ENTRIES, {"ids": searched_ids})
    entries = [
        {"serial_id": serial_id, "list_code": code}
        for serial_id, search in sorted(searches.items())
        for code in sorted(search.listed_in & list_codes)
    ]
    if entries:
        conn.execute(_INSERT_ENTRIES, {"rows": json.dumps(entries)})
    conn.execute(_MARK_SEARCHED, {"at": datetime.now(UTC), "ids": searched_ids})
