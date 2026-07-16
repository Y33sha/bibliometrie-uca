"""Oneshot — réattribuer par consensus les identifiants du stock portés par plusieurs personnes.

Le chemin forward de la phase personnes ne corrige que les **nouveaux** conflits. Le stock
peut porter un identifiant dont les signatures sont réparties sur **plusieurs personnes** :
un doublon (deux fiches d'une même personne), ou une signature étrangère qu'un identifiant a
traînée sur une autre personne existante. Ce passage réattribue l'identifiant à la personne
que soutient le consensus des porteurs.

Jamais de scission ni de fusion. La réattribution ne fait que déplacer l'identifiant entre
des personnes qui **existent déjà** :

- une valeur portée par ≥ 2 personnes → transfert vers celle du consensus (la fusion d'un
  éventuel doublon relève du dédoublonnage assisté, séparé) ;
- une valeur dont tous les porteurs sont sur une seule personne (formes étrangères l'ayant
  polluée, sans créer d'autre personne) → **no-op**, rien à réattribuer ;
- un consensus qui désigne le propriétaire → on garde.

Réutilise exactement la décision du forward (`resolve_identifier_transfers`). Committe par
défaut ; `--dry-run` annule la transaction après coup (les compteurs sont réels, rien n'est écrit).
"""

import argparse
import os
import sys

from application.pipeline.persons.resolve_identifier_transfers import (
    detect_identifier_conflicts,
    resolve_identifier_transfers,
)
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.pipeline.persons_matching import PgPersonsMatchingQueries
from infrastructure.repositories import person_repository

log = setup_logger("remediate_identifier_captures", os.path.dirname(__file__))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Annule la transaction : compte sans écrire."
    )
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        queries = PgPersonsMatchingQueries()
        conflicts = detect_identifier_conflicts(conn, queries)
        result = resolve_identifier_transfers(
            conn,
            conflicts,
            queries=queries,
            repo=person_repository(conn),
            logger=log,
        )
        print(
            f"\nConflits du stock : {result['conflicts']} "
            f"({result['pending']} sur propriétaire pending)"
        )
        print(f"Identifiants réattribués par consensus : {result['transferred']}")
        if args.dry_run:
            conn.rollback()
            print("\nDry-run : transaction annulée, rien écrit.")
        else:
            conn.commit()
            print("\n✓ Réattributions committées.")


if __name__ == "__main__":
    main()
