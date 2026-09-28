# STATUS: oneshot (2026-09-28)
"""Corrige en place le stock où un nom d'auteur porte un chiffre.

`clean_raw_author_name` retire à l'entrée du pipeline les chiffres d'un nom d'auteur (année de naissance « Candoni, Jean-François 1964- », identifiant de source « Emmanuel Moreau (1278759) », renvoi d'affiliation « Ibrahim1 ») et la ponctuation qu'ils laissent isolée. Ce script corrige les trois traces que ces chiffres laissent dans le stock déjà normalisé, sans renormaliser les notices.

1. `source_authorships` : `raw_author_name` re-nettoyé et `identity_id` repointé sur l'identité propre, résolue via l'upsert du writer (`_UPSERT_IDENTITY_SQL` + `key_hash_sql`). Les identités devenues orphelines sont purgées. Le nom normalisé de l'identité sert de clé de rapprochement cross-source, d'où l'intérêt de le nettoyer.
2. `persons` : `last_name`/`first_name` et leurs formes normalisées re-nettoyés. Le pipeline fige le nom d'une personne à sa création, ce que ce backfill complète.
3. `person_name_forms` : régénérées par `populate` (diff-sync global, idempotent) une fois `persons` et les identités corrigées.

Les liens `person_id` restent en l'état ; le rapprochement des signatures propres avec leur personne suit au prochain run de la phase `persons`.

Usage :
    python -m interfaces.cli.oneshot.backfill_clean_author_names            # exécution
    python -m interfaces.cli.oneshot.backfill_clean_author_names --dry-run  # rapport seul
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, bindparam, text

from application.pipeline.persons.populate_person_name_forms import populate
from domain.normalize import clean_raw_author_name, normalize_name, normalize_name_form
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.jsonb import Jsonb
from infrastructure.observability.log import setup_logger
from infrastructure.pipeline.normalize.authorships import (
    _UPSERT_IDENTITY_SQL,
    delete_orphan_identities,
    key_hash_sql,
)
from infrastructure.pipeline.persons.name_forms import PgPersonNameFormsQueries

log = setup_logger("backfill_clean_author_names", os.path.dirname(__file__))

# Toute signature dont le nom brut porte un chiffre.
_POLLUTED_PREDICATE = r"raw_author_name ~ '\d'"

_REPOINT_SIGNATURE_SQL = text(
    """
    UPDATE source_authorships
    SET raw_author_name = :raw,
        identity_id = (SELECT id FROM author_identifying_keys
                       WHERE key_hash = """
    + key_hash_sql(":author_name_normalized", ":person_identifiers")
    + """)
    WHERE id = :sa_id
"""
).bindparams(bindparam("person_identifiers", type_=Jsonb))


def _repoint_polluted_identities(conn: Connection, apply: bool) -> None:
    """Re-nettoie `raw_author_name` et repointe `identity_id` sur l'identité propre."""
    rows = conn.execute(
        text(
            "SELECT sa.id AS sa_id, sa.raw_author_name AS raw, aik.person_identifiers AS pid "
            "FROM source_authorships sa "
            "JOIN author_identifying_keys aik ON aik.id = sa.identity_id "
            f"WHERE sa.{_POLLUTED_PREDICATE}"
        )
    ).all()

    n = 0
    for r in rows:
        clean_raw = clean_raw_author_name(r.raw)
        if clean_raw == r.raw:
            continue  # nom fait seulement de chiffres (ORCID recopié), laissé tel quel
        n += 1
        if not apply:
            continue
        clean_norm = normalize_name_form(clean_raw)
        # 1. garantir l'existence de l'identité propre (nom propre, mêmes identifiants)
        conn.execute(
            _UPSERT_IDENTITY_SQL,
            {"author_name_normalized": clean_norm, "person_identifiers": r.pid},
        )
        # 2. re-nettoyer le nom brut et repointer la signature sur l'identité propre
        conn.execute(
            _REPOINT_SIGNATURE_SQL,
            {
                "sa_id": r.sa_id,
                "raw": clean_raw,
                "author_name_normalized": clean_norm,
                "person_identifiers": r.pid,
            },
        )
    log.info("source_authorships pollués repointés : %d / %d examinés", n, len(rows))


def _fix_person_names(conn: Connection, apply: bool) -> None:
    """Re-nettoie le nom et le prénom des personnes qui portent un chiffre."""
    rows = conn.execute(
        text(
            r"SELECT id, last_name, first_name FROM persons WHERE last_name ~ '\d' OR first_name ~ '\d'"
        )
    ).all()

    upd: list[dict[str, int | str | None]] = []
    for r in rows:
        last = clean_raw_author_name(r.last_name or "")
        first = clean_raw_author_name(r.first_name or "")
        if (last, first) == (r.last_name or "", r.first_name or ""):
            continue
        log.info("person %d : %r %r → %r %r", r.id, r.first_name, r.last_name, first, last)
        upd.append(
            {
                "id": r.id,
                "last": last,
                "first": first,
                "last_norm": normalize_name(last),
                "first_norm": normalize_name(first),
            }
        )
    log.info("persons à renommer : %d / %d", len(upd), len(rows))
    if apply and upd:
        conn.execute(
            text(
                "UPDATE persons SET last_name = :last, first_name = :first, "
                "last_name_normalized = :last_norm, first_name_normalized = :first_norm "
                "WHERE id = :id"
            ),
            upd,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Rapport seul : n'écrit rien (défaut : applique)."
    )
    args = parser.parse_args()
    apply = not args.dry_run

    if not apply:
        log.info("DRY-RUN (rapport seul) — retirer --dry-run pour écrire")

    engine = get_sync_engine()
    with engine.connect() as conn:
        _repoint_polluted_identities(conn, apply)
        _fix_person_names(conn, apply)
        if apply:
            purged = delete_orphan_identities(conn)
            log.info("identités orphelines purgées : %d", purged)
            populate(conn, PgPersonNameFormsQueries(), log)
            conn.commit()
            log.info("✓ backfill appliqué")
        else:
            log.info("DRY-RUN terminé — aucune écriture (formes de nom non régénérées)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
