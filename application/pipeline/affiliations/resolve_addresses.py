"""
Résolution des adresses : identification UCA + rattachement structures.

Lit les formes de noms depuis la table structure_name_forms,
et enregistre dans address_structures avec matched_form_id pour
la traçabilité (boucle de rétroaction).

L'orchestration dépend du port `AddressResolutionQueries` ; le point
d'entrée CLI est dans
`interfaces/cli/pipeline/resolve_addresses.py` (composition root).

Schéma v2 :
  - address_structures (address_id, structure_id, matched_form_id, is_confirmed)
  - matched_form_id IS NOT NULL = détection auto
  - matched_form_id IS NULL + is_confirmed = assignation manuelle
"""

import logging
import time

import ahocorasick
from sqlalchemy import Connection

from application.ports.pipeline.address_resolution import (
    AddressResolutionQueries,
    StructureNameForm,
)

BATCH_SIZE = 1000


# ─── Matching ────────────────────────────────────────────────────


class AddressMatcher:
    """Matche les formes de structures dans une adresse via un automate Aho-Corasick.

    L'automate, construit une fois sur les 453 formes, détecte en un seul
    passage par adresse toutes les formes présentes (coût indépendant du
    nombre de formes), là où une recherche forme par forme relisait chaque
    adresse autant de fois qu'elle contenait de formes.

    Une forme matche si son `form_text` est présent comme sous-chaîne ; les
    formes `is_word_boundary` ou de longueur <= 6 exigent en plus un mot entier
    (caractères adjacents hors [a-z0-9]). Les formes excluantes retirent leur
    structure des résultats ; les formes à contexte (`requires_context_of`)
    n'aboutissent que si une forme d'une des structures de contexte matche aussi.
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
                if f.is_word_boundary or len(f.form_text) <= 6:
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
    *,
    mode: str = "full",
    reset: bool = False,
    rerun: bool = False,
) -> None:
    """Exécute le pipeline de résolution. `conn` nécessaire pour commit batch."""
    if reset or rerun:
        affils = queries.reset_auto_detected(conn)
        queries.reset_all_resolved_at(conn)
        conn.commit()
        logger.info(f"Reset : {affils} affiliations auto supprimées")
        if reset and not rerun:
            return

    logger.info("Chargement des structures et formes...")
    forms = queries.load_name_forms(conn)
    logger.info(f"  {len(forms)} formes chargées")
    matcher = AddressMatcher(forms)
    logger.info(f"  {len(perimeter_ids)} structures dans le périmètre")

    incremental = mode == "daily"
    if incremental:
        logger.info("Mode incrémental : adresses non résolues uniquement")
    rows = queries.fetch_addresses_to_resolve(conn, incremental=incremental)
    total = len(rows)
    logger.info(f"  {total} adresses à résoudre")

    if total > 0:
        process_addresses(conn, queries, rows, matcher, perimeter_ids, logger)


def process_addresses(
    conn: Connection,
    queries: AddressResolutionQueries,
    rows: list[tuple[int, str]],
    matcher: AddressMatcher,
    perimeter: set[int],
    logger: logging.Logger,
) -> tuple[int, int]:
    """Traite une liste d'adresses : détection + affiliations.

    `rows` fournit `(id, normalized_text)` : le texte est déjà normalisé en
    base (colonne `addresses.normalized_text`), aucun recalcul ici.
    """
    t_start = time.perf_counter()
    total = len(rows)
    processed = 0
    uca_count = 0
    affil_count = 0
    removed_count = 0

    for addr_id, normalized_text in rows:
        matches = matcher.resolve(normalized_text)

        in_perimeter = any(sid in perimeter for sid, _ in matches)
        if in_perimeter:
            uca_count += 1

        detected_structure_ids = [sid for sid, _ in matches]

        removed_count += queries.delete_obsolete_detections(conn, addr_id, detected_structure_ids)
        queries.unflag_obsolete_detections(conn, addr_id, detected_structure_ids)

        for structure_id, form_id in matches:
            affil_count += 1
            queries.upsert_detected_structure(conn, addr_id, structure_id, form_id)

        queries.mark_address_resolved(conn, addr_id)
        processed += 1
        if processed % BATCH_SIZE == 0:
            conn.commit()
            elapsed = time.perf_counter() - t_start
            rate = processed / elapsed
            logger.info(
                f"  {processed}/{total} "
                f"({uca_count} UCA, {affil_count} affiliations, "
                f"{removed_count} obsolètes supprimés) "
                f"— {rate:.0f} addr/s"
            )

    conn.commit()

    elapsed = time.perf_counter() - t_start
    if total > 0:
        logger.info(f"\n=== Terminé en {elapsed:.1f}s ===")
        logger.info(f"  Adresses traitées    : {processed}")
        logger.info(f"  UCA                  : {uca_count} ({100 * uca_count / processed:.1f}%)")
        logger.info(f"  Affiliations créées  : {affil_count}")
        logger.info(f"  Obsolètes supprimés  : {removed_count}")

    return uca_count, affil_count
