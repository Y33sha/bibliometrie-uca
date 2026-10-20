"""Résolution des adresses : rattachement aux structures et détection du périmètre. Tâche `affiliations.resolve_addresses`.

Reconnaît les structures par leurs formes de nom (`name_recognition`) et enregistre dans `address_structures` la forme à l'origine de chaque détection (`matched_form_id`).
"""

import logging
from typing import NamedTuple

from sqlalchemy import Connection, text

from infrastructure.db.scalars import scalar_int
from pipeline.runtime.observability.libelles import BRANCHE, DERNIERE_BRANCHE, forme
from pipeline.runtime.observability.progression import progression
from pipeline.transformation.structures.name_recognition import StructureNameMatcher

# Taille des tranches (pagination keyset) : borne la mémoire et les allers-retours SQL par batch.
CHUNK_SIZE = 10000


class KeptPair(NamedTuple):
    """Détection `(address_id, structure_id)` encore présente, à préserver de la purge."""

    address_id: int
    structure_id: int


class DetectedStructure(NamedTuple):
    """Détection à écrire : structure `structure_id` reconnue dans l'adresse `address_id` par la forme `form_id`."""

    address_id: int
    structure_id: int
    form_id: int


# ─── SQL ─────────────────────────────────────────────────────────

# Liens d'une adresse de `addr_ids` dont le couple (address_id, structure_id) est absent de
# `kept_pairs` (les couples encore détectés). Alias de table : `a`.
_OBSOLETE_WHERE = """
    a.address_id = ANY(:addr_ids)
    AND NOT EXISTS (
        SELECT 1
        FROM unnest(CAST(:kept_aids AS int[]), CAST(:kept_sids AS int[])) AS k(aid, sid)
        WHERE k.aid = a.address_id AND k.sid = a.structure_id
    )
"""


def _kept_arrays(kept_pairs: list[KeptPair]) -> tuple[list[int], list[int]]:
    """Éclate `kept_pairs` en tableaux parallèles `(address_ids, structure_ids)` pour l'`unnest` SQL."""
    return [p.address_id for p in kept_pairs], [p.structure_id for p in kept_pairs]


class AddressResolutionQueries:
    """Requêtes de la résolution des adresses.

    Chaque run est un recalcul complet idempotent : toutes les adresses sont traitées par tranches (keyset par `id`), et seules les détections `address_structures` qui changent sont écrites.
    """

    def count_addresses(self, conn: Connection) -> int:
        return scalar_int(conn.execute(text("SELECT count(*) FROM addresses")))

    def fetch_addresses_chunk(
        self, conn: Connection, *, after_id: int, limit: int
    ) -> list[tuple[int, str]]:
        rows = conn.execute(
            text(
                "SELECT a.id, a.normalized_text FROM addresses a "
                "WHERE a.id > :after ORDER BY a.id LIMIT :limit"
            ),
            {"after": after_id, "limit": limit},
        ).all()
        return [(r.id, r.normalized_text) for r in rows]

    def delete_obsolete_detections_bulk(
        self, conn: Connection, addr_ids: list[int], kept_pairs: list[KeptPair]
    ) -> int:
        if not addr_ids:
            return 0
        kept_aids, kept_sids = _kept_arrays(kept_pairs)
        return conn.execute(
            text(
                "DELETE FROM address_structures a WHERE "
                + _OBSOLETE_WHERE
                + " AND a.is_confirmed IS NULL"
            ),
            {"addr_ids": addr_ids, "kept_aids": kept_aids, "kept_sids": kept_sids},
        ).rowcount

    def unflag_obsolete_detections_bulk(
        self, conn: Connection, addr_ids: list[int], kept_pairs: list[KeptPair]
    ) -> None:
        if not addr_ids:
            return
        kept_aids, kept_sids = _kept_arrays(kept_pairs)
        conn.execute(
            text(
                "UPDATE address_structures a SET matched_form_id = NULL WHERE "
                + _OBSOLETE_WHERE
                + " AND a.matched_form_id IS NOT NULL AND a.is_confirmed IS NOT NULL"
            ),
            {"addr_ids": addr_ids, "kept_aids": kept_aids, "kept_sids": kept_sids},
        )

    def upsert_detected_structures_bulk(
        self, conn: Connection, detections: list[DetectedStructure]
    ) -> None:
        if not detections:
            return
        aids = [d.address_id for d in detections]
        sids = [d.structure_id for d in detections]
        fids = [d.form_id for d in detections]
        conn.execute(
            text("""
                INSERT INTO address_structures (address_id, structure_id, matched_form_id)
                SELECT aid, sid, fid
                FROM unnest(CAST(:aids AS int[]), CAST(:sids AS int[]), CAST(:fids AS int[]))
                     AS t(aid, sid, fid)
                ON CONFLICT (address_id, structure_id)
                    DO UPDATE SET matched_form_id = EXCLUDED.matched_form_id
                    WHERE address_structures.matched_form_id IS DISTINCT FROM EXCLUDED.matched_form_id
            """),
            {"aids": aids, "sids": sids, "fids": fids},
        )


# ─── Run ─────────────────────────────────────────────────────────


class ResolutionStats(NamedTuple):
    """Bilan d'une passe de résolution d'adresses."""

    processed: int  # adresses traitées
    in_perimeter: int  # adresses portant ≥1 structure du périmètre
    affiliations: int  # liens adresse↔structure détectés


def run_resolution(
    conn: Connection,
    queries: AddressResolutionQueries,
    perimeter_ids: set[int],
    logger: logging.Logger,
) -> ResolutionStats:
    """Recalcul complet idempotent des affiliations (commit par lot, d'où le `conn`)."""
    matcher = StructureNameMatcher.load(conn)
    return process_addresses(conn, queries, matcher, perimeter_ids, logger)


def process_addresses(
    conn: Connection,
    queries: AddressResolutionQueries,
    matcher: StructureNameMatcher,
    perimeter: set[int],
    logger: logging.Logger,
    *,
    chunk_size: int = CHUNK_SIZE,
) -> ResolutionStats:
    """Résout toutes les adresses par tranches (keyset) : matching mémoire + écritures en bloc.

    Chaque tranche est lue et matchée en mémoire, puis mise à jour des liens adresse→structure en base pour qu'ils correspondent au matching, en trois requêtes ensemblistes : on retire les liens automatiques qui ne sont plus détectés ; un lien confirmé par l'admin est conservé mais perd sa marque « automatique » ; les liens trouvés cette fois sont insérés ou mis à jour. Seul ce qui change est écrit ; mémoire et allers-retours SQL bornés par `chunk_size`.
    """

    processed = 0
    in_perimeter_count = 0
    affil_count = 0
    removed_count = 0
    after_id = 0

    with progression(queries.count_addresses(conn), BRANCHE.rstrip(), logger) as avancement:
        while True:
            rows = queries.fetch_addresses_chunk(conn, after_id=after_id, limit=chunk_size)
            if not rows:
                break
            after_id = rows[-1][0]  # tranche triée par id

            addr_ids: list[int] = []
            detections: list[DetectedStructure] = []
            kept_pairs: list[KeptPair] = []
            for addr_id, normalized_text in rows:
                addr_ids.append(addr_id)
                matches = matcher.resolve(normalized_text)
                if any(m.structure_id in perimeter for m in matches):
                    in_perimeter_count += 1
                for match in matches:
                    detections.append(DetectedStructure(addr_id, match.structure_id, match.form_id))
                    kept_pairs.append(KeptPair(addr_id, match.structure_id))
                    affil_count += 1

            removed_count += queries.delete_obsolete_detections_bulk(conn, addr_ids, kept_pairs)
            queries.unflag_obsolete_detections_bulk(conn, addr_ids, kept_pairs)
            queries.upsert_detected_structures_bulk(conn, detections)
            conn.commit()

            processed += len(rows)
            avancement.avance(len(rows))

    if processed > 0:
        logger.info(
            "%sstructures du périmètre identifiées dans %s %s (%.1f%%)",
            DERNIERE_BRANCHE,
            in_perimeter_count,
            forme(in_perimeter_count, "adresse"),
            100 * in_perimeter_count / processed,
        )

    return ResolutionStats(processed, in_perimeter_count, affil_count)
