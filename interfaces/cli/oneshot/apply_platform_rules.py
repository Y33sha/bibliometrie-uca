# STATUS: oneshot (2026-11-01)
"""Applique aux enregistrements sources déjà normalisés les règles de la normalisation sur les plateformes, sans relire le raw store.

- La série qui désigne une plateforme est retirée de `biblio.journal` (`names_platform`). Les candidats ont une série, et un DOI de serveur de preprints dans `staging` ou une source OpenAlex du registre des plateformes.
- Le DOI d'un serveur de preprints donne une copie sur ce serveur (`preprint_copy_url`), ouverte si le serveur donne librement accès à tout son contenu. Une copie de même URL déjà présente devient ouverte au besoin.

Les enregistrements sources qui gagnent une copie sont mis en file pour la consolidation de leur publication. La phase `publishing` détache de leur revue ceux qui perdent leur série.

Usage :
    uv run python -m interfaces.cli.oneshot.apply_platform_rules [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter

from sqlalchemy import Connection, text

from domain.platforms.platform import PlatformType
from domain.platforms.registry import (
    KNOWN_PLATFORMS,
    is_fully_open,
    names_platform,
    preprint_copy_url,
)
from domain.source_records.biblio import BiblioKey, JournalKey, with_journal
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.queues import Queue, enqueue
from infrastructure.observability.log import setup_logger

log = setup_logger("apply_platform_rules", os.path.dirname(__file__))

_PREPRINT_PREFIXES = sorted(
    {
        prefix
        for p in KNOWN_PLATFORMS
        if p.platform_type is PlatformType.PREPRINT_SERVER
        for prefix in p.doi_prefixes
    }
)
_OPENALEX_IDS = sorted({i for p in KNOWN_PLATFORMS for i in p.openalex_ids})

_SERIES_CANDIDATES = text("""
    SELECT sr.id, sr.source::text AS source, sr.biblio, st.doi
    FROM source_records sr
    LEFT JOIN staging st ON st.id = sr.staging_id
    WHERE sr.biblio ? 'journal'
      AND (st.doi ILIKE ANY(:doi_patterns)
           OR sr.biblio->'journal'->>'openalex_id' = ANY(:openalex_ids))
""")

_WRITE_BIBLIO = text("""
    UPDATE source_records sr SET biblio = NULLIF(t.biblio, 'null'::jsonb)
    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS t(id integer, biblio jsonb)
    WHERE sr.id = t.id
""")

# Même sélection que la normalisation : tout DOI de l'enregistrement source, sauf un DOI lié.
_PREPRINT_DOIS = text("""
    SELECT source_record_id, id_value FROM source_record_identifiers
    WHERE id_type = 'doi' AND role <> 'related' AND split_part(id_value, '/', 1) = ANY(:prefixes)
""")

_OPEN_COPIES = text("""
    UPDATE source_record_locations l SET is_oa = true
    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS c(id integer, url text, is_oa boolean)
    WHERE l.source_record_id = c.id AND l.url = c.url AND c.is_oa AND l.is_oa IS NOT TRUE
    RETURNING l.source_record_id
""")

_INSERT_COPIES = text("""
    INSERT INTO source_record_locations (source_record_id, url, is_oa)
    SELECT c.id, c.url, c.is_oa
    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS c(id integer, url text, is_oa boolean)
    WHERE NOT EXISTS (
        SELECT 1 FROM source_record_locations l WHERE l.source_record_id = c.id AND l.url = c.url
    )
    RETURNING source_record_id
""")


def _platform_series(conn: Connection) -> list[dict[str, object]]:
    """Renvoie la `biblio` sans série des enregistrements sources dont la série désigne une plateforme."""
    candidates = conn.execute(
        _SERIES_CANDIDATES,
        {"doi_patterns": [f"%{p}/%" for p in _PREPRINT_PREFIXES], "openalex_ids": _OPENALEX_IDS},
    ).all()
    rows: list[dict[str, object]] = []
    titles: Counter[tuple[str, str]] = Counter()
    for r in candidates:
        journal = r.biblio.get(BiblioKey.JOURNAL) or {}
        title = journal.get(JournalKey.TITLE)
        if names_platform([title], openalex_id=journal.get(JournalKey.OPENALEX_ID), doi=r.doi):
            rows.append({"id": r.id, "biblio": with_journal(r.biblio, None)})
            titles[(r.source, str(title))] += 1
    log.info("Séries : %d candidats, %d séries de plateforme", len(candidates), len(rows))
    for (source, title), n in titles.most_common(20):
        log.info("  %s « %s » : %d", source, title, n)
    return rows


def _preprint_copies(conn: Connection) -> list[dict[str, object]]:
    """Renvoie la copie sur le serveur de preprints de chaque DOI de serveur de preprints."""
    copies: list[dict[str, object]] = []
    for source_record_id, doi in conn.execute(_PREPRINT_DOIS, {"prefixes": _PREPRINT_PREFIXES}):
        if url := preprint_copy_url(doi):
            copies.append({"id": source_record_id, "url": url, "is_oa": is_fully_open(url)})
    log.info(
        "Copies : %d DOI de serveur de preprints, dont %d sur un serveur ouvert",
        len(copies),
        sum(1 for c in copies if c["is_oa"]),
    )
    return copies


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Compte les cibles sans rien écrire")
    args = parser.parse_args()
    with get_sync_engine().connect() as conn:
        series = _platform_series(conn)
        copies = _preprint_copies(conn)
        if args.dry_run:
            log.info("Dry-run, rien écrit.")
            return
        if series:
            conn.execute(_WRITE_BIBLIO, {"rows": json.dumps(series)})
        changed: set[int] = set()
        if copies:
            params = {"rows": json.dumps(copies)}
            opened = set(conn.execute(_OPEN_COPIES, params).scalars())
            inserted = set(conn.execute(_INSERT_COPIES, params).scalars())
            log.info("%d copies ouvertes, %d copies ajoutées", len(opened), len(inserted))
            changed = opened | inserted
        if changed:
            enqueue(
                conn,
                Queue.SOURCE_RECORD_KEYS,
                "SELECT unnest(CAST(:ids AS integer[]))",
                {"ids": sorted(changed)},
            )
        conn.commit()
        log.info(
            "%d séries retirées, %d enregistrements sources mis en file", len(series), len(changed)
        )


if __name__ == "__main__":
    main()
