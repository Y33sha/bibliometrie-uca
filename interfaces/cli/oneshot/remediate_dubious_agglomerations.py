# STATUS: oneshot (2026-06-22)
"""Remédiation des personnes agglomérées par un identifiant empoisonné (corruption source).

Le `normalize` suffixe `_dubious` aux identifiants partagés de façon suspecte, ce qui les rend
invisibles au matching *futur* — mais les `person_id` déjà posés (les personnes « Frankenstein »
comme 12913, qui a agrégé des centaines de signatures distinctes) restent en place. La phase
persons étant **incrémentale** (`WHERE person_id IS NULL`), elle ne les ré-évalue pas d'elle-même.

Séquence :

1. **Null `person_id`** des signatures portant un identifiant `_dubious` — fenêtré par
   `source_publication_id` (Bitmap Index Scan sur l'unique `(source_publication_id,
   author_position)`), pour ne pas seq-scanner les ~19M lignes en une fois. Les rend à nouveau
   éligibles au matching.
2. **Purge des `person_identifiers` `status='pending'` orphelins** : plus aucune
   `source_authorship` de la personne ne porte la valeur (l'ORCID empoisonné n'existe plus
   qu'en `orcid_dubious`). Les `confirmed`/`rejected` (verdicts humains) sont préservés.
3. **Recalcul `person_name_forms`** : les formes étant dérivées de `persons` +
   `source_authorships`, le diff supprime les formes héritées des signatures nullées (les
   noms d'autres auteurs disparaissent ; le nom propre de la personne survit via la ligne
   `persons`).

Ensuite : **relancer le pipeline** (phase persons). `create_persons` re-matchera les signatures
nullées sur des formes désormais propres et sans l'ORCID empoisonné → ré-attribution correcte.

Usage :
    python -m interfaces.cli.oneshot.remediate_dubious_agglomerations [--dry-run] [--window 2000]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, text

from application.pipeline.persons.populate_person_name_forms import populate
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.pipeline.persons.name_forms import PgPersonNameFormsQueries

log = setup_logger("remediate_dubious_agglomerations", os.path.dirname(__file__))

_MAX_PUB_SQL = text("SELECT max(source_publication_id) FROM source_authorships")

# Signatures liées (person_id non nul) à identifiants (objet JSONB) de la fenêtre courante.
_LINKED_SQL = text("""
    SELECT sa.id, aik.person_identifiers
    FROM source_authorships sa
    JOIN author_identifying_keys aik ON aik.id = sa.identity_id
    WHERE sa.source_publication_id > :last
      AND sa.source_publication_id <= :hi
      AND sa.person_id IS NOT NULL
      AND jsonb_typeof(aik.person_identifiers) = 'object'
""")

_NULL_SQL = text("UPDATE source_authorships SET person_id = NULL WHERE id = ANY(:ids)")

# Identifiants `pending` qu'aucune signature de la personne ne porte plus (clé nue). Les
# `confirmed`/`rejected` sont des verdicts humains, jamais touchés.
_PURGE_SQL = text("""
    DELETE FROM person_identifiers pi
    WHERE pi.status = 'pending'
      AND NOT EXISTS (
          SELECT 1 FROM source_authorships sa
          JOIN author_identifying_keys aik ON aik.id = sa.identity_id
          WHERE sa.person_id = pi.person_id
            AND aik.person_identifiers ->> (pi.id_type)::text = pi.id_value
      )
""")


def _null_dubious_links(conn: Connection, window: int, dry_run: bool) -> int:
    max_pub = conn.execute(_MAX_PUB_SQL).scalar() or 0
    total = 0
    last = 0
    while last < max_pub:
        hi = last + window
        rows = conn.execute(_LINKED_SQL, {"last": last, "hi": hi}).all()
        ids = [r.id for r in rows if any(k.endswith("_dubious") for k in r.person_identifiers)]
        if ids and not dry_run:
            conn.execute(_NULL_SQL, {"ids": ids})
            conn.commit()
        total += len(ids)
        last = hi
        if (last // window) % 50 == 0:
            log.info("… curseur=%d/%d, %d person_id nullés", last, max_pub, total)
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Compte sans écrire ni recalculer.")
    parser.add_argument(
        "--window", type=int, default=2000, help="Largeur de la fenêtre d'ids de publication."
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        n_nulled = _null_dubious_links(conn, args.window, args.dry_run)
        log.info("1/3 — %d person_id %s", n_nulled, "à nuller" if args.dry_run else "nullés")

        if args.dry_run:
            n_purge = conn.execute(
                text(
                    "SELECT count(*) FROM person_identifiers pi WHERE pi.status='pending' "
                    "AND NOT EXISTS (SELECT 1 FROM source_authorships sa "
                    "JOIN author_identifying_keys aik ON aik.id = sa.identity_id "
                    "WHERE sa.person_id=pi.person_id "
                    "AND aik.person_identifiers->>(pi.id_type)::text = pi.id_value)"
                )
            ).scalar()
            log.info("2/3 — %d person_identifiers pending orphelins (à supprimer)", n_purge)
            log.info("3/3 — recalcul person_name_forms (sauté en dry-run)")
            log.info("DRY-RUN : aucune écriture")
            return 0

        n_purged = conn.execute(_PURGE_SQL).rowcount
        conn.commit()
        log.info("2/3 — %d person_identifiers pending orphelins supprimés", n_purged)

        log.info("3/3 — recalcul person_name_forms…")
        populate(conn, PgPersonNameFormsQueries(), log)
        conn.commit()

    log.info("Terminé. Relancer le pipeline (phase persons) pour la ré-attribution.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
