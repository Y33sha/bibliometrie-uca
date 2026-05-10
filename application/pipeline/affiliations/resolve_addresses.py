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

import re
import time
from typing import Any

from application.ports.address_resolution import AddressResolutionQueries
from domain.normalize import normalize_text as normalize

BATCH_SIZE = 1000


# ─── Matching ────────────────────────────────────────────────────


def match_form_in_text(form: Any, text_normalized: Any) -> Any:
    """Vérifie si une forme matche dans le texte normalisé.

    Si is_word_boundary ou forme <= 6 chars : mot entier (word boundary).
    Sinon : sous-chaîne.
    """
    form_text = form["form_text"]
    if not form_text:
        return False

    if form.get("is_word_boundary") or len(form_text) <= 6:
        pattern = r"(?<![a-z0-9])" + re.escape(form_text) + r"(?![a-z0-9])"
        return bool(re.search(pattern, text_normalized))
    else:
        return form_text in text_normalized


def build_forms_by_structure(forms: Any) -> Any:
    """Index : structure_id → [forms]."""
    idx: dict[int, list] = {}
    for f in forms:
        idx.setdefault(f["structure_id"], []).append(f)
    return idx


def has_form_match_for_structure(
    struct_id: Any, text_normalized: Any, forms_by_structure: Any
) -> Any:
    """Vérifie si au moins une forme de la structure donnée matche."""
    for f in forms_by_structure.get(struct_id, []):
        if match_form_in_text(f, text_normalized):
            return True
    return False


def resolve_address(text_normalized: Any, forms: Any, forms_by_structure: Any) -> Any:
    """Résout une adresse : trouve toutes les structures identifiées.

    Les formes excluantes (is_excluding=True) retirent la structure
    des résultats si elles matchent.

    Retourne une liste de (structure_id, form_id).
    """
    matches = []
    seen_structures = set()
    excluded_structures = set()

    # Passe 1 : détecter les exclusions
    for f in forms:
        if f.get("is_excluding") and match_form_in_text(f, text_normalized):
            excluded_structures.add(f["structure_id"])

    # Passe 2 : matcher les formes normales
    for f in forms:
        sid = f["structure_id"]
        if sid in seen_structures or sid in excluded_structures:
            continue
        if f.get("is_excluding"):
            continue

        if not match_form_in_text(f, text_normalized):
            continue

        # Vérifier le contexte (requires_context_of = integer[])
        ctx = f["requires_context_of"]
        if ctx:
            context_satisfied = any(
                has_form_match_for_structure(cid, text_normalized, forms_by_structure)
                for cid in ctx
            )
            if not context_satisfied:
                continue

        matches.append((sid, f["id"]))
        seen_structures.add(sid)

    return matches


# ─── Run ─────────────────────────────────────────────────────────


def run_resolution(
    conn: Any,
    queries: AddressResolutionQueries,
    perimeter_ids: set[int],
    logger: Any,
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
    forms_by_structure = build_forms_by_structure(forms)
    logger.info(f"  {len(perimeter_ids)} structures dans le périmètre")

    incremental = mode == "daily"
    if incremental:
        logger.info("Mode incrémental : adresses non résolues uniquement")
    rows = queries.fetch_addresses_to_resolve(conn, incremental=incremental)
    total = len(rows)
    logger.info(f"  {total} adresses à résoudre")

    if total > 0:
        process_addresses(conn, queries, rows, forms, forms_by_structure, perimeter_ids, logger)


def process_addresses(
    conn: Any,
    queries: AddressResolutionQueries,
    rows: Any,
    forms: Any,
    forms_by_structure: Any,
    perimeter: Any,
    logger: Any,
) -> tuple[int, int]:
    """Traite une liste d'adresses : détection + affiliations."""
    t_start = time.perf_counter()
    total = len(rows)
    processed = 0
    uca_count = 0
    affil_count = 0
    removed_count = 0

    for addr_id, raw_text in rows:
        text_norm = normalize(raw_text)
        matches = resolve_address(text_norm, forms, forms_by_structure)

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
