# STATUS: oneshot (2026-09-17)
"""Retire du stock les DOI et préfixes DOI qui n'en ont pas la forme.

Un DOI a la forme `10.<chiffres>/<suffixe>` (`DOI`), un préfixe DOI la forme `10.<chiffres>` (`DoiPrefix`). Le stock garde des valeurs d'avant ces règles :

- des lignes de `doi_prefixes` : « doi:10.5194 », « https: », « 2119303118 » ; elles sont supprimées ;
- des DOI de documents (« 10.101621gloenvcha.2020.102168 », WoS) : ils sont vidés, et l'enregistrement est marqué `keys_dirty` pour que la phase `publications` le réconcilie ;
- des `related_dois` (OpenAlex : identifiants numériques, URL d'articles, DOI sous URL `www.doi.org`) : les DOI sont normalisés, le reste est retiré de la liste ;
- des DOI de publications : ils sont vidés.

Usage :
    python -m interfaces.cli.oneshot.backfill_drop_malformed_dois             # applique
    python -m interfaces.cli.oneshot.backfill_drop_malformed_dois --dry-run   # rapport seul
"""

from __future__ import annotations

import argparse
import json
import os

from sqlalchemy import Connection, text

from domain.publications.identifiers import DOI, DoiPrefix
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("backfill_drop_malformed_dois", os.path.dirname(__file__))

# Préfiltre SQL large : la décision revient aux objets valeur.
_NOT_A_DOI = r"'^10\.[0-9]+/'"


def _drop_prefixes(conn: Connection) -> int:
    rows = conn.execute(text("SELECT prefix, publisher_id FROM doi_prefixes")).all()
    bad = [r for r in rows if str(DoiPrefix.try_parse(r.prefix)) != r.prefix]
    for row in bad:
        log.info("Préfixe DOI supprimé : %r (éditeur %s)", row.prefix, row.publisher_id)
    conn.execute(
        text("DELETE FROM doi_prefixes WHERE prefix = ANY(:p)"), {"p": [r.prefix for r in bad]}
    )
    return len(bad)


def _clear_record_dois(conn: Connection) -> int:
    rows = conn.execute(
        text(f"SELECT id, source, doi FROM source_publications WHERE doi !~ {_NOT_A_DOI}")
    ).all()
    bad = [r for r in rows if DOI.try_parse(r.doi) is None]
    for row in bad:
        log.info("DOI vidé : enregistrement %d (%s) %r", row.id, row.source, row.doi)
    conn.execute(
        text("UPDATE source_publications SET doi = NULL, keys_dirty = TRUE WHERE id = ANY(:ids)"),
        {"ids": [r.id for r in bad]},
    )
    return len(bad)


def _filter_related_dois(conn: Connection) -> int:
    rows = conn.execute(
        text(f"""
            SELECT sp.id, sp.external_ids->'related_dois' AS related
            FROM source_publications sp
            WHERE jsonb_typeof(sp.external_ids->'related_dois') = 'array'
              AND EXISTS (
                  SELECT 1 FROM jsonb_array_elements_text(sp.external_ids->'related_dois') d(v)
                  WHERE d.v !~ {_NOT_A_DOI}
              )
        """)
    ).all()
    dropped = 0
    for row in rows:
        parsed = [DOI.try_parse(d) for d in row.related]
        kept = list(dict.fromkeys(str(d) for d in parsed if d is not None))
        removed = [raw for raw, d in zip(row.related, parsed, strict=True) if d is None]
        if kept == row.related:
            continue
        dropped += len(removed)
        log.info(
            "related_dois de l'enregistrement %d : %r retirés, %r gardés", row.id, removed, kept
        )
        conn.execute(
            text("""
                UPDATE source_publications
                SET external_ids = CASE WHEN CAST(:kept AS jsonb) = '[]'::jsonb
                                        THEN external_ids - 'related_dois'
                                        ELSE jsonb_set(external_ids, '{related_dois}', CAST(:kept AS jsonb))
                                   END
                WHERE id = :id
            """),
            {"kept": json.dumps(kept), "id": row.id},
        )
    return dropped


def _clear_publication_dois(conn: Connection) -> int:
    rows = conn.execute(text(f"SELECT id, doi FROM publications WHERE doi !~ {_NOT_A_DOI}")).all()
    bad = [r for r in rows if DOI.try_parse(r.doi) is None]
    for row in bad:
        log.info("DOI vidé : publication %d %r", row.id, row.doi)
    conn.execute(
        text("UPDATE publications SET doi = NULL WHERE id = ANY(:ids)"),
        {"ids": [r.id for r in bad]},
    )
    return len(bad)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Rapport seul : n'écrit rien (défaut : applique)."
    )
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        prefixes = _drop_prefixes(conn)
        records = _clear_record_dois(conn)
        related = _filter_related_dois(conn)
        publications = _clear_publication_dois(conn)
        log.info(
            "%d préfixes supprimés, %d DOI d'enregistrements vidés, %d related_dois retirés, %d DOI de publications vidés",
            prefixes,
            records,
            related,
            publications,
        )
        if args.dry_run:
            conn.rollback()
            log.info("DRY-RUN terminé — aucune écriture")
            return 0
        conn.commit()
        log.info("✓ backfill appliqué")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
