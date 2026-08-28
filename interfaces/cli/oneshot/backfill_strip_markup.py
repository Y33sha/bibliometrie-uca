# STATUS: oneshot (2026-08-28)
"""Retire du stock le balisage et les entités HTML des champs qui s'affichent en texte.

`to_plain_text` fait cette mise à plat à l'entrée du pipeline (adresses, sujets, signatures, titres de revue, noms d'éditeur). Ce script corrige ce que les runs précédents ont déposé, en appliquant à chaque champ la fonction qui le garde désormais.

Deux champs portent un index unique sur leur valeur affichée — `md5(raw_text)` pour les adresses, `lower(label)` pour les sujets. La mise à plat peut donc faire converger deux lignes : le script les fusionne, en repointant les tables de jonction vers la ligne survivante puis en supprimant la doublure. La survivante est la ligne de plus petit identifiant, arbitraire mais stable.

Les autres champs n'ont pas d'index sur leur valeur affichée : la mise à plat est une simple réécriture.

Les colonnes normalisées (`*_normalized`, formes de nom) ne sont pas recalculées : `normalize_text` retire déjà le balisage, si bien qu'elles ne changent pas. Elle ne décode en revanche pas les entités, ce qui laisse en base des revues et des éditeurs dédoublés par le seul encodage — le script les recense en fin de rapport, sans les fusionner : la fusion d'une revue ou d'un éditeur a ses règles et son écran d'administration.

Usage :
    python -m interfaces.cli.oneshot.backfill_strip_markup            # exécution
    python -m interfaces.cli.oneshot.backfill_strip_markup --dry-run  # rapport seul
"""

from __future__ import annotations

import argparse
import hashlib
import os
from collections.abc import Callable

from sqlalchemy import Connection, text

from domain.normalize import (
    clean_raw_author_name,
    normalize_label,
    normalize_text,
    sanitize_raw_text,
    to_plain_text,
)
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("backfill_strip_markup", os.path.dirname(__file__))

# Une valeur porte une balise, un commentaire ou une entité HTML. Le prédicat vit en SQL pour
# que seules les lignes concernées remontent — le stock se compte en centaines de milliers.
_POLLUTED = r"~ '</?[A-Za-z][^>]*>|<!--|&[a-zA-Z]{2,8};|&#[0-9]+;'"

# Champs sans index unique sur la valeur affichée : la mise à plat est une réécriture.
_SIMPLES: list[tuple[str, str, Callable[[str], str]]] = [
    ("journals", "title", to_plain_text),
    ("publishers", "name", to_plain_text),
    ("source_authorships", "raw_author_name", clean_raw_author_name),
]


def _rewrite_simple(
    conn: Connection, table: str, column: str, clean: Callable[[str], str], apply: bool
) -> None:
    """Réécrit en place les valeurs mises à plat d'un champ sans contrainte d'unicité."""
    rows = list(
        conn.execute(text(f"SELECT id, {column} AS v FROM {table} WHERE {column} {_POLLUTED}"))
    )
    changed = [(r.id, clean(r.v)) for r in rows if clean(r.v) != r.v]
    log.info("%s.%s : %d lignes à mettre à plat", table, column, len(changed))
    for row_id, value in changed[:5]:
        log.info("    %s → %r", row_id, value[:80])
    if apply and changed:
        conn.execute(
            text(f"UPDATE {table} SET {column} = :v WHERE id = :id"),
            [{"id": i, "v": v} for i, v in changed],
        )


def _merge_and_rewrite(
    conn: Connection,
    table: str,
    column: str,
    clean: Callable[[str], str],
    key_sql: str,
    junctions: list[tuple[str, str]],
    apply: bool,
) -> None:
    """Met à plat un champ dont l'unicité porte sur la valeur affichée, en fusionnant les convergences.

    `key_sql` est l'expression de la clé unique (`md5(raw_text)`, `lower(label)`) : elle sert à retrouver la ligne survivante quand la valeur mise à plat existe déjà. `junctions` liste les tables qui référencent la ligne, avec la colonne porteuse.
    """
    rows = list(
        conn.execute(text(f"SELECT id, {column} AS v FROM {table} WHERE {column} {_POLLUTED}"))
    )
    changed = [(r.id, clean(r.v)) for r in rows if clean(r.v) != r.v]

    # Ligne survivante par valeur mise à plat : celle qui la porte déjà, sinon le plus petit
    # identifiant parmi celles qui convergent dessus.
    survivant: dict[str, int] = {}
    for row_id, value in sorted(changed, key=lambda p: p[1]):
        survivant.setdefault(value, row_id)
    existing = {
        r.v: r.id
        for r in conn.execute(
            text(f"SELECT id, {column} AS v FROM {table} WHERE {key_sql} = ANY(:keys)"),
            {"keys": [_key_of(key_sql, v) for v in survivant]},
        )
    }
    survivant.update(existing)

    fusions = [
        (row_id, survivant[value]) for row_id, value in changed if survivant[value] != row_id
    ]
    reecritures = [(row_id, value) for row_id, value in changed if survivant[value] == row_id]
    log.info(
        "%s.%s : %d lignes à mettre à plat — %d réécritures, %d fusions",
        table,
        column,
        len(changed),
        len(reecritures),
        len(fusions),
    )
    if not apply:
        return

    if reecritures:
        conn.execute(
            text(f"UPDATE {table} SET {column} = :v WHERE id = :id"),
            [{"id": i, "v": v} for i, v in reecritures],
        )
    for perdant, gagnant in fusions:
        for junction, col in junctions:
            # Le repointage peut heurter l'unicité de la jonction quand les deux lignes
            # portaient déjà le même rattachement : le doublon est alors simplement écarté.
            conn.execute(
                text(
                    f"UPDATE {junction} SET {col} = :gagnant WHERE {col} = :perdant "
                    f"AND NOT EXISTS (SELECT 1 FROM {junction} j2 "
                    f"WHERE j2.{col} = :gagnant AND {_same_row_sql(junction, col)})"
                ),
                {"gagnant": gagnant, "perdant": perdant},
            )
        conn.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": perdant})


def _key_of(key_sql: str, value: str) -> str:
    """Valeur de la clé unique côté Python, pour interroger l'index sans aller-retour."""
    if key_sql.startswith("md5"):
        return hashlib.md5(value.encode(), usedforsecurity=False).hexdigest()
    return value.lower()


def _same_row_sql(junction: str, col: str) -> str:
    """Condition d'identité d'un rattachement, hors la colonne repointée : ce qui rend un repointage redondant."""
    autres = {
        "address_structures": ["structure_id"],
        "source_authorship_addresses": ["source_authorship_id"],
        "publication_subjects": ["publication_id", "source"],
    }[junction]
    return " AND ".join(f"j2.{c} = {junction}.{c}" for c in autres)


def _report_revealed_duplicates(conn: Connection) -> None:
    """Recense les revues et éditeurs que la mise à plat rend identiques sans les fusionner.

    `normalize_text` ne décode pas les entités : `Wood &amp; Fire Safety` et `Wood & Fire Safety` ont deux clés distinctes et vivent en deux lignes. La mise à plat les rend visiblement identiques ; les réunir demande la fusion, qui a ses règles.
    """
    for table, column in (("journals", "title"), ("publishers", "name")):
        rows = [(r.id, r.v) for r in conn.execute(text(f"SELECT id, {column} AS v FROM {table}"))]
        avant = {i: normalize_text(v) for i, v in rows}
        apres: dict[str, list[int]] = {}
        for row_id, value in rows:
            apres.setdefault(normalize_text(to_plain_text(value)), []).append(row_id)
        valeur = dict(rows)
        groupes = [
            ids for ids in apres.values() if len(ids) > 1 and len({avant[i] for i in ids}) > 1
        ]
        log.info("%s : %d doublons révélés par la mise à plat (non fusionnés)", table, len(groupes))
        for ids in groupes:
            log.info("    %s — %s", ids, [valeur[i][:60] for i in ids])


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
        _merge_and_rewrite(
            conn,
            "addresses",
            "raw_text",
            sanitize_raw_text,
            "md5(raw_text)",
            [("address_structures", "address_id"), ("source_authorship_addresses", "address_id")],
            apply,
        )
        _merge_and_rewrite(
            conn,
            "subjects",
            "label",
            normalize_label,
            "lower(label)",
            [("publication_subjects", "subject_id")],
            apply,
        )
        for table, column, clean in _SIMPLES:
            _rewrite_simple(conn, table, column, clean, apply)
        _report_revealed_duplicates(conn)
        if apply:
            conn.commit()
            log.info("✓ backfill appliqué")
        else:
            log.info("DRY-RUN terminé — aucune écriture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
