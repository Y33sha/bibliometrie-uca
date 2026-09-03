# STATUS: oneshot (2026-08-24)
"""Corrige en place le stock où un identifiant numérique parenthésé subsiste dans un nom d'auteur.

Certaines signatures OpenAlex portent un identifiant de source recopié dans le nom (« Emmanuel Moreau (1278759) »). `clean_raw_author_name` neutralise ce parasite à l'entrée du pipeline ; ce script corrige les trois traces qu'il laisse dans le stock déjà normalisé.

1. `source_authorships` : `raw_author_name` re-nettoyé et `identity_id` repointé sur l'identité propre, résolue via l'upsert du writer (`_UPSERT_IDENTITY_SQL` + `key_hash_sql`). Les identités devenues orphelines sont purgées. Le nom normalisé de l'identité sert de clé de rapprochement cross-source, d'où l'intérêt de le nettoyer.
2. `persons` : `last_name`/`first_name` et leurs formes normalisées recalculés pour les personnes dont le nom de famille est l'identifiant parenthésé. Le pipeline fige le nom d'une personne à sa création, ce que ce backfill complète.
3. `person_name_forms` : régénérées par `populate` (diff-sync global, idempotent) une fois `persons` et les identités corrigées.

Les liens `person_id` restent en l'état ; le rapprochement des signatures propres avec leur personne suit au prochain run de la phase `persons`.

Usage :
    python -m interfaces.cli.oneshot.backfill_strip_author_name_ids            # exécution
    python -m interfaces.cli.oneshot.backfill_strip_author_name_ids --dry-run  # rapport seul
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.pipeline.persons.populate_person_name_forms import populate
from domain.normalize import clean_raw_author_name, normalize_name, normalize_name_form
from domain.persons.name_matching import parse_raw_author_name
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.pipeline.normalize.authorships import (
    _UPSERT_IDENTITY_SQL,
    delete_orphan_identities,
    key_hash_sql,
)
from infrastructure.pipeline.persons.name_forms import PgPersonNameFormsQueries

log = setup_logger("backfill_strip_author_name_ids", os.path.dirname(__file__))

# Toute signature dont le nom brut porte un identifiant numérique parenthésé.
_POLLUTED_PREDICATE = r"raw_author_name ~ '\(\d+\)'"

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
).bindparams(bindparam("person_identifiers", type_=JSONB))


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
            continue  # parenthèse non numérique captée par le pré-filtre : rien à corriger
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
    """Recalcule le nom des personnes dont le nom de famille est un identifiant parenthésé."""
    rows = conn.execute(
        text(r"SELECT id, last_name, first_name FROM persons WHERE last_name ~ '^\(\d+\)$'")
    ).all()

    upd: list[dict[str, int | str | None]] = []
    for r in rows:
        # Reconstitue le nom brut d'origine (prénom + identifiant capté comme nom) puis re-parse
        # avec le parser, qui écarte l'identifiant parenthésé.
        reconstructed = f"{r.first_name or ''} {r.last_name}".strip()
        last, first = parse_raw_author_name(reconstructed)
        if not last:
            log.warning("person %d : nom vide après nettoyage (%r), ignorée", r.id, reconstructed)
            continue
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
