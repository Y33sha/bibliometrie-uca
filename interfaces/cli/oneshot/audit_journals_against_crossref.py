# STATUS: oneshot (2026-09-18)
"""Audit (lecture seule) : revues des enregistrements face à celle de Crossref, avant la correction des revues erronées.

Trois mesures :

1. **Écarts à Crossref** : dans une publication qui a un enregistrement Crossref rattaché à une revue, les autres enregistrements rattachés à une autre revue, par source. Un écart sur le même DOI que Crossref est corrigeable ; un écart sans DOI peut venir d'enregistrements réunis à tort. Un écart entre deux revues aux titres compatibles ou à ISSN commun est un doublon de revues resté à fusionner.
2. **Divergences sans Crossref** : publications dont les enregistrements portent plusieurs revues, sans enregistrement Crossref rattaché à une revue, selon l'agence du DOI de la publication.
3. **Préprints DataCite** : ceux qui partagent une publication avec un enregistrement Crossref, ceux qu'une relation lie au DOI d'un enregistrement Crossref, leur revue et leur déposant.

Les revues rattachées par le préfixe du DOI (phase `metadata_correction`) sont écartées : seules comptent les revues que les sources donnent.

Usage :
    python -m interfaces.cli.oneshot.audit_journals_against_crossref
"""

from __future__ import annotations

import os
from collections import Counter, defaultdict

from sqlalchemy import Connection, text

from domain.journals.titles import compatible_titles
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("audit_journals_against_crossref", os.path.dirname(__file__))

_SOURCE_JOURNALS = """
    SELECT s.id, s.publication_id, s.source::text AS source, s.doi, s.journal_id
    FROM source_publications s
    WHERE s.publication_id IS NOT NULL AND s.journal_id IS NOT NULL
      AND NOT (s.raw_metadata ? 'journal_id')
"""

_JOURNALS = """
    SELECT id, title, array_remove(ARRAY[issn, eissn, issnl], NULL) || rejected_issns AS issns
    FROM journals
"""

_PUBLICATION_RA = """
    SELECT p.id, dp.ra
    FROM publications p
    LEFT JOIN doi_prefixes dp ON dp.prefix = split_part(p.doi, '/', 1)
"""

_DATACITE_PREPRINTS = """
    SELECT s.id, s.publication_id, s.journal_id, s.container_title,
           s.raw_metadata ? 'journal_id' AS by_doi_prefix,
           s.biblio->>'publisher' AS depositor, s.meta->'related_identifiers' AS relations
    FROM source_publications s
    WHERE s.source = 'datacite' AND s.doc_type = 'preprint'
"""

_CROSSREF_DOIS = """
    SELECT lower(doi) AS doi, publication_id
    FROM source_publications
    WHERE source = 'crossref' AND doi IS NOT NULL
"""


def _same_journal_family(a: tuple[str, set[str]], b: tuple[str, set[str]]) -> bool:
    """Deux revues aux titres compatibles ou à ISSN commun : un doublon resté à fusionner."""
    return compatible_titles(a[0], b[0]) or bool(a[1] & b[1])


def _crossref_gaps(conn: Connection, journals: dict[int, tuple[str, set[str]]]) -> None:
    rows = conn.execute(text(_SOURCE_JOURNALS)).all()
    crossref = {r.publication_id: r for r in rows if r.source == "crossref"}
    gaps: Counter[tuple[str, str, str]] = Counter()
    publications: defaultdict[tuple[str, str, str], set[int]] = defaultdict(set)
    agreeing: Counter[str] = Counter()
    for r in rows:
        ref = crossref.get(r.publication_id)
        if ref is None or r.source == "crossref":
            continue
        if r.journal_id == ref.journal_id:
            agreeing[r.source] += 1
            continue
        doi = "même DOI" if r.doi and r.doi == ref.doi else "sans DOI" if not r.doi else "autre DOI"
        kind = (
            "doublon de revues"
            if _same_journal_family(journals[r.journal_id], journals[ref.journal_id])
            else "revue différente"
        )
        gaps[(r.source, doi, kind)] += 1
        publications[(r.source, doi, kind)].add(r.publication_id)

    log.info("─── 1. Écarts à Crossref ───")
    log.info("Publications dont un enregistrement Crossref donne la revue : %d", len(crossref))
    log.info(
        "Publications où une autre source donne une autre revue : %d",
        len({p for ps in publications.values() for p in ps}),
    )
    for source in sorted({k[0] for k in gaps} | set(agreeing)):
        log.info("  %s : %d enregistrements concordants", source, agreeing[source])
        for (s, doi, kind), n in sorted(gaps.items()):
            if s == source:
                log.info(
                    "      %-9s %-17s %5d enregistrements, %5d publications",
                    doi,
                    kind,
                    n,
                    len(publications[(s, doi, kind)]),
                )


def _divergences_without_crossref(conn: Connection) -> None:
    rows = conn.execute(text(_SOURCE_JOURNALS)).all()
    ra: dict[int, str | None] = {r.id: r.ra for r in conn.execute(text(_PUBLICATION_RA))}
    journals_by_publication: defaultdict[int, defaultdict[int, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for r in rows:
        journals_by_publication[r.publication_id][r.journal_id].add(r.source)
    divergent = {p: js for p, js in journals_by_publication.items() if len(js) > 1}
    without = {
        p: js
        for p, js in divergent.items()
        if not any("crossref" in sources for sources in js.values())
    }
    log.info("─── 2. Divergences sans Crossref ───")
    log.info("Publications divergentes : %d, dont %d sans Crossref", len(divergent), len(without))
    by_ra = Counter(ra.get(p) or "sans DOI" for p in without)
    for agency, n in by_ra.most_common():
        log.info("  DOI %s : %d publications", agency, n)
    combos = Counter(
        " ⟂ ".join(sorted("+".join(sorted(s)) for s in js.values())) for js in without.values()
    )
    for combo, n in combos.most_common(10):
        log.info("  %5d  %s", n, combo)


def _datacite_preprints(conn: Connection) -> None:
    rows = conn.execute(text(_DATACITE_PREPRINTS)).all()
    crossref_dois: dict[str, int] = {
        r.doi: r.publication_id for r in conn.execute(text(_CROSSREF_DOIS))
    }
    with_crossref = {
        p
        for (p,) in conn.execute(
            text(
                "SELECT DISTINCT publication_id FROM source_publications"
                " WHERE source = 'crossref' AND publication_id IS NOT NULL"
            )
        )
    }
    same_publication = sum(1 for r in rows if r.publication_id in with_crossref)
    relations: Counter[tuple[str, str]] = Counter()
    for r in rows:
        for rel in r.relations or []:
            target = crossref_dois.get((rel.get("doi") or "").lower())
            if target is None:
                continue
            where = "même publication" if target == r.publication_id else "autre publication"
            relations[(rel.get("relation_type") or "?", where)] += 1
    log.info("─── 3. Préprints DataCite ───")
    log.info("Préprints DataCite : %d", len(rows))
    log.info("  dans une publication qui a un enregistrement Crossref : %d", same_publication)
    attached = [r for r in rows if r.journal_id is not None]
    log.info(
        "  rattachés à une revue : %d par la source, %d par le préfixe DOI",
        sum(1 for r in attached if not r.by_doi_prefix),
        sum(1 for r in attached if r.by_doi_prefix),
    )
    log.info("  relations vers le DOI d'un enregistrement Crossref :")
    for (relation, where), n in relations.most_common():
        log.info("      %-20s %-17s %5d", relation, where, n)
    log.info("  déposants :")
    for depositor, n in Counter(r.depositor for r in rows).most_common(8):
        log.info("      %5d  %s", n, depositor)


def main() -> int:
    with get_sync_engine().connect() as conn:
        journals = {r.id: (r.title, set(r.issns)) for r in conn.execute(text(_JOURNALS)).all()}
        _crossref_gaps(conn, journals)
        _divergences_without_crossref(conn)
        _datacite_preprints(conn)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
