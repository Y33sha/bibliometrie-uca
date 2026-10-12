"""Résolution des adresses : rattachement aux structures et détection du périmètre. Nœud `affiliations.resolve_addresses`.

Lit les formes de noms depuis `structure_name_forms` et enregistre dans `address_structures` la forme à l'origine de chaque détection (`matched_form_id`).
"""

import logging
from typing import NamedTuple

import ahocorasick
from sqlalchemy import Connection, text

from domain.structures.structure import StructureType
from infrastructure.db.scalars import scalar_int
from pipeline.libelles import BRANCHE, DERNIERE_BRANCHE, forme
from pipeline.progression import progression

# Taille des tranches (pagination keyset) : borne la mémoire et les allers-retours SQL par batch.
CHUNK_SIZE = 10000


class StructureNameForm(NamedTuple):
    """Forme normalisée d'une structure consommée par le matching adresses → structures.

    `requires_context_of` : liste des structure_ids dont au moins une forme doit aussi matcher pour valider cette forme (anti-faux-positifs cross-établissement : un code de laboratoire ambigu n'est retenu que si son université de tutelle matche la même adresse). `None` ou liste vide = pas de contexte requis.
    `is_excluding` : si TRUE et que la forme matche, retire la structure des résultats même si d'autres formes la matchent.
    `structure_type` : type de la structure portant la forme. Détermine si un appariement vaut affiliation à retenir ou seulement contexte de reconnaissance (`StructureType.is_affiliation`).
    """

    id: int
    structure_id: int
    form_text: str
    is_word_boundary: bool
    requires_context_of: list[int] | None
    is_excluding: bool
    structure_type: StructureType


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

# Détections auto (`matched_form_id` posé) d'une adresse de `addr_ids` dont le couple
# (address_id, structure_id) est absent de `kept_pairs` (les couples encore détectés).
# Alias de table : `a`.
_OBSOLETE_AUTO_WHERE = """
    a.address_id = ANY(:addr_ids)
    AND a.matched_form_id IS NOT NULL
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

    def load_name_forms(self, conn: Connection) -> list[StructureNameForm]:
        rows = conn.execute(
            text("""
                SELECT nf.id, nf.structure_id, nf.form_text,
                       nf.is_word_boundary, nf.requires_context_of, nf.is_excluding,
                       s.structure_type::text AS structure_type
                FROM structure_name_forms nf
                JOIN structures s ON s.id = nf.structure_id
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
                structure_type=StructureType(r.structure_type),
            )
            for r in rows
        ]

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
                + _OBSOLETE_AUTO_WHERE
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
                + _OBSOLETE_AUTO_WHERE
                + " AND a.is_confirmed IS NOT NULL"
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


# ─── Matching ────────────────────────────────────────────────────


def _is_whole_word(text: str, start: int, end: int) -> bool:
    """Vrai si `text[start:end+1]` est un mot entier : bord de chaîne ou caractère non
    alphanumérique de part et d'autre."""
    before_ok = start == 0 or not text[start - 1].isalnum()
    after_ok = end + 1 >= len(text) or not text[end + 1].isalnum()
    return before_ok and after_ok


class StructureMatch(NamedTuple):
    """Structure `structure_id` reconnue dans une adresse par sa forme `form_id`."""

    structure_id: int
    form_id: int


class AddressMatcher:
    """Matche les formes de structures dans une adresse via un automate Aho-Corasick.

    L'automate, construit une fois sur l'ensemble des formes, détecte en un seul passage par adresse toutes les formes présentes (coût indépendant du nombre de formes).
    """

    def __init__(self, forms: list[StructureNameForm]) -> None:
        self._forms_by_id = {f.id: f for f in forms}
        by_text: dict[str, list[StructureNameForm]] = {}
        for f in forms:
            if f.form_text:
                by_text.setdefault(f.form_text, []).append(f)
        self._automaton = ahocorasick.Automaton()
        for form_text, matching_forms in by_text.items():
            self._automaton.add_word(form_text, matching_forms)
        self._empty = not by_text
        if not self._empty:
            self._automaton.make_automaton()

    def _matched_form_ids(self, text_normalized: str) -> set[int]:
        """Ids des formes présentes (sous-chaîne + contrainte de mot entier)."""
        matched: set[int] = set()
        if self._empty:
            return matched
        for end, forms_here in self._automaton.iter(text_normalized):
            for f in forms_here:
                if f.id in matched:
                    continue
                if not f.is_word_boundary or _is_whole_word(
                    text_normalized, end - len(f.form_text) + 1, end
                ):
                    matched.add(f.id)
        return matched

    def resolve(self, text_normalized: str) -> list[StructureMatch]:
        """Résout une adresse normalisée : affiliations reconnues et forme à l'origine.

        Pour chaque structure, la première forme par `id` qui matche l'emporte.

        Les structures dont le type ne vaut pas affiliation participent à l'arbitrage sans figurer au résultat : elles entrent dans `structs_matched`, donc satisfont le `requires_context_of` des formes qui les invoquent, mais ne produisent aucun rattachement.
        """
        matched_ids = self._matched_form_ids(text_normalized)
        if not matched_ids:
            return []
        matched = [self._forms_by_id[i] for i in matched_ids]
        structs_matched = {f.structure_id for f in matched}
        excluded = {f.structure_id for f in matched if f.is_excluding}

        result: list[StructureMatch] = []
        seen: set[int] = set()
        for f in sorted(matched, key=lambda f: f.id):
            sid = f.structure_id
            if sid in seen or sid in excluded or f.is_excluding:
                continue
            if not f.structure_type.is_affiliation:
                continue
            ctx = f.requires_context_of
            if ctx and not any(cid in structs_matched for cid in ctx):
                continue
            result.append(StructureMatch(sid, f.id))
            seen.add(sid)
        return result


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
    matcher = AddressMatcher(queries.load_name_forms(conn))
    return process_addresses(conn, queries, matcher, perimeter_ids, logger)


def process_addresses(
    conn: Connection,
    queries: AddressResolutionQueries,
    matcher: AddressMatcher,
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
