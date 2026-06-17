# STATUS: oneshot (2026-06-17)
"""Assainit `addresses.raw_text` sur le stock existant (purge des caractères invisibles).

Le `normalize` remplit désormais `raw_text` via `domain.normalize.sanitize_raw_text` (espaces
Unicode → espace simple, suppression des invisibles de format/contrôle, collapse des espaces).
Les adresses déjà en base gardent leur forme bruitée — typiquement un espace insécable (U+00A0)
qui empêche la recherche admin `unaccent(raw_text) ILIKE` de retrouver le texte tapé au clavier.
Ce one-shot les ré-assainit.

Ré-écrire `raw_text` change `md5(raw_text)`, la clé de dédoublonnage : deux adresses qui ne
différaient que par un caractère invisible convergent alors sur la même forme. Le script fusionne
ces doublons :
  - garde l'`id` le plus petit du groupe (keeper) ; les autres sont absorbés puis supprimés ;
  - repointe `source_authorship_addresses` vers le keeper (doublons `(sa_id, address_id)` éliminés) ;
  - repointe `address_structures` vers le keeper ; sur une même structure, la décision humaine
    (`is_confirmed` TRUE/FALSE) prime sur un lien pending (NULL), `matched_form_id` = premier non-NULL ;
  - `recompute_pub_count()` rétablit `addresses.pub_count`.

Idempotent : un second run ne trouve plus rien à assainir ni à fusionner.

Usage :
    python -m interfaces.cli.oneshot.sanitize_addresses_raw_text [--dry-run]
"""

from __future__ import annotations

import argparse
import os
from collections import defaultdict

from sqlalchemy import text

from domain.normalize import normalize_text, sanitize_raw_text
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.repositories.address_linker import recompute_pub_count

log = setup_logger("sanitize_addresses_raw_text", os.path.dirname(__file__))

COMMIT_EVERY = 500  # groupes de fusion entre deux commits
UPDATE_BATCH = 5000  # lignes par batch d'UPDATE raw_text


def _merge_is_confirmed(values: list[bool | None]) -> bool | None:
    """Fusionne les `is_confirmed` d'une même structure : la décision humaine prime sur le pending.

    TRUE l'emporte sur FALSE (filet : aucun conflit TRUE/FALSE n'existe sur le stock observé) ;
    NULL (pending) ne l'emporte jamais sur une décision.
    """
    if any(v is True for v in values):
        return True
    if any(v is False for v in values):
        return False
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche le plan (compte) et sort sans rien modifier.",
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, raw_text FROM addresses")).fetchall()
        original = {r.id: r.raw_text for r in rows}

        by_canonical: dict[str, list[int]] = defaultdict(list)
        for r in rows:
            by_canonical[sanitize_raw_text(r.raw_text)].append(r.id)

        merges: list[tuple[int, list[int], str]] = []  # (keeper, others, canonical)
        updates: list[tuple[int, str]] = []  # (id, canonical) où raw_text change
        for canonical, ids in by_canonical.items():
            ids_sorted = sorted(ids)
            keeper, others = ids_sorted[0], ids_sorted[1:]
            if others:
                merges.append((keeper, others, canonical))
            if original[keeper] != canonical:
                updates.append((keeper, canonical))

        absorbed = sum(len(o) for _, o, _ in merges)
        log.info(
            "%d adresses ; %d raw_text à ré-écrire ; %d groupes à fusionner (%d adresses absorbées)",
            len(rows),
            len(updates),
            len(merges),
            absorbed,
        )

        if args.dry_run:
            log.info("DRY-RUN : aucune modification appliquée.")
            return 0

        # ── Phase 1 : fusion des doublons (repointage des enfants + suppression des absorbées) ──
        # Préchargement des address_structures de tous les ids concernés, groupés par canonical.
        id2canon: dict[int, str] = {}
        for keeper, others, canonical in merges:
            for i in (keeper, *others):
                id2canon[i] = canonical
        coll_ids = list(id2canon)
        ast_by_canon: dict[str, list] = defaultdict(list)
        if coll_ids:
            ast_rows = conn.execute(
                text(
                    "SELECT id, address_id, structure_id, is_confirmed, matched_form_id "
                    "FROM address_structures WHERE address_id = ANY(:ids)"
                ),
                {"ids": coll_ids},
            ).fetchall()
            for ar in ast_rows:
                ast_by_canon[id2canon[ar.address_id]].append(ar)

        merged = 0
        for keeper, others, canonical in merges:
            group_all = [keeper, *others]

            # source_authorship_addresses : éliminer les doublons (sa_id) puis repointer vers keeper.
            conn.execute(
                text(
                    "DELETE FROM source_authorship_addresses x "
                    "WHERE x.address_id = ANY(:others) AND EXISTS ("
                    "  SELECT 1 FROM source_authorship_addresses y "
                    "  WHERE y.source_authorship_id = x.source_authorship_id "
                    "    AND y.address_id = ANY(:group_all) AND y.address_id < x.address_id)"
                ),
                {"others": others, "group_all": group_all},
            )
            conn.execute(
                text(
                    "UPDATE source_authorship_addresses SET address_id = :keeper "
                    "WHERE address_id = ANY(:others)"
                ),
                {"keeper": keeper, "others": others},
            )

            # address_structures : un survivant par structure, repointé vers keeper, valeurs fusionnées.
            by_struct: dict[int, list] = defaultdict(list)
            for ar in ast_by_canon.get(canonical, []):
                by_struct[ar.structure_id].append(ar)
            for srows in by_struct.values():
                if len(srows) == 1 and srows[0].address_id == keeper:
                    continue
                merged_conf = _merge_is_confirmed([r.is_confirmed for r in srows])
                matches = [r.matched_form_id for r in srows if r.matched_form_id is not None]
                merged_match = matches[0] if matches else None
                keeper_rows = [r for r in srows if r.address_id == keeper]
                survivor = keeper_rows[0] if keeper_rows else min(srows, key=lambda r: r.id)
                conn.execute(
                    text(
                        "UPDATE address_structures "
                        "SET address_id = :keeper, is_confirmed = :mc, matched_form_id = :mm "
                        "WHERE id = :sid"
                    ),
                    {"keeper": keeper, "mc": merged_conf, "mm": merged_match, "sid": survivor.id},
                )
                dead = [r.id for r in srows if r.id != survivor.id]
                if dead:
                    conn.execute(
                        text("DELETE FROM address_structures WHERE id = ANY(:dead)"),
                        {"dead": dead},
                    )

            conn.execute(text("DELETE FROM addresses WHERE id = ANY(:others)"), {"others": others})
            merged += 1
            if merged % COMMIT_EVERY == 0:
                conn.commit()
                log.info("  fusion : %d/%d groupes...", merged, len(merges))
        conn.commit()
        if merges:
            log.info("✓ %d groupes fusionnés (%d adresses absorbées)", len(merges), absorbed)

        # ── Phase 2 : ré-écriture de raw_text / normalized_text sur les survivants ──
        # Après la phase 1, les absorbées sont supprimées : plus aucune collision md5 possible.
        done = 0
        for start in range(0, len(updates), UPDATE_BATCH):
            chunk = updates[start : start + UPDATE_BATCH]
            conn.execute(
                text(
                    "UPDATE addresses SET raw_text = :raw, normalized_text = :norm WHERE id = :id"
                ),
                [{"id": i, "raw": c, "norm": normalize_text(c)} for i, c in chunk],
            )
            conn.commit()
            done += len(chunk)
            log.info("  raw_text : %d/%d ré-écrits...", done, len(updates))
        if updates:
            log.info("✓ %d raw_text assainis", len(updates))

        # ── Phase 3 : recompute pub_count (les fusions ont redistribué les liens) ──
        n = recompute_pub_count(conn)
        conn.commit()
        log.info("✓ pub_count recalculé (%d adresses mises à jour)", n)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
