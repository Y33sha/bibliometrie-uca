"""Query service : matching des adresses vers les structures, phase `affiliations`.

Appelé par `application/pipeline/affiliations/resolve_addresses.py`. Regroupe le SQL de la boucle de détection automatique via `structure_name_forms` : chargement des formes, parcours des adresses par tranches, écriture des seules détections qui changent.

Séparé de `infrastructure/queries/addresses.py`, qui sert la couche API (lecture/CRUD des adresses).
"""

from sqlalchemy import Connection, text

from application.ports.pipeline.address_resolution import (
    AddressResolutionQueries,
    StructureNameForm,
)


def load_name_forms(conn: Connection) -> list[StructureNameForm]:
    """Charge toutes les formes de `structure_name_forms`, triées par `id`."""
    rows = conn.execute(
        text("""
            SELECT nf.id, nf.structure_id, nf.form_text,
                   nf.is_word_boundary, nf.requires_context_of, nf.is_excluding
            FROM structure_name_forms nf
            ORDER BY nf.id
        """)
    ).all()
    return [
        StructureNameForm(
            id=r.id,
            structure_id=r.structure_id,
            form_text=r.form_text,
            is_word_boundary=r.is_word_boundary,
            requires_context_of=r.requires_context_of,
            is_excluding=r.is_excluding,
        )
        for r in rows
    ]


def fetch_addresses_chunk(conn: Connection, *, after_id: int, limit: int) -> list[tuple[int, str]]:
    """Tranche `(id, normalized_text)` triée par `id`, `id > after_id`.

    Le matching opère sur `normalized_text` (déjà normalisé à l'insertion par
    `normalize_text`), pas sur le brut : aucun recalcul côté pipeline.
    Pagination keyset : la mémoire reste bornée par `limit`, pas par le total.
    """
    rows = conn.execute(
        text(
            "SELECT a.id, a.normalized_text FROM addresses a "
            "WHERE a.id > :after ORDER BY a.id LIMIT :limit"
        ),
        {"after": after_id, "limit": limit},
    ).all()
    return [(r.id, r.normalized_text) for r in rows]


def delete_obsolete_detections_bulk(
    conn: Connection, addr_ids: list[int], kept_pairs: list[tuple[int, int]]
) -> int:
    """Supprime en bloc les détections auto non confirmées devenues obsolètes.

    Pour les adresses `addr_ids`, retire les liens `matched_form_id IS NOT NULL`
    / `is_confirmed IS NULL` dont le `(address_id, structure_id)` n'est pas dans
    `kept_pairs` (encore détecté). Retourne le rowcount.
    """
    if not addr_ids:
        return 0
    kept_aids = [a for a, _ in kept_pairs]
    kept_sids = [s for _, s in kept_pairs]
    return conn.execute(
        text("""
            DELETE FROM address_structures a
            WHERE a.address_id = ANY(:addr_ids)
              AND a.matched_form_id IS NOT NULL
              AND a.is_confirmed IS NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM unnest(CAST(:kept_aids AS int[]), CAST(:kept_sids AS int[])) AS k(aid, sid)
                  WHERE k.aid = a.address_id AND k.sid = a.structure_id
              )
        """),
        {"addr_ids": addr_ids, "kept_aids": kept_aids, "kept_sids": kept_sids},
    ).rowcount


def unflag_obsolete_detections_bulk(
    conn: Connection, addr_ids: list[int], kept_pairs: list[tuple[int, int]]
) -> None:
    """Retire en bloc `matched_form_id` des liens manuels (is_confirmed) obsolètes.

    Les liens manuels ne sont pas supprimés, mais perdent leur marqueur auto.
    """
    if not addr_ids:
        return
    kept_aids = [a for a, _ in kept_pairs]
    kept_sids = [s for _, s in kept_pairs]
    conn.execute(
        text("""
            UPDATE address_structures a
            SET matched_form_id = NULL
            WHERE a.address_id = ANY(:addr_ids)
              AND a.matched_form_id IS NOT NULL
              AND a.is_confirmed IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM unnest(CAST(:kept_aids AS int[]), CAST(:kept_sids AS int[])) AS k(aid, sid)
                  WHERE k.aid = a.address_id AND k.sid = a.structure_id
              )
        """),
        {"addr_ids": addr_ids, "kept_aids": kept_aids, "kept_sids": kept_sids},
    )


def upsert_detected_structures_bulk(
    conn: Connection, detections: list[tuple[int, int, int]]
) -> None:
    """Insère/maj en bloc les détections `(address_id, structure_id, form_id)`.

    `resolve` garantit l'unicité de `(address_id, structure_id)` dans la tranche,
    donc l'ON CONFLICT ne porte jamais deux fois sur la même ligne. La clause
    `WHERE ... IS DISTINCT FROM` rend l'upsert idempotent : un lien dont le
    `matched_form_id` est déjà à jour n'est pas réécrit (pas de churn ni de bloat
    sur un recalcul qui ne change rien).
    """
    if not detections:
        return
    aids = [d[0] for d in detections]
    sids = [d[1] for d in detections]
    fids = [d[2] for d in detections]
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


class PgAddressResolutionQueries(AddressResolutionQueries):
    """Adapter PostgreSQL pour `application.ports.pipeline.address_resolution.AddressResolutionQueries`."""

    def load_name_forms(self, conn: Connection) -> list[StructureNameForm]:
        return load_name_forms(conn)

    def fetch_addresses_chunk(
        self, conn: Connection, *, after_id: int, limit: int
    ) -> list[tuple[int, str]]:
        return fetch_addresses_chunk(conn, after_id=after_id, limit=limit)

    def delete_obsolete_detections_bulk(
        self, conn: Connection, addr_ids: list[int], kept_pairs: list[tuple[int, int]]
    ) -> int:
        return delete_obsolete_detections_bulk(conn, addr_ids, kept_pairs)

    def unflag_obsolete_detections_bulk(
        self, conn: Connection, addr_ids: list[int], kept_pairs: list[tuple[int, int]]
    ) -> None:
        unflag_obsolete_detections_bulk(conn, addr_ids, kept_pairs)

    def upsert_detected_structures_bulk(
        self, conn: Connection, detections: list[tuple[int, int, int]]
    ) -> None:
        upsert_detected_structures_bulk(conn, detections)
