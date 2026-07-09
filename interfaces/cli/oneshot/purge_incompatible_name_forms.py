"""Oneshot — re-orpheliner les signatures attachées à une personne dont le nom ne corrobore pas.

Le canal nominal n'attache une signature à une personne que si sa forme de nom corrobore
celle de la personne. Une signature attachée à une personne dont le nom **ne corrobore
pas** n'a donc pas pu s'y attacher par le nom : elle vient d'un identifiant qui a traîné
une signature étrangère (un ORCID/IdRef recopié sur le mauvais co-auteur). Le forward de
la phase personnes ne reprend une forme nominale que si elle *devient ambiguë* (désigne
≥ 2 personnes) ; une signature étrangère isolée sur une personne n'est jamais reprise. Ce
passage nettoie ce stock.

La corroboration rejoue **exactement** celle du barreau identifiant du pipeline
(`decide_match_by_identifier`) : `same_person_name(parse_raw_author_name(raw_author_name),
nom, prénom canoniques)`. Le test porte sur la signature **brute**, qui conserve l'ordre
nom/prénom et les virgules — une variante de graphie ou un nom composé réordonné
(« Benrabah, Mohamed » pour « Mohamed Benrabah ») corrobore et reste attaché, seul le nom
franchement étranger ou l'homonyme à prénom autre est re-orphelinée.

Pour chaque signature qui ne corrobore pas : `person_id → NULL` (la cascade la re-résout
au prochain run). Les formes `pending` devenues sans support sont supprimées.

Périmètre : signatures portées par une forme `pending` non dérivée du nom canonique
(source `'persons'`). Les formes `confirmed`/`rejected` (verdict admin, changement de nom
inclus) et les signatures épinglées (`confirmed_authorships`) sont hors périmètre.

Committe par défaut ; `--dry-run` annule la transaction (les compteurs restent réels).
"""

import argparse
import os
import sys

from sqlalchemy import bindparam, text

from domain.persons.name_matching import parse_raw_author_name, same_person_name
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("purge_incompatible_name_forms", os.path.dirname(__file__))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Annule la transaction : compte sans écrire."
    )
    parser.add_argument(
        "--examples", type=int, default=25, help="Nombre d'exemples de captures affichés."
    )
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        # Signatures portées par une forme `pending` non canonique, non épinglées : le
        # seul gisement possible de captures (une forme canonique ou `confirmed` corrobore
        # par construction ; une signature `names_compatible` l'est aussi via
        # `same_person_name`, sur-ensemble de `names_compatible`).
        candidates = conn.execute(
            text("""
                SELECT sa.id,
                       sa.raw_author_name,
                       sa.person_id,
                       aik.author_name_normalized AS name_form,
                       p.last_name,
                       p.first_name
                FROM source_authorships sa
                JOIN author_identifying_keys aik ON aik.id = sa.identity_id
                JOIN persons p ON p.id = sa.person_id
                JOIN person_name_forms pnf
                  ON pnf.name_form = aik.author_name_normalized
                 AND pnf.person_id = sa.person_id
                WHERE sa.person_id IS NOT NULL
                  AND pnf.status = 'pending'
                  AND NOT ('persons' = ANY(pnf.sources))
                  AND NOT EXISTS (
                    SELECT 1 FROM confirmed_authorships ca
                    WHERE ca.source_authorship_id = sa.id
                  )
            """)
        ).fetchall()

        captures: list[tuple] = []  # (sa_id, raw, person_id, name_form, last, first)
        for sa_id, raw, person_id, name_form, last_name, first_name in candidates:
            sig_last, sig_first = parse_raw_author_name(raw)
            if not same_person_name(sig_last, sig_first, last_name, first_name):
                captures.append((sa_id, raw, person_id, name_form, last_name, first_name))

        affected_forms = {(c[3], c[2]) for c in captures}
        print(f"Signatures examinées (formes `pending` non canoniques) : {len(candidates)}")
        print(
            f"Captures (nom non corroboré) : {len(captures)} signatures re-orphelinées, "
            f"sous {len(affected_forms)} formes."
        )
        for sa_id, raw, person_id, _name_form, last_name, first_name in captures[: args.examples]:
            canon = f"{first_name or ''} {last_name}".strip()
            print(f"  SA#{sa_id}  « {raw} »  →  personne #{person_id} « {canon} »")

        if not captures:
            print("\nRien à re-orpheliner.")
            return

        # Re-orpheliner les signatures étrangères.
        conn.execute(
            text("""
                UPDATE source_authorships
                SET person_id = NULL, resolution_mode = NULL
                WHERE id IN :ids
            """).bindparams(bindparam("ids", expanding=True)),
            {"ids": [c[0] for c in captures]},
        )

        # Supprimer les formes `pending` non canoniques qui n'ont plus aucune signature
        # de support après re-orphelinage (une forme encore portée par une signature
        # épinglée survit). Les couples affectés transitent par une table temporaire.
        conn.execute(text("CREATE TEMP TABLE _purge_pairs (name_form text, person_id integer)"))
        conn.execute(
            text("INSERT INTO _purge_pairs (name_form, person_id) VALUES (:name_form, :person_id)"),
            [{"name_form": nf, "person_id": pid} for nf, pid in affected_forms],
        )
        deleted = conn.execute(
            text("""
                DELETE FROM person_name_forms p
                USING _purge_pairs pp
                WHERE p.name_form = pp.name_form
                  AND p.person_id = pp.person_id
                  AND p.status = 'pending'
                  AND NOT ('persons' = ANY(p.sources))
                  AND NOT EXISTS (
                    SELECT 1 FROM source_authorships sa
                    JOIN author_identifying_keys aik ON aik.id = sa.identity_id
                    WHERE sa.person_id = p.person_id
                      AND aik.author_name_normalized = p.name_form
                  )
            """)
        ).rowcount
        conn.execute(text("DROP TABLE _purge_pairs"))
        print(f"Formes `pending` supprimées (sans support restant) : {deleted}")

        if args.dry_run:
            conn.rollback()
            print("\nDry-run : transaction annulée, rien écrit.")
        else:
            conn.commit()
            print("\n✓ Purge committée.")


if __name__ == "__main__":
    main()
