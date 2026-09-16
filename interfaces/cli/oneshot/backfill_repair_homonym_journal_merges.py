# STATUS: oneshot (2026-09-16)
"""Répare les revues touchées par la fusion d'un homonyme.

La première version de la fusion par titre a réuni des revues homonymes. L'audit des fusions en relève trois conséquences, corrigées ici sur une liste explicite :

1. une forme de nom d'un autre éditeur rattache à la revue les enregistrements de l'homonyme : la forme est supprimée ;
2. un livre porte les ISSN d'une revue Elsevier de même titre : les ISSN sont retirés ;
3. des enregistrements de l'homonyme sont rattachés à la revue : ils passent à une revue propre, créée sous l'éditeur de l'homonyme, et leurs publications sont recalculées.

Chaque action vérifie l'état attendu ; un écart est signalé et l'action sautée.

Usage :
    python -m interfaces.cli.oneshot.backfill_repair_homonym_journal_merges             # applique
    python -m interfaces.cli.oneshot.backfill_repair_homonym_journal_merges --dry-run   # rapport seul
"""

from __future__ import annotations

import argparse
import os
from typing import NamedTuple

from sqlalchemy import Connection, text

from application.services.publications.core import refresh_from_sources
from domain.normalize import normalize_text
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.pipeline.journals import PgJournalGatewayQueries
from infrastructure.repositories.publication_repository import PgPublicationRepository

log = setup_logger("backfill_repair_homonym_journal_merges", os.path.dirname(__file__))


class Form(NamedTuple):
    journal_id: int
    form_id: int
    publisher: str


class Move(NamedTuple):
    from_journal_id: int
    title: str
    publisher_id: int
    publisher: str
    publication_ids: tuple[int, ...]


# (revue, forme de nom, éditeur de l'homonyme)
_FORMS = (
    Form(7665, 574500, "Dunod"),
    Form(12365, 376295, "IntechOpen"),
    Form(12365, 513079, "InTech"),
    Form(20295, 198376, "Herald Scholarly Open Access"),
    Form(102675, 198353, "FapUNIFESP (SciELO)"),
    Form(14084, 512527, "AMA Service GmbH"),
    Form(101374, 561423, "Elsevier BV"),
    Form(102133, 58416, "Elsevier BV"),
)

# Livres qui portent les ISSN d'une revue Elsevier de même titre : (revue, ISSN attendus)
_BOOKS_WITH_JOURNAL_ISSNS = {
    101374: ("0143-8174", "1878-2809"),
    102133: ("0933-3657", "1873-2860"),
}

_MOVES = (
    Move(12365, "Livestock Science", 2215, "IntechOpen", (173211,)),
    Move(14084, "Lectures", 80499, "AMA Service GmbH", (15984,)),
)


def _delete_forms(conn: Connection) -> None:
    for form in _FORMS:
        row = conn.execute(
            text("""
                DELETE FROM journal_name_forms f
                USING journals j
                WHERE f.id = :form AND f.journal_id = :journal AND j.id = f.journal_id
                RETURNING j.title, f.form_normalized
            """),
            {"form": form.form_id, "journal": form.journal_id},
        ).one_or_none()
        if row is None:
            log.warning(
                "Forme %d de la revue %d introuvable : sautée", form.form_id, form.journal_id
            )
            continue
        log.info(
            "Revue %d « %s » : forme %r de l'éditeur %s supprimée",
            form.journal_id,
            row.title,
            row.form_normalized,
            form.publisher,
        )


def _remove_journal_issns(conn: Connection) -> None:
    for journal_id, (issn, eissn) in _BOOKS_WITH_JOURNAL_ISSNS.items():
        row = conn.execute(
            text("""
                UPDATE journals SET issn = NULL, eissn = NULL, issnl = NULL
                WHERE id = :id AND issn = :issn AND eissn = :eissn
                RETURNING title
            """),
            {"id": journal_id, "issn": issn, "eissn": eissn},
        ).one_or_none()
        if row is None:
            log.warning("Revue %d : ISSN %s/%s absents, sautée", journal_id, issn, eissn)
            continue
        log.info("Revue %d « %s » : ISSN %s/%s retirés", journal_id, row.title, issn, eissn)


def _move_records(conn: Connection) -> None:
    journals = PgJournalGatewayQueries(conn)
    publications = PgPublicationRepository(conn)
    for move in _MOVES:
        new_id = journals.create_journal(
            title=move.title,
            issn=None,
            eissn=None,
            issnl=None,
            publisher_id=move.publisher_id,
            openalex_id=None,
            oa_model=None,
        )
        journals.add_journal_name_form(new_id, normalize_text(move.title), move.publisher_id)
        moved = conn.execute(
            text("""
                UPDATE source_publications SET journal_id = :new
                WHERE journal_id = :old AND publication_id = ANY(:pubs)
            """),
            {"new": new_id, "old": move.from_journal_id, "pubs": list(move.publication_ids)},
        ).rowcount
        for publication_id in move.publication_ids:
            refresh_from_sources(publication_id, repo=publications)
        log.info(
            "Revue %d « %s » : %d enregistrements de %s passent à la revue créée %d",
            move.from_journal_id,
            move.title,
            moved,
            move.publisher,
            new_id,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Rapport seul : n'écrit rien (défaut : applique)."
    )
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        _delete_forms(conn)
        _remove_journal_issns(conn)
        _move_records(conn)
        if args.dry_run:
            conn.rollback()
            log.info("DRY-RUN terminé — aucune écriture")
            return 0
        conn.commit()
        log.info("✓ backfill appliqué")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
