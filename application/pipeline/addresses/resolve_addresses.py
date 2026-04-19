"""
Résolution des adresses : identification UCA + rattachement structures.

Lit les formes de noms depuis la table structure_name_forms,
et enregistre dans address_structures avec matched_form_id pour
la traçabilité (boucle de rétroaction).

Schéma v2 :
  - address_structures (address_id, structure_id, matched_form_id, is_confirmed)
  - matched_form_id IS NOT NULL = détection auto
  - matched_form_id IS NULL + is_confirmed = assignation manuelle

Usage:
    python resolve_addresses.py              # résoudre les adresses non traitées
    python resolve_addresses.py --reset      # remettre à zéro (auto uniquement)
    python resolve_addresses.py --rerun      # reset auto + relancer tout
    python resolve_addresses.py --stats      # stats
"""

import argparse
import os
import re
import time

from domain.normalize import normalize_text as normalize
from infrastructure.db.connection import get_connection
from infrastructure.log import setup_logger
from infrastructure.perimeter import get_persons_structure_ids

logger = setup_logger("resolve_addresses", os.path.join(os.path.dirname(__file__), "logs"))

BATCH_SIZE = 1000


# ─── Chargement des données ──────────────────────────────────────


def load_forms(cur):
    """Charge toutes les formes depuis structure_name_forms."""
    cur.execute("""
        SELECT nf.id, nf.structure_id, nf.form_text,
               nf.is_word_boundary, nf.requires_context_of,
               nf.is_excluding,
               s.code AS struct_code, s.structure_type::text AS struct_type
        FROM structure_name_forms nf
        JOIN structures s ON s.id = nf.structure_id
        ORDER BY nf.id
    """)
    columns = [desc[0] for desc in cur.description]
    forms = [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]
    logger.info(f"  {len(forms)} formes chargées")
    return forms


def load_perimeter(cur):
    """Construit l'ensemble des structure_ids dans le périmètre."""
    return get_persons_structure_ids(cur)


# ─── Matching ────────────────────────────────────────────────────


def match_form_in_text(form, text_normalized):
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


def build_forms_by_structure(forms):
    """Index : structure_id → [forms]."""
    idx: dict[int, list] = {}
    for f in forms:
        idx.setdefault(f["structure_id"], []).append(f)
    return idx


def has_form_match_for_structure(struct_id, text_normalized, forms_by_structure):
    """Vérifie si au moins une forme de la structure donnée matche."""
    for f in forms_by_structure.get(struct_id, []):
        if match_form_in_text(f, text_normalized):
            return True
    return False


def resolve_address(text_normalized, forms, forms_by_structure):
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


# ─── Main ────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Supprime les affiliations auto")
    parser.add_argument(
        "--rerun", action="store_true", help="Reset auto puis relance la résolution complète"
    )
    parser.add_argument(
        "--mode",
        choices=["full", "weekly", "monthly", "daily"],
        default="full",
        help="Mode d'exécution (daily = incrémental)",
    )
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    if args.reset or args.rerun:
        # Supprimer les affiliations auto-détectées (matched_form_id IS NOT NULL)
        cur.execute("DELETE FROM address_structures WHERE matched_form_id IS NOT NULL")
        affils = cur.rowcount
        # Remettre resolved_at à NULL pour forcer le recalcul
        cur.execute("UPDATE addresses SET resolved_at = NULL")
        conn.commit()
        logger.info(f"Reset : {affils} affiliations auto supprimées")
        if args.reset and not args.rerun:
            conn.close()
            return

    # Charger les données
    logger.info("Chargement des structures et formes...")
    forms = load_forms(cur)
    forms_by_structure = build_forms_by_structure(forms)
    perimeter = load_perimeter(cur)
    logger.info(f"  {len(perimeter)} structures dans le périmètre")

    # En mode daily : uniquement les adresses jamais résolues
    if args.mode == "daily":
        cur.execute("""
            SELECT a.id, a.raw_text FROM addresses a
            WHERE a.resolved_at IS NULL
            ORDER BY a.id
        """)
        logger.info("Mode incrémental : adresses non résolues uniquement")
    else:
        cur.execute("""
            SELECT a.id, a.raw_text FROM addresses a
            ORDER BY a.id
        """)

    rows = cur.fetchall()
    total = len(rows)
    logger.info(f"  {total} adresses à résoudre")

    if total > 0:
        process_addresses(cur, conn, rows, forms, forms_by_structure, perimeter)

    conn.close()


def process_addresses(cur, conn, rows, forms, forms_by_structure, perimeter):
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

        detected_structure_ids = {sid for sid, _ in matches}

        # Liens auto-détectés obsolètes (structure plus détectée par le script)
        if detected_structure_ids:
            obsolete_condition = """
                address_id = %s
                AND matched_form_id IS NOT NULL
                AND structure_id != ALL(%s)
            """
            obsolete_params: tuple = (addr_id, list(detected_structure_ids))
        else:
            obsolete_condition = """
                address_id = %s
                AND matched_form_id IS NOT NULL
            """
            obsolete_params = (addr_id,)

        # Non confirmés : supprimer
        cur.execute(
            f"""
            DELETE FROM address_structures
            WHERE {obsolete_condition} AND is_confirmed IS NULL
        """,
            obsolete_params,
        )
        removed_count += cur.rowcount

        # Confirmés/rejetés : retirer le flag de détection auto
        cur.execute(
            f"""
            UPDATE address_structures
            SET matched_form_id = NULL
            WHERE {obsolete_condition} AND is_confirmed IS NOT NULL
        """,
            obsolete_params,
        )

        # Insérer/mettre à jour les structures détectées
        for structure_id, form_id in matches:
            affil_count += 1
            cur.execute(
                """
                INSERT INTO address_structures
                    (address_id, structure_id, matched_form_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (address_id, structure_id)
                    DO UPDATE SET matched_form_id = EXCLUDED.matched_form_id
            """,
                (addr_id, structure_id, form_id),
            )

        cur.execute("UPDATE addresses SET resolved_at = now() WHERE id = %s", (addr_id,))
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


if __name__ == "__main__":
    main()
