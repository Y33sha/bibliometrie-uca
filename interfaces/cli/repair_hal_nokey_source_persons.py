#!/usr/bin/env python3
"""One-shot : répare/nettoie les `source_persons` HAL en ``nokey-*``.

Contexte
--------
~146 ``source_persons`` HAL sans ``hal_person_id`` ni ``hal_form_id``
(``source_ids`` vide), résidus d'imports passés où le composite Solr
``authFullNameFormIDPersonIDIDHal_fs`` renvoyé par HAL était partiel.
Le code actuel ne produit plus ce cas pour les publis dont le composite
est complet (vérifié en simulant la normalisation sur un échantillon).

Stratégie
---------
Pour chaque ``hal_id`` impliqué (c.-à-d. ``source_publication`` HAL
portant au moins une ``source_authorship`` vers un nokey) :

- **In-scope** pour ``extract_hal --mode full`` (``pub_year`` dans la
  fenêtre config ET au moins une collection UCA ou le tag
  ``_portail_clermont-univ``) : on **nulle ``staging.raw_hash``**. La
  prochaine extraction HAL re-ramasse la publi, le diff de hash
  déclenche l'écrasement de ``raw_data`` + ``processed=FALSE``, et la
  normalisation suivante crée les ``source_persons`` avec ``0_{form_id}``
  propres. Les ``delete_hal_duplicate_authorships`` +
  ``delete_hal_orphan_source_persons`` du post-process nettoient les
  nokey orphelins au passage.
- **Hors-scope** : on supprime ``source_publication`` (CASCADE sur
  ``source_authorships`` et ``source_authorship_addresses``), la ligne
  ``staging`` correspondante, puis les ``source_persons`` HAL nokey
  devenus orphelins. Ces publis seront éventuellement re-ramenées par
  un futur cross-import si elles sont citées ailleurs (OpenAlex, WoS).
  La ``publication`` canonique n'est PAS touchée : son
  ``source_publications.publication_id`` est SET NULL par la cascade,
  ce qui peut la rendre orpheline — les ids concernés sont loggés en
  WARNING pour revue manuelle.

Usage
-----
    python -m interfaces.cli.repair_hal_nokey_source_persons --dry-run
    python -m interfaces.cli.repair_hal_nokey_source_persons
"""

from __future__ import annotations

import argparse
import logging
import os
from typing import Any

from infrastructure.app_config import get_hal_collections, get_years
from infrastructure.db.connection import get_connection
from infrastructure.log import setup_logger

log = setup_logger("repair_hal_nokey_source_persons", os.path.dirname(__file__))


def find_nokey_hal_ids(cur: Any) -> list[dict[str, Any]]:
    """Retourne ``(hal_id, pub_year, hal_collections)`` pour chaque
    ``source_publication`` HAL portant au moins un authorship nokey.
    """
    cur.execute("""
        SELECT DISTINCT spub.source_id AS hal_id,
                        spub.pub_year,
                        spub.hal_collections
        FROM source_authorships sa
        JOIN source_persons sp   ON sp.id = sa.source_person_id
        JOIN source_publications spub ON spub.id = sa.source_publication_id
        WHERE sp.source = 'hal'
          AND sp.source_id LIKE 'nokey-%%'
          AND spub.source = 'hal'
        ORDER BY spub.source_id
    """)
    return list(cur.fetchall())


def classify(cur: Any, rows: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Partage les hal_ids entre in_scope et out_of_scope.

    In-scope = couvert par ``extract_hal --mode full`` : ``pub_year`` dans
    la fenêtre ``pipeline_years_full`` ET au moins une collection UCA
    connue (ou le tag synthétique ``_portail_clermont-univ``).
    """
    years = set(get_years(cur, mode="full"))
    uca_colls = set(get_hal_collections(cur).keys())
    in_scope: list[str] = []
    out_of_scope: list[str] = []
    for r in rows:
        colls = set(r["hal_collections"] or [])
        year_ok = r["pub_year"] in years if r["pub_year"] else False
        coll_ok = bool(colls & uca_colls) or "_portail_clermont-univ" in colls
        (in_scope if year_ok and coll_ok else out_of_scope).append(r["hal_id"])
    return in_scope, out_of_scope


def null_staging_hashes(cur: Any, hal_ids: list[str]) -> int:
    """Force la ré-extraction : ``raw_hash=NULL`` déclenchera
    ``IS DISTINCT FROM EXCLUDED.raw_hash`` au prochain ON CONFLICT →
    écrasement de ``raw_data`` + ``processed=FALSE``.
    """
    if not hal_ids:
        return 0
    cur.execute(
        "UPDATE staging SET raw_hash = NULL WHERE source = 'hal' AND source_id = ANY(%s)",
        (hal_ids,),
    )
    return cur.rowcount


def delete_hal_publications(cur: Any, hal_ids: list[str]) -> dict[str, int]:
    """Supprime source_publications HAL + staging + nokey orphelins.

    Cascade automatique via FK :
    ``source_publications`` → ``source_authorships`` →
    ``source_authorship_addresses``. La ``publication`` canonique est
    laissée intacte (son ``source_publications.publication_id`` passe à
    NULL via SET NULL).
    """
    if not hal_ids:
        return {}

    # Inventaire pré-delete pour les compteurs
    cur.execute(
        "SELECT id FROM source_publications WHERE source = 'hal' AND source_id = ANY(%s)",
        (hal_ids,),
    )
    spub_ids = [r["id"] for r in cur.fetchall()]

    cur.execute(
        "SELECT COUNT(*) AS n FROM source_authorships WHERE source_publication_id = ANY(%s)",
        (spub_ids,),
    )
    n_auths = cur.fetchone()["n"]
    cur.execute(
        """
        SELECT COUNT(*) AS n FROM source_authorship_addresses
        WHERE source_authorship_id IN (
            SELECT id FROM source_authorships WHERE source_publication_id = ANY(%s)
        )
        """,
        (spub_ids,),
    )
    n_addr = cur.fetchone()["n"]

    # Publis canoniques qui risquent de devenir orphelines
    cur.execute(
        """
        SELECT DISTINCT publication_id FROM source_publications
        WHERE id = ANY(%s) AND publication_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM source_publications sp2
              WHERE sp2.publication_id = source_publications.publication_id
                AND sp2.id != ALL(%s)
          )
        """,
        (spub_ids, spub_ids),
    )
    orphan_publication_ids = [r["publication_id"] for r in cur.fetchall()]
    if orphan_publication_ids:
        log.warning(
            "%d publications canoniques vont devenir orphelines (plus aucune source_publication) : %s",
            len(orphan_publication_ids),
            orphan_publication_ids,
        )

    # DELETE source_publications → cascade authorships + addresses
    cur.execute(
        "DELETE FROM source_publications WHERE source = 'hal' AND source_id = ANY(%s)",
        (hal_ids,),
    )
    n_pubs = cur.rowcount

    # staging n'est pas cascadé
    cur.execute(
        "DELETE FROM staging WHERE source = 'hal' AND source_id = ANY(%s)",
        (hal_ids,),
    )
    n_stag = cur.rowcount

    # source_persons HAL nokey devenus orphelins (aucun authorship restant)
    cur.execute("""
        DELETE FROM source_persons
        WHERE source = 'hal'
          AND source_id LIKE 'nokey-%%'
          AND NOT EXISTS (
              SELECT 1 FROM source_authorships
              WHERE source_person_id = source_persons.id
          )
    """)
    n_orphan_persons = cur.rowcount

    return {
        "source_authorship_addresses": n_addr,
        "source_authorships": n_auths,
        "source_publications": n_pubs,
        "staging": n_stag,
        "orphan_nokey_source_persons": n_orphan_persons,
        "orphan_publications_flagged": len(orphan_publication_ids),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Répare/nettoie les source_persons HAL en nokey-*")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compte et classe sans modifier la base",
    )
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    try:
        cur = conn.cursor()

        rows = find_nokey_hal_ids(cur)
        log.info("Publis HAL impliquées : %d", len(rows))

        in_scope, out_of_scope = classify(cur, rows)
        log.info("  in-scope (ré-extraction) : %d", len(in_scope))
        log.info("  hors-scope (suppression) : %d", len(out_of_scope))

        if args.dry_run:
            log.info("[DRY RUN] rollback, aucune modification.")
            conn.rollback()
            return

        n_nulled = null_staging_hashes(cur, in_scope)
        log.info("staging.raw_hash nullé sur %d lignes", n_nulled)

        stats = delete_hal_publications(cur, out_of_scope)
        if stats:
            log.info("Suppressions :")
            for k, v in stats.items():
                log.info("  %-32s %d", k, v)

        conn.commit()
        log.info(
            "Terminé. Étapes suivantes (manuel) : "
            "`python run_pipeline.py --mode full --only extract --sources hal` "
            "puis `--only normalize --sources hal`."
        )

    except Exception:
        conn.rollback()
        logging.getLogger().exception("Échec — rollback effectué")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
