# STATUS: oneshot (2026-05-28)
r"""
Audit (pure lecture) : sur quelles publications les patterns de titre
de recension d'ouvrage (book review) frappent-ils, et sous quel
`doc_type` sont-elles classées aujourd'hui ?

Patterns testés :
- ISBN dans le titre : mention textuelle "ISBN" (regex case-insensitive)
  ou numéro ISBN-13 commençant par 978/979.
- Titre terminé par "année, N pages" : `(19|20)\d{2}\s*,?\s*\d+\s*p(\.|ages?)?` en fin de titre.

Sert à dimensionner la règle `TITLE_*_TO_BOOK_REVIEW` du chantier
[METIER_doc-types](../../docs/chantiers/METIER_doc-types.md) :
combien de cas sont attrapés, quelle proportion est déjà classée
`book_review` ou `review` (no-op vs reclassement), et quels types
arbitraires (article, other, …) doivent passer en `book_review`.

Ne fait AUCUNE écriture en base.

Usage :
    python -m interfaces.cli.oneshot.audit_book_review_title_patterns
"""

from __future__ import annotations

import os

from sqlalchemy import Connection, text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("audit_book_review_title_patterns", os.path.dirname(__file__))

_ISBN_PATTERN = r"(\misbn\M|\m97[89][- 0-9]{10,17}\M)"

_YEAR_PAGES_END_PATTERN = r"(19|20)\d{2}[\s,.]+\d{1,4}\s*(p|pp|pages?)\.?\s*$"


def main() -> None:
    engine = get_sync_engine()
    with engine.connect() as conn:
        log.info("=" * 60)
        log.info("Pattern 1 — ISBN dans le titre")
        log.info("=" * 60)
        run_pattern(conn, _ISBN_PATTERN, "ISBN")

        log.info("")
        log.info("=" * 60)
        log.info("Pattern 2 — Titre terminé par 'année, N pages'")
        log.info("=" * 60)
        run_pattern(conn, _YEAR_PAGES_END_PATTERN, "ANNEE_PAGES")


def run_pattern(conn: Connection, pattern: str, label: str) -> None:
    res = conn.execute(
        text(
            "SELECT doc_type::text, count(*) AS n "
            "FROM publications "
            "WHERE title ~* :pat "
            "GROUP BY doc_type "
            "ORDER BY n DESC"
        ),
        {"pat": pattern},
    ).fetchall()
    if not res:
        log.info("Aucun match.")
        return
    total = sum(r.n for r in res)
    log.info(f"Total : {total} publications match le pattern.")
    log.info("")
    log.info(f"{'doc_type':<20} {'n':>6} {'%':>6}")
    log.info("-" * 36)
    for row in res:
        pct = 100.0 * row.n / total
        log.info(f"{row.doc_type:<20} {row.n:>6} {pct:>5.1f}%")

    examples = conn.execute(
        text(
            "SELECT id, doc_type::text AS doc_type, title "
            "FROM publications "
            "WHERE title ~* :pat "
            "AND doc_type::text NOT IN ('book_review') "
            "ORDER BY random() LIMIT 8"
        ),
        {"pat": pattern},
    ).fetchall()
    if examples:
        log.info("")
        log.info("Exemples (échantillon, hors book_review déjà classé) :")
        for ex in examples:
            log.info(f"  [#{ex.id} {ex.doc_type}] {ex.title[:140]}")


if __name__ == "__main__":
    main()
