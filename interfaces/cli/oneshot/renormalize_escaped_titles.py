# STATUS: oneshot (2026-06-18)
"""
Renormalise en place les titres `source_publications` HTML-échappés.

Contexte : certains flux source livrent le markup du titre HTML-échappé
(`&lt;sub&gt;` au lieu de `<sub>`). Avant le correctif de
`domain.publications.metadata.clean_publication_title` (qui ne décodait que le
double-encodage), ces titres étaient stockés tels quels — ce qui pollue
`title_normalized` (clé de blocking dédup : `… lt sub gt …`) et l'affichage.

Ce script ré-applique `clean_publication_title` / `normalized_title` aux SP
concernées, met à jour `title` + `title_normalized` quand ils changent, et pose
`keys_dirty = TRUE` pour que la phase `publications` re-déduplique le voisinage
au prochain run — sans re-moissonner (pas de `raw_hash = NULL`).

Idempotent. Après exécution, lancer `python run_pipeline.py --only publications`
(puis les phases aval) pour matérialiser les fusions et ré-agréger les titres
canoniques depuis les sources nettoyées.

Usage :
    python -m interfaces.cli.oneshot.renormalize_escaped_titles [--dry-run] [--limit N]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, text

from domain.publications.metadata import clean_publication_title, normalized_title
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("renormalize_escaped_titles", os.path.dirname(__file__))

_BATCH = 500

# SP dont le titre porte une entité HTML échappée (`&lt;`, `&gt;`, `&amp;`).
# `clean_publication_title` est idempotent : on ne met à jour que ce qui change.
_CANDIDATE_SQL = """
    SELECT id, title, title_normalized
    FROM source_publications
    WHERE title LIKE '%&lt;%' OR title LIKE '%&gt;%' OR title LIKE '%&amp;%'
    ORDER BY id
"""


def _flush(conn: Connection, pending: list[dict[str, object]]) -> None:
    """Applique un lot de mises à jour en une requête (unnest), pas N round-trips."""
    conn.execute(
        text("""
            UPDATE source_publications AS sp
            SET title = d.title, title_normalized = d.tn, keys_dirty = TRUE
            FROM unnest(CAST(:ids AS int[]), CAST(:titles AS text[]), CAST(:tns AS text[]))
                 AS d(id, title, tn)
            WHERE sp.id = d.id
        """),
        {
            "ids": [p["id"] for p in pending],
            "titles": [p["title"] for p in pending],
            "tns": [p["tn"] for p in pending],
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Affiche sans écrire.")
    parser.add_argument(
        "--limit", type=int, default=0, help="Limiter le nombre de SP candidates (0 = toutes)."
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        sql = _CANDIDATE_SQL + (f" LIMIT {int(args.limit)}" if args.limit else "")
        rows = conn.execute(text(sql)).all()
        log.info("%d source_publications candidates (titre à entité HTML échappée).", len(rows))

        changed = 0
        pending: list[dict[str, object]] = []
        for r in rows:
            new_title = clean_publication_title(r.title)
            new_tn = normalized_title(r.title)
            if new_title == r.title and new_tn == r.title_normalized:
                continue
            changed += 1
            if changed <= 5:
                log.info(
                    "  ex. id=%s\n      avant : %s\n      après : %s",
                    r.id,
                    (r.title or "")[:90],
                    (new_title or "")[:90],
                )
            pending.append({"id": r.id, "title": new_title, "tn": new_tn})
            if not args.dry_run and len(pending) >= _BATCH:
                _flush(conn, pending)
                conn.commit()
                pending = []

        if not args.dry_run and pending:
            _flush(conn, pending)
            conn.commit()

        log.info(
            "Bilan : %d SP modifiées sur %d candidates%s.",
            changed,
            len(rows),
            " (dry-run, aucune écriture)" if args.dry_run else " — keys_dirty posé",
        )
        if changed and not args.dry_run:
            log.info(
                "→ Lancer `python run_pipeline.py --only publications` (puis aval) "
                "pour re-dédupliquer et ré-agréger les titres."
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
