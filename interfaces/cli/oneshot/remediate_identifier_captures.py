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

from sqlalchemy import Connection, text

from application.persons.core import IdentifierConflict
from application.pipeline.persons.resolve_identifier_transfers import resolve_identifier_transfers
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.pipeline.persons_create import PgPersonsCreateQueries
from infrastructure.repositories import person_repository

ID_TYPES = ("orcid", "idref", "hal_person_id")
log = setup_logger("remediate_identifier_captures", os.path.dirname(__file__))


def _owner_map(conn: Connection, id_type: str) -> dict[str, tuple[int, str]]:
    """`{id_value: (person_id, status)}` — propriétaires non rejetés."""
    rows = conn.execute(
        text("""
            SELECT id_value, person_id, status
            FROM person_identifiers
            WHERE id_type = :t AND status <> 'rejected'
        """),
        {"t": id_type},
    ).all()
    return {r.id_value: (r.person_id, r.status) for r in rows}


def build_stock_conflicts(conn: Connection) -> list[IdentifierConflict]:
    """Conflits du stock : chaque personne qui détient des signatures d'une valeur sans en
    être le propriétaire attribué. `resolve_identifier_transfers` tranchera par consensus."""
    conflicts: list[IdentifierConflict] = []
    for id_type in ID_TYPES:
        owners = _owner_map(conn, id_type)
        if not owners:
            continue
        source_filter = (
            "AND sa.source IN ('crossref', 'openalex', 'hal')" if id_type == "orcid" else ""
        )
        rows = conn.execute(
            text(f"""
                SELECT aik.person_identifiers->>:id_type AS id_value, sa.person_id
                FROM source_authorships sa
                JOIN author_identifying_keys aik ON aik.id = sa.identity_id
                WHERE aik.person_identifiers ? :id_type
                  AND sa.person_id IS NOT NULL
                  {source_filter}
                GROUP BY 1, 2
            """),
            {"id_type": id_type},
        ).all()
        for r in rows:
            owner = owners.get(r.id_value)
            if owner is None:
                continue
            owner_pid, status = owner
            if r.person_id != owner_pid:
                conflicts.append(
                    IdentifierConflict(id_type, r.id_value, r.person_id, owner_pid, status)
                )
    return conflicts


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Annule la transaction : compte sans écrire."
    )
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        conflicts = build_stock_conflicts(conn)
        result = resolve_identifier_transfers(
            conn,
            conflicts,
            queries=PgPersonsCreateQueries(),
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
