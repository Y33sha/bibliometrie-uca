# STATUS: oneshot (2026-09-20)
"""Audit (lecture seule) : ISBN présents dans le raw store et que la normalisation ne lit pas.

Seul Crossref alimente `external_ids.isbn`. Les autres sources portent pourtant l'ISBN dans leur
notice brute, chacune à sa place :

- HAL : la notice TEI de `label_xml`, zone `<idno type="isbn">` ;
- DataCite : un `relatedIdentifiers` de type `ISBN`, ou le conteneur quand son identifiant est un ISBN ;
- WoS : un identifiant de type `isbn` ou `eisbn` ;
- ScanR : les identifiants externes.

L'audit porte sur les enregistrements de type livre, chapitre, communication ou recueil d'actes. Il
mesure, par source, la part qui porte un ISBN, puis la part des publications et des conteneurs de
chapitres que cet ISBN identifierait.

Usage :
    python -m interfaces.cli.oneshot.audit_isbn_in_raw_store [--limit N]
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter, defaultdict

from sqlalchemy import text

from domain.types import JsonValue, as_mapping, as_sequence, as_str
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.raw_store.base import RawStore
from infrastructure.raw_store.factory import get_raw_store

log = setup_logger("audit_isbn_in_raw_store", os.path.dirname(__file__))

_DOC_TYPES = ("book", "book_chapter", "conference_paper", "proceedings")

_RECORDS = """
    SELECT s.source::text AS source, s.source_id, s.doc_type::text AS doc_type,
           s.publication_id, s.external_ids->>'isbn' AS isbn_lu,
           lower(s.doi) AS doi, lower(p.container_title) AS conteneur
    FROM source_publications s
    LEFT JOIN publications p ON p.id = s.publication_id
    WHERE s.doc_type = ANY(CAST(:types AS text[]))
"""

_TEI_ISBN = re.compile(r'<idno[^>]*type="isbn"[^>]*>([^<]+)', re.IGNORECASE)
# ISBN à 13 chiffres porté par un DOI (`10.1007/978-3-030-58080-3_309`).
_ISBN_IN_DOI = re.compile(r"97[89](?:-?\d){10}")


def _hal_isbn(payload: JsonValue) -> str | None:
    match = _TEI_ISBN.search(as_str(as_mapping(payload).get("label_xml")) or "")
    return match.group(1).strip() if match else None


def _datacite_isbn(payload: JsonValue) -> str | None:
    attributes = as_mapping(as_mapping(payload).get("attributes"))
    for related in as_sequence(attributes.get("relatedIdentifiers")):
        entry = as_mapping(related)
        if (as_str(entry.get("relatedIdentifierType")) or "").upper() == "ISBN":
            return as_str(entry.get("relatedIdentifier"))
    container = as_mapping(attributes.get("container"))
    if (as_str(container.get("identifierType")) or "").upper() == "ISBN":
        return as_str(container.get("identifier"))
    return None


def _wos_isbn(payload: JsonValue) -> str | None:
    cluster = as_mapping(as_mapping(as_mapping(payload).get("dynamic_data")).get("cluster_related"))
    identifiers = as_mapping(cluster.get("identifiers")).get("identifier")
    entries = as_sequence(identifiers) if isinstance(identifiers, list) else [identifiers]
    for entry in entries:
        identifier = as_mapping(entry)
        if "isbn" in (as_str(identifier.get("type")) or "").lower():
            return as_str(identifier.get("value"))
    return None


def _scanr_isbn(payload: JsonValue) -> str | None:
    for external in as_sequence(as_mapping(payload).get("externalIds")):
        entry = as_mapping(external)
        if "isbn" in (as_str(entry.get("type")) or "").lower():
            return as_str(entry.get("id"))
    return None


_READERS = {
    "hal": _hal_isbn,
    "datacite": _datacite_isbn,
    "wos": _wos_isbn,
    "scanr": _scanr_isbn,
}


def _isbn_from_raw(store: RawStore, source: str, source_id: str) -> tuple[str, str | None]:
    """État du raw store pour cet enregistrement, et l'ISBN qu'il porte."""
    reader = _READERS.get(source)
    if reader is None:
        return "source sans lecteur", None
    try:
        payload = json.loads(store.get(source, source_id))
    except KeyError:
        return "absent du raw store", None
    return "lu", reader(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="Nombre d'enregistrements examinés au plus.")
    args = parser.parse_args()

    store = get_raw_store()
    with get_sync_engine().connect() as conn:
        rows = conn.execute(text(_RECORDS), {"types": list(_DOC_TYPES)}).all()
    if args.limit:
        rows = rows[: args.limit]

    par_source: Counter[tuple[str, str]] = Counter()
    isbn_par_publication: defaultdict[int, set[str]] = defaultdict(set)
    deja_lu: set[int] = set()
    conteneurs: defaultdict[str, set[str]] = defaultdict(set)
    conteneurs_connus: set[str] = set()
    for row in rows:
        etat, isbn = _isbn_from_raw(store, row.source, row.source_id)
        par_source[(row.source, "ISBN dans la notice" if isbn else etat)] += 1
        if row.publication_id is None:
            continue
        if row.isbn_lu or (row.doi and _ISBN_IN_DOI.search(row.doi)):
            deja_lu.add(row.publication_id)
            if row.conteneur:
                conteneurs_connus.add(row.conteneur)
        if isbn:
            isbn_par_publication[row.publication_id].add(isbn)
            if row.conteneur:
                conteneurs[row.conteneur].add(isbn)

    log.info("─── ISBN par source ───")
    log.info("Enregistrements de type livre, chapitre, communication ou recueil : %d", len(rows))
    for (source, etat), n in sorted(par_source.items()):
        log.info("  %-10s %-22s %6d", source, etat, n)

    gain = set(isbn_par_publication) - deja_lu
    log.info("─── Ce que la lecture apporterait ───")
    log.info("Publications qui gagneraient un ISBN : %d", len(gain))
    log.info(
        "Publications dont les notices donnent plusieurs ISBN : %d",
        sum(1 for isbns in isbn_par_publication.values() if len(isbns) > 1),
    )
    nouveaux = set(conteneurs) - conteneurs_connus
    log.info(
        "Conteneurs de chapitres : %d identifiés par un ISBN, dont %d nouveaux",
        len(conteneurs),
        len(nouveaux),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
