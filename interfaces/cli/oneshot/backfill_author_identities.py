# STATUS: oneshot (2026-07-02)
"""Backfill des identités d'auteur : peuple `author_identifying_keys` et pose `source_authorships.identity_id`.

Étape de données de la séparation de `source_authorships` (identité d'auteur ⊥ liaison), à lancer après la migration qui crée la table `author_identifying_keys` et la colonne nullable `identity_id`. Trois temps :

1. **Peuplement des identités** — `INSERT … SELECT DISTINCT (author_name_normalized, person_identifiers) FROM source_authorships ON CONFLICT DO NOTHING`. Le `DISTINCT` collapse les ~19 M signatures sur les ~645 k identités distinctes ; idempotent, sauté si la table est déjà peuplée.

2. **Chargement de la map d'identités en mémoire** — `{(nom, identifiants canoniques) : identity_id}`, ~645 k entrées. La clé sérialise le jsonb en JSON trié pour un rapprochement déterministe et NULL-safe côté Python, sans join SQL sur une colonne jsonb (non indexable en égalité NULL-safe).

3. **Rattachement par tranches d'id** — parcours de `source_authorships` par fenêtres de `id` (clé primaire dense) ; pour chaque signature, `identity_id` est résolu par lookup dans la map, puis posé en masse par un `UPDATE … FROM unnest(ids, identity_ids)` (join par clé primaire, rapide). Commit et log à chaque fenêtre : progression visible, transactions bornées, reprise possible (le filtre `identity_id IS NULL` ne retraite que les signatures encore sans identité).

Ne touche ni `person_id`, ni les deux colonnes d'origine, qui restent en place jusqu'à la phase de contraction.

Usage :
    python -m interfaces.cli.oneshot.backfill_author_identities [--dry-run] [--batch 50000]
"""

from __future__ import annotations

import argparse
import json
import os

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("backfill_author_identities", os.path.dirname(__file__))

_POPULATE_SQL = text("""
    INSERT INTO author_identifying_keys (author_name_normalized, person_identifiers)
    SELECT DISTINCT author_name_normalized, person_identifiers
    FROM source_authorships
    ON CONFLICT (author_name_normalized, person_identifiers) DO NOTHING
""")

_REMAINING_SQL = text("SELECT count(*) FROM source_authorships WHERE identity_id IS NULL")
_COUNT_IDENTITIES_SQL = text("SELECT count(*) FROM author_identifying_keys")
_LOAD_IDENTITIES_SQL = text(
    "SELECT id, author_name_normalized, person_identifiers FROM author_identifying_keys"
)
_MAX_ID_SQL = text("SELECT max(id) FROM source_authorships")
_SELECT_WINDOW_SQL = text("""
    SELECT id, author_name_normalized, person_identifiers
    FROM source_authorships
    WHERE id > :lo AND id <= :hi AND identity_id IS NULL
""")
_UPDATE_WINDOW_SQL = text("""
    UPDATE source_authorships sa
    SET identity_id = v.iid
    FROM unnest(CAST(:ids AS int[]), CAST(:iids AS int[])) AS v(id, iid)
    WHERE sa.id = v.id
""")


def _key(name: str | None, ids: object) -> tuple[str | None, str | None]:
    """Clé d'identité canonique, identique des deux côtés (map et signature).

    Le jsonb est sérialisé en JSON trié ; `NULL` reste `None`. `person_identifiers`
    revient parsé (dict) via le loader jsonb, mais on tolère une str par prudence."""
    if isinstance(ids, str):
        ids = json.loads(ids)
    return (name, None if ids is None else json.dumps(ids, sort_keys=True, separators=(",", ":")))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Compte sans écrire.")
    parser.add_argument("--batch", type=int, default=50000, help="Largeur de la fenêtre d'ids.")
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        remaining = conn.execute(_REMAINING_SQL).scalar() or 0
        log.info("Signatures sans identité : %d", remaining)
        if args.dry_run:
            log.info("Dry-run : %d signatures seraient rattachées.", remaining)
            return 0

        # 1. Peuplement (idempotent), sauté si déjà fait.
        if (conn.execute(_COUNT_IDENTITIES_SQL).scalar() or 0) == 0:
            log.info("Peuplement de author_identifying_keys (SELECT DISTINCT)…")
            conn.execute(_POPULATE_SQL)
            conn.commit()

        # 2. Map d'identités en mémoire.
        log.info("Chargement de la map d'identités…")
        identity_of: dict[tuple[str | None, str | None], int] = {}
        for r in conn.execute(_LOAD_IDENTITIES_SQL):
            identity_of[_key(r.author_name_normalized, r.person_identifiers)] = r.id
        log.info("  %d identités en mémoire.", len(identity_of))

        # 3. Rattachement par tranches d'id.
        max_id = conn.execute(_MAX_ID_SQL).scalar() or 0
        linked = 0
        unmatched = 0
        lo = 0
        while lo < max_id:
            hi = lo + args.batch
            rows = conn.execute(_SELECT_WINDOW_SQL, {"lo": lo, "hi": hi}).all()
            ids: list[int] = []
            iids: list[int] = []
            for r in rows:
                iid = identity_of.get(_key(r.author_name_normalized, r.person_identifiers))
                if iid is None:
                    unmatched += 1
                    continue
                ids.append(r.id)
                iids.append(iid)
            if ids:
                conn.execute(_UPDATE_WINDOW_SQL, {"ids": ids, "iids": iids})
                conn.commit()
                linked += len(ids)
            lo = hi
            log.info("… id≤%d/%d, %d rattachées", hi, max_id, linked)

    log.info("Terminé : %d signatures rattachées, %d sans identité trouvée.", linked, unmatched)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
