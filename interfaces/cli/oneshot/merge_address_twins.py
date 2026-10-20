# STATUS: oneshot (2026-10-16)
"""Fusionne les adresses de même forme normalisée, et supprime les adresses de forme normalisée vide.

Prépare l'unicité de `addresses.normalized_text`. Chaque groupe de jumelles garde l'adresse de plus grand `publication_count`, la plus ancienne à égalité :

- ses contributions sources, ROR et liens aux structures réunissent ceux des jumelles ;
- un lien à une structure confirmé sur une jumelle et infirmé sur une autre redevient à examiner ;
- ses pays réunissent ceux des jumelles, et `countries_dirty` est posé.

Les jumelles sont ensuite supprimées. Une adresse de forme normalisée vide (« ; », « ). ») est supprimée avec ses liens.

Le script exige des formes normalisées à jour : il refuse de tourner tant qu'une forme stockée diffère de `normalize_text(raw_text)`. `recompute_normalized_texts` le précède.

Usage :
    python -m interfaces.cli.oneshot.merge_address_twins            # exécution
    python -m interfaces.cli.oneshot.merge_address_twins --dry-run  # rapport seul
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, text

from domain.normalize import normalize_text
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("merge_address_twins", os.path.dirname(__file__))


class StaleNormalizedTextError(RuntimeError):
    """Des formes normalisées stockées diffèrent de `normalize_text(raw_text)`."""


def check_normalized_texts(conn: Connection) -> None:
    """Lève `StaleNormalizedTextError` si une forme stockée diffère de `normalize_text(raw_text)`."""
    stale = sum(
        1
        for raw, stored in conn.execute(text("SELECT raw_text, normalized_text FROM addresses"))
        if normalize_text(raw) != stored
    )
    if stale:
        raise StaleNormalizedTextError(
            f"{stale} formes normalisées périmées : lancer recompute_normalized_texts d'abord"
        )


_STEPS = (
    (
        "jumelles",
        """
        CREATE TEMP TABLE _twins ON COMMIT DROP AS
        SELECT id AS old_id, keeper
        FROM (
            SELECT id, first_value(id) OVER (
                PARTITION BY normalized_text ORDER BY publication_count DESC NULLS LAST, id
            ) AS keeper
            FROM addresses
            WHERE normalized_text <> ''
        ) ranked
        WHERE id <> keeper
        """,
    ),
    (
        "liens aux contributions sources repris",
        """
        INSERT INTO source_contribution_addresses (source_contribution_id, address_id)
        SELECT DISTINCT sca.source_contribution_id, t.keeper
        FROM source_contribution_addresses sca
        JOIN _twins t ON t.old_id = sca.address_id
        ON CONFLICT DO NOTHING
        """,
    ),
    (
        "ROR repris",
        """
        INSERT INTO source_contribution_rors (source_contribution_id, ror_id, address_id)
        SELECT DISTINCT r.source_contribution_id, r.ror_id, t.keeper
        FROM source_contribution_rors r
        JOIN _twins t ON t.old_id = r.address_id
        ON CONFLICT DO NOTHING
        """,
    ),
    (
        "liens aux structures réunis",
        """
        CREATE TEMP TABLE _merged_structures ON COMMIT DROP AS
        WITH members AS (
            SELECT keeper, keeper AS address_id FROM _twins
            UNION
            SELECT keeper, old_id FROM _twins
        )
        SELECT m.keeper, ast.structure_id,
               CASE WHEN bool_or(ast.is_confirmed) AND bool_or(NOT ast.is_confirmed) THEN NULL
                    ELSE bool_or(ast.is_confirmed) END AS is_confirmed,
               (array_agg(ast.matched_form_id ORDER BY ast.address_id = m.keeper DESC)
                   FILTER (WHERE ast.matched_form_id IS NOT NULL))[1] AS matched_form_id
        FROM members m
        JOIN address_structures ast ON ast.address_id = m.address_id
        GROUP BY m.keeper, ast.structure_id
        """,
    ),
    (
        "liens aux structures des adresses gardées effacés",
        "DELETE FROM address_structures WHERE address_id IN (SELECT keeper FROM _twins)",
    ),
    (
        "liens aux structures réécrits",
        """
        INSERT INTO address_structures (address_id, structure_id, is_confirmed, matched_form_id)
        SELECT keeper, structure_id, is_confirmed, matched_form_id FROM _merged_structures
        """,
    ),
    (
        "pays réunis",
        """
        UPDATE addresses a
        SET countries = u.countries, countries_dirty = TRUE
        FROM (
            SELECT g.keeper,
                   nullif(array(
                       SELECT DISTINCT c FROM addresses x, unnest(x.countries) c
                       WHERE x.id = g.keeper OR x.id = ANY(g.olds) ORDER BY c
                   ), '{}') AS countries
            FROM (SELECT keeper, array_agg(old_id) AS olds FROM _twins GROUP BY keeper) g
        ) u
        WHERE a.id = u.keeper
        """,
    ),
    ("jumelles supprimées", "DELETE FROM addresses WHERE id IN (SELECT old_id FROM _twins)"),
    ("formes vides supprimées", "DELETE FROM addresses WHERE normalized_text = ''"),
)


def merge(conn: Connection) -> dict[str, int]:
    """Fusionne les jumelles et supprime les formes vides. Retourne le nombre de lignes de chaque étape. Ne commite pas."""
    check_normalized_texts(conn)
    counts: dict[str, int] = {}
    for label, sql in _STEPS:
        counts[label] = conn.execute(text(sql)).rowcount
    counts["groupes"] = conn.execute(text("SELECT count(DISTINCT keeper) FROM _twins")).scalar_one()
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Rapport seul : n'écrit rien (défaut : applique)."
    )
    apply = not parser.parse_args().dry_run
    with get_sync_engine().connect() as conn:
        for label, n in merge(conn).items():
            log.info("%s : %d", label, n)
        if apply:
            conn.commit()
            log.info("✓ fusion appliquée")
        else:
            conn.rollback()
            log.info("DRY-RUN — aucune écriture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
