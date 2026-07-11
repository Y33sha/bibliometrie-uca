"""Résolution des adresses : rattachement aux structures et détection du périmètre.

Lit les formes de noms depuis `structure_name_forms` et enregistre dans `address_structures` la forme à l'origine de chaque détection (`matched_form_id`).
"""

import logging
import time

import ahocorasick
from sqlalchemy import Connection

from application.ports.pipeline.address_resolution import (
    AddressResolutionQueries,
    StructureNameForm,
)

# Taille des tranches (pagination keyset) : borne la mémoire et les allers-retours SQL par batch.
CHUNK_SIZE = 10000


# ─── Matching ────────────────────────────────────────────────────


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
        n = len(text_normalized)
        for end, forms_here in self._automaton.iter(text_normalized):
            for f in forms_here:
                if f.id in matched:
                    continue
                if f.is_word_boundary:
                    start = end - len(f.form_text) + 1
                    before_ok = start == 0 or not text_normalized[start - 1].isalnum()
                    after_ok = end + 1 >= n or not text_normalized[end + 1].isalnum()
                    if before_ok and after_ok:
                        matched.add(f.id)
                else:
                    matched.add(f.id)
        return matched

    def resolve(self, text_normalized: str) -> list[tuple[int, int]]:
        """Résout une adresse normalisée : liste de (structure_id, form_id).

        Pour chaque structure, la première forme par `id` qui matche l'emporte.
        """
        matched_ids = self._matched_form_ids(text_normalized)
        if not matched_ids:
            return []
        matched = [self._forms_by_id[i] for i in matched_ids]
        structs_matched = {f.structure_id for f in matched}
        excluded = {f.structure_id for f in matched if f.is_excluding}

        result: list[tuple[int, int]] = []
        seen: set[int] = set()
        for f in sorted(matched, key=lambda f: f.id):
            sid = f.structure_id
            if sid in seen or sid in excluded or f.is_excluding:
                continue
            ctx = f.requires_context_of
            if ctx and not any(cid in structs_matched for cid in ctx):
                continue
            result.append((sid, f.id))
            seen.add(sid)
        return result


# ─── Run ─────────────────────────────────────────────────────────


def run_resolution(
    conn: Connection,
    queries: AddressResolutionQueries,
    perimeter_ids: set[int],
    logger: logging.Logger,
) -> tuple[int, int, int]:
    """Recalcul complet idempotent des affiliations. `conn` nécessaire pour commit batch.

    Retourne `(adresses traitées, adresses in_perimeter, affiliations détectées)`.
    """
    logger.info("Chargement des structures et formes...")
    forms = queries.load_name_forms(conn)
    logger.info(f"  {len(forms)} formes chargées")
    matcher = AddressMatcher(forms)
    logger.info(f"  {len(perimeter_ids)} structures dans le périmètre")

    return process_addresses(conn, queries, matcher, perimeter_ids, logger)


def process_addresses(
    conn: Connection,
    queries: AddressResolutionQueries,
    matcher: AddressMatcher,
    perimeter: set[int],
    logger: logging.Logger,
    *,
    chunk_size: int = CHUNK_SIZE,
) -> tuple[int, int, int]:
    """Résout toutes les adresses par tranches (keyset) : matching mémoire + écritures en bloc.

    Chaque tranche est lue (`normalized_text`, déjà normalisé en base — aucun recalcul), matchée en mémoire, puis synchronisée en trois requêtes ensemblistes (delete obsolètes / unflag / upsert idempotent des détections) avant commit. Seules les détections qui changent sont écrites ; mémoire et allers-retours SQL bornés par `chunk_size`.
    """
    t_start = time.perf_counter()
    processed = 0
    in_perimeter_count = 0
    affil_count = 0
    removed_count = 0
    after_id = 0

    while True:
        rows = queries.fetch_addresses_chunk(conn, after_id=after_id, limit=chunk_size)
        if not rows:
            break
        after_id = rows[-1][0]  # tranche triée par id

        addr_ids: list[int] = []
        detections: list[tuple[int, int, int]] = []
        kept_pairs: list[tuple[int, int]] = []
        for addr_id, normalized_text in rows:
            addr_ids.append(addr_id)
            matches = matcher.resolve(normalized_text)
            if any(sid in perimeter for sid, _ in matches):
                in_perimeter_count += 1
            for structure_id, form_id in matches:
                detections.append((addr_id, structure_id, form_id))
                kept_pairs.append((addr_id, structure_id))
                affil_count += 1

        removed_count += queries.delete_obsolete_detections_bulk(conn, addr_ids, kept_pairs)
        queries.unflag_obsolete_detections_bulk(conn, addr_ids, kept_pairs)
        queries.upsert_detected_structures_bulk(conn, detections)
        conn.commit()

        processed += len(rows)
        elapsed = time.perf_counter() - t_start
        logger.info(
            f"  {processed} traitées "
            f"({in_perimeter_count} in_perimeter, {affil_count} affiliations, "
            f"{removed_count} obsolètes supprimés) "
            f"— {processed / elapsed:.0f} addr/s"
        )

    elapsed = time.perf_counter() - t_start
    if processed > 0:
        logger.info(f"\n=== Terminé en {elapsed:.1f}s ===")
        logger.info(f"  Adresses traitées    : {processed}")
        logger.info(
            f"  in_perimeter         : {in_perimeter_count} "
            f"({100 * in_perimeter_count / processed:.1f}%)"
        )
        logger.info(f"  Affiliations créées  : {affil_count}")
        logger.info(f"  Obsolètes supprimés  : {removed_count}")

    return processed, in_perimeter_count, affil_count
