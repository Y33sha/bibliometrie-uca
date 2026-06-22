# STATUS: oneshot (2026-06-22)
"""Backfill : marque `_dubious` tout identifiant partagé entre ≥2 signatures d'un même record.

Le `normalize` (tous sources) suffixe désormais `_dubious` à tous les identifiants d'une
signature dont une valeur (ORCID, hal_person_id, idref…) est portée par ≥2 auteurs du même
enregistrement source — corruption : un identifiant ne peut pas désigner deux signatures
dans un même document. Cas typique : le dépôt crossref d'un méga-papier de collaboration
recopie l'ORCID du premier auteur sur tous les co-auteurs, et OpenAlex en hérite ; le
matching par identifiant agglomère alors des centaines de personnes en une seule.

Les `source_authorships` déjà en base portent encore les clés nues ; ce one-shot applique le
même renommage au stock, **sans tout re-normaliser** et **sans seq scan global** : la
détection JSONB sur les ~19M lignes, en une requête, matérialise un intermédiaire ingérable.

La détection exhaustive impose **un passage complet en lecture** (aucun index ne porte les
valeurs d'identifiant) — incompressible. Mais on le **découpe en fenêtres d'ids**
`source_publication_id` (denses, 1..~1M) via l'unique `(source_publication_id,
author_position)` : chaque batch lit un intervalle borné (`WHERE source_publication_id BETWEEN
…`), regroupe les signatures par publication et applique le **même** helper
`mark_shared_identifiers_dubious` que le normalize (aucune ré-implémentation de la détection),
puis `UPDATE` les signatures dont une clé change. Commit par batch.

- **Progressif et résumable** : commit par batch + curseur (`--resume-from <id>`) ; le helper
  étant idempotent (clés déjà `_dubious` ignorées), ré-exécuter depuis 0 est un no-op sur les
  publications déjà traitées.
- **Mémoire bornée** : un batch en RAM à la fois ; un méga-papier seul gonfle son batch mais
  reste borné à `--batch` ids de publication. Pas de matérialisation JSONB globale (la cause
  du seq scan ingérable d'une requête unique).

Généralise `backfill_dubious_hal_identifiers` (limité à HAL / `hal_person_id`).
Ne touche PAS `source_authorships.person_id` ni la table `person_identifiers` : la
remédiation des personnes déjà agglomérées est une étape séparée.

Usage :
    python -m interfaces.cli.oneshot.backfill_dubious_shared_identifiers [--dry-run]
                                                                        [--window 2000] [--resume-from 0]
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict

from sqlalchemy import text

from domain.persons.identifiers import mark_shared_identifiers_dubious
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("backfill_dubious_shared_identifiers", os.path.dirname(__file__))

_MAX_PUB_SQL = text("SELECT max(source_publication_id) FROM source_authorships")

# Signatures à identifiants (objet JSONB) de la fenêtre courante. Pas d'ORDER BY : le
# regroupement par publication se fait en Python (defaultdict). Intervalle sur l'unique
# `(source_publication_id, author_position)`.
_AUTHORSHIPS_SQL = text("""
    SELECT id, source_publication_id, person_identifiers
    FROM source_authorships
    WHERE source_publication_id > :last
      AND source_publication_id <= :hi
      AND jsonb_typeof(person_identifiers) = 'object'
""")

_UPDATE_SQL = text(
    "UPDATE source_authorships SET person_identifiers = CAST(:ids AS jsonb) WHERE id = :id"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Compte sans écrire.")
    parser.add_argument(
        "--window", type=int, default=2000, help="Largeur de la fenêtre d'ids de publication."
    )
    parser.add_argument(
        "--resume-from", type=int, default=0, help="Reprendre après ce source_publication_id."
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    total_marked = 0
    with engine.connect() as conn:
        max_pub = conn.execute(_MAX_PUB_SQL).scalar() or 0
        last = args.resume_from
        while last < max_pub:
            hi = last + args.window
            rows = conn.execute(_AUTHORSHIPS_SQL, {"last": last, "hi": hi}).all()

            by_pub: dict[int, list[tuple[int, dict]]] = defaultdict(list)
            for r in rows:
                by_pub[r.source_publication_id].append((r.id, r.person_identifiers))

            updates = []
            for items in by_pub.values():
                tainted = mark_shared_identifiers_dubious([ids for _, ids in items])
                for (sa_id, before), after in zip(items, tainted, strict=True):
                    if after is not before:  # le helper renvoie le même objet si inchangé
                        updates.append({"id": sa_id, "ids": json.dumps(after)})

            if updates and not args.dry_run:
                conn.execute(_UPDATE_SQL, updates)
                conn.commit()

            total_marked += len(updates)
            last = hi
            if (last // args.window) % 50 == 0:
                log.info("… curseur=%d/%d, %d signatures marquées", last, max_pub, total_marked)

    verb = "à marquer" if args.dry_run else "marquées"
    log.info("Terminé : curseur=%d, %d signatures %s", max_pub, total_marked, verb)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
