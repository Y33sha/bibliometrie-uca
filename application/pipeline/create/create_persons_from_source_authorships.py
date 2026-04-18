"""
Crée des entités Personnes à partir des authorships sources UCA non rattachées.

Algorithme en 4 étapes + 1 étape complémentaire :

  Étape 0 : Comptes HAL déjà rattachés
    source_persons HAL avec hal_person_id ET person_id → propagation aux nouvelles
    authorships du même compte. Les comptes non rattachés sont laissés
    aux étapes suivantes (matching par nom, ORCID, position).

  Étape 1 : Cross-source
    Pour chaque authorship sans person_id, chercher sur la même publication
    (même position) une authorship d'une autre source qui a un person_id.
    Si le nom est compatible → rattacher à cette personne.

  Étape 2 : ORCID connu
    Si l'authorship a un ORCID déjà présent en base (status != rejected)
    et mappé à une personne → rattacher à cette personne.
    L'ORCID ne prime pas sur le cross-source (risque d'ORCID erroné
    dans OpenAlex/WoS supérieur au risque d'homonymie en cross-source).

  Étape 3 : Lookup person_name_forms
    Normaliser le nom de l'auteur et chercher dans person_name_forms.
    - Mappé à 1 personne → rattacher
    - Mappé à >1 personnes → orphelin (traitement manuel)
    - Forme inconnue → créer nouvelle personne

  Étape 4 : Presonnes liées aux thèses (directeurs, rapporteurs, jury)
    Les rôles non-auteur des thèses sont hors périmètre (in_perimeter=false: pas de signatures ni de structure_ids) et ne passent pas par les étapes 0-3. Si leur source_author a un IdRef correspondant à une personne connue, on rattache sans modifier in_perimeter ni créer de personne.

Usage:
    python create_persons_from_source_authorships.py              # exécuter
    python create_persons_from_source_authorships.py --dry-run    # dry-run
"""

import argparse
import os
from collections import defaultdict

from psycopg2.extras import RealDictCursor

from infrastructure.db.connection import get_connection
from application.persons import (
    add_identifiers_from_authorships as add_identifiers,
)
from application.persons import (
    add_name_form,
    create_person,
)
from application.persons import (
    link_authorships as link_to_person,
)
from infrastructure.log import setup_logger
from domain.names import names_compatible, parse_raw_author_name
from domain.normalize import normalize_name

logger = setup_logger("create_persons", os.path.join(os.path.dirname(__file__), "logs"))


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def get_all_unlinked_authorships(cur):
    """Récupère toutes les authorships UCA sans person_id, toutes sources."""
    # HAL
    cur.execute("""
        SELECT sa_auth.id AS authorship_id, 'hal' AS source,
               sa_auth.raw_author_name AS full_name, sa.last_name, sa.first_name,
               sa.orcid,
               sa.source_ids->>'idhal' AS idhal,
               sa.idref,
               sa.id AS source_person_id,
               ((sa.source_ids->>'hal_person_id') IS NOT NULL) AS has_hal_person_id,
               (sa.source_ids->>'hal_person_id')::int AS hal_person_id,
               sd.publication_id,
               sa_auth.author_position
        FROM source_authorships sa_auth
        JOIN source_persons sa ON sa.id = sa_auth.source_person_id
        JOIN source_publications sd ON sd.id = sa_auth.source_publication_id
        JOIN v_active_publications vap ON vap.id = sd.publication_id
        WHERE sa_auth.source = 'hal'
          AND sa_auth.person_id IS NULL
          AND sa_auth.in_perimeter = TRUE
          AND sd.publication_id IS NOT NULL
    """)
    hal_rows = cur.fetchall()

    # OpenAlex
    # L'ORCID n'est remonté que si raw_author_name est compatible avec
    # le display_name de l'entité auteur OA (l'algo OA fusionne parfois
    # des personnes différentes, attribuant un ORCID erroné).
    cur.execute("""
        SELECT sa_auth.id AS authorship_id, 'openalex' AS source,
               sa_auth.raw_author_name AS full_name,
               NULL::text AS last_name, NULL::text AS first_name,
               sa.orcid AS oa_orcid, sa.full_name AS oa_full_name,
               NULL::text AS idhal,
               NULL::int AS source_person_id,
               FALSE AS has_hal_person_id,
               NULL::int AS hal_person_id,
               sd.publication_id,
               sa_auth.author_position
        FROM source_authorships sa_auth
        JOIN source_persons sa ON sa.id = sa_auth.source_person_id
        JOIN source_publications sd ON sd.id = sa_auth.source_publication_id
        JOIN v_active_publications vap ON vap.id = sd.publication_id
        WHERE sa_auth.source = 'openalex'
          AND sa_auth.person_id IS NULL
          AND sa_auth.in_perimeter = TRUE
          AND sa_auth.raw_author_name IS NOT NULL
          AND sd.publication_id IS NOT NULL
    """)
    oa_rows = cur.fetchall()

    # WoS
    cur.execute("""
        SELECT sa_auth.id AS authorship_id, 'wos' AS source,
               sa_auth.raw_author_name AS full_name, sa.last_name, sa.first_name,
               sa.orcid, NULL::text AS idhal,
               NULL::int AS source_person_id,
               FALSE AS has_hal_person_id,
               NULL::int AS hal_person_id,
               sd.publication_id,
               sa_auth.author_position
        FROM source_authorships sa_auth
        JOIN source_persons sa ON sa.id = sa_auth.source_person_id
        JOIN source_publications sd ON sd.id = sa_auth.source_publication_id
        JOIN v_active_publications vap ON vap.id = sd.publication_id
        WHERE sa_auth.source = 'wos'
          AND sa_auth.person_id IS NULL
          AND sa_auth.in_perimeter = TRUE
          AND sd.publication_id IS NOT NULL
    """)
    wos_rows = cur.fetchall()

    # ScanR
    cur.execute("""
        SELECT sa_auth.id AS authorship_id, 'scanr' AS source,
               sa_auth.raw_author_name AS full_name, sa.last_name, sa.first_name,
               sa.orcid, NULL::text AS idhal, sa.idref,
               NULL::int AS source_person_id,
               FALSE AS has_hal_person_id,
               NULL::int AS hal_person_id,
               sd.publication_id,
               sa_auth.author_position
        FROM source_authorships sa_auth
        JOIN source_persons sa ON sa.id = sa_auth.source_person_id
        JOIN source_publications sd ON sd.id = sa_auth.source_publication_id
        JOIN v_active_publications vap ON vap.id = sd.publication_id
        WHERE sa_auth.source = 'scanr'
          AND sa_auth.person_id IS NULL
          AND sa_auth.in_perimeter = TRUE
          AND sd.publication_id IS NOT NULL
    """)
    scanr_rows = cur.fetchall()

    # theses.fr (même structure que ScanR : idref comme clé)
    # Les rôles non-auteur (directeur, rapporteur, jury) ne créent pas de personne.
    cur.execute("""
        SELECT sa_auth.id AS authorship_id, 'theses' AS source,
               sa_auth.raw_author_name AS full_name, sa.last_name, sa.first_name,
               sa.orcid, NULL::text AS idhal, sa.idref,
               NULL::int AS source_person_id,
               FALSE AS has_hal_person_id,
               NULL::int AS hal_person_id,
               sd.publication_id,
               sa_auth.author_position,
               sa_auth.roles
        FROM source_authorships sa_auth
        JOIN source_persons sa ON sa.id = sa_auth.source_person_id
        JOIN source_publications sd ON sd.id = sa_auth.source_publication_id
        JOIN v_active_publications vap ON vap.id = sd.publication_id
        WHERE sa_auth.source = 'theses'
          AND sa_auth.person_id IS NULL
          AND sa_auth.in_perimeter = TRUE
          AND sd.publication_id IS NOT NULL
    """)
    theses_rows = cur.fetchall()

    # Enrichir avec last_name/first_name parsés + filtrage ORCID OA
    all_rows = []
    for r in hal_rows + oa_rows + wos_rows + scanr_rows + theses_rows:
        r = dict(r)
        if not r.get("last_name"):
            r["last_name"], r["first_name"] = parse_raw_author_name(r["full_name"])
        r["last_norm"] = normalize_name(r["last_name"])
        r["first_norm"] = normalize_name(r["first_name"])

        # Les rôles non-auteur des thèses ne créent pas de personne
        roles = r.get("roles") or []
        r["allow_create"] = not (r["source"] == "theses" and "author" not in roles)

        # ORCID OpenAlex : ne garder que si le nom de l'entité auteur OA
        # est compatible avec le raw_author_name de l'authorship
        if r.get("oa_orcid"):
            oa_ln, oa_fn = parse_raw_author_name(r.get("oa_full_name", ""))
            if names_compatible(
                r["last_norm"], r["first_norm"], normalize_name(oa_ln), normalize_name(oa_fn)
            ):
                r["orcid"] = r["oa_orcid"]
            else:
                r["orcid"] = None
            r.pop("oa_orcid", None)
            r.pop("oa_full_name", None)

        all_rows.append(r)

    return all_rows


def load_linked_authorships_by_pub(cur):
    """Charge les authorships déjà rattachées à une personne, indexées par
    (publication_id, author_position) pour le cross-source matching.

    Retourne : {(pub_id, position): [(person_id, last_norm, first_norm, source), ...]}
    """
    index = defaultdict(list)

    # Sources avec noms structurés dans source_persons (tout sauf OpenAlex)
    from domain.sources import SOURCES_WITH_STRUCTURED_NAMES_SQL

    cur.execute(f"""
        SELECT sa_auth.person_id, sa_auth.author_position,
               sd.publication_id,
               sa.last_name, sa.first_name, sa_auth.raw_author_name AS full_name,
               sa_auth.source
        FROM source_authorships sa_auth
        JOIN source_persons sa ON sa.id = sa_auth.source_person_id
        JOIN source_publications sd ON sd.id = sa_auth.source_publication_id
        WHERE sa_auth.source IN {SOURCES_WITH_STRUCTURED_NAMES_SQL}
          AND sa_auth.person_id IS NOT NULL
          AND sd.publication_id IS NOT NULL
    """)
    for r in cur.fetchall():
        ln = normalize_name(r["last_name"] or "")
        fn = normalize_name(r["first_name"] or "")
        if not ln and r["full_name"]:
            last, first = parse_raw_author_name(r["full_name"])
            ln, fn = normalize_name(last), normalize_name(first)
        index[(r["publication_id"], r["author_position"])].append(
            (r["person_id"], ln, fn, r["source"])
        )

    # OpenAlex : nom depuis raw_author_name
    cur.execute("""
        SELECT sa_auth.person_id, sa_auth.author_position,
               sd.publication_id,
               sa_auth.raw_author_name AS full_name,
               'openalex' AS source
        FROM source_authorships sa_auth
        JOIN source_publications sd ON sd.id = sa_auth.source_publication_id
        WHERE sa_auth.source = 'openalex'
          AND sa_auth.person_id IS NOT NULL
          AND sd.publication_id IS NOT NULL
    """)
    for r in cur.fetchall():
        last, first = parse_raw_author_name(r["full_name"])
        ln, fn = normalize_name(last), normalize_name(first)
        index[(r["publication_id"], r["author_position"])].append(
            (r["person_id"], ln, fn, r["source"])
        )

    return index


def load_name_form_map(cur):
    """Charge person_name_forms.

    Retourne : {name_form: [person_id, ...]}
    """
    cur.execute("SELECT name_form, person_ids FROM person_name_forms")
    return {r["name_form"]: r["person_ids"] for r in cur.fetchall()}


# ---------------------------------------------------------------------------
# Étape 0 : Comptes HAL
# ---------------------------------------------------------------------------


def step0_hal_accounts(cur, all_authorships, linked_ids, dry_run):
    """Propagation des comptes HAL déjà rattachés à une personne.

    Seuls les source_persons HAL avec hal_person_id ET person_id sont traités.
    Les comptes HAL non encore rattachés sont laissés aux passes suivantes
    (matching par nom, ORCID, position) pour éviter de créer des doublons.
    """
    by_hal_pid = defaultdict(list)
    for a in all_authorships:
        if a["source"] == "hal" and a["has_hal_person_id"]:
            by_hal_pid[a["hal_person_id"]].append(a)

    # source_persons HAL déjà liés à une personne
    cur.execute("""
        SELECT (sa.source_ids->>'hal_person_id')::int AS hal_person_id, sa.person_id
        FROM source_persons sa
        WHERE sa.source = 'hal'
          AND (sa.source_ids->>'hal_person_id') IS NOT NULL
          AND sa.person_id IS NOT NULL
    """)
    hal_person_map = {r["hal_person_id"]: r["person_id"] for r in cur.fetchall()}

    linked = 0
    skipped = 0
    for hal_pid, group in by_hal_pid.items():
        existing_pid = hal_person_map.get(hal_pid)
        if existing_pid:
            if not dry_run:
                link_to_person(cur, existing_pid, group)
                add_identifiers(cur, existing_pid, group)
            linked += len(group)
            for a in group:
                linked_ids.add((a["source"], a["authorship_id"]))
        else:
            # Compte HAL non rattaché → laisser aux passes suivantes
            skipped += len(group)

    logger.info(
        f"  {linked} authorships rattachées, {skipped} ignorées (comptes HAL non rattachés)"
    )
    return linked


# ---------------------------------------------------------------------------
# Étape 1 : Cross-source (même publication + même position)
# ---------------------------------------------------------------------------


def step1_cross_source(cur, all_authorships, linked_ids, linked_index, dry_run):
    """Pour chaque authorship sans person_id, chercher sur la même publication
    (même position) une authorship d'une autre source rattachée à une personne.
    """
    linked = 0
    for a in all_authorships:
        if (a["source"], a["authorship_id"]) in linked_ids:
            continue

        pub_id = a["publication_id"]
        position = a["author_position"]
        if pub_id is None or position is None:
            continue

        candidates = linked_index.get((pub_id, position), [])
        if not candidates:
            continue

        # Chercher un candidat d'une autre source avec nom compatible
        matched_pid = None
        for pid, ln, fn, src in candidates:
            if src == a["source"]:
                continue  # même source, pas utile
            if names_compatible(a["last_norm"], a["first_norm"], ln, fn):
                if matched_pid is not None and matched_pid != pid:
                    matched_pid = None  # ambiguïté
                    break
                matched_pid = pid

        if matched_pid:
            if not dry_run:
                link_to_person(cur, matched_pid, [a])
                add_name_form(cur, matched_pid, a["full_name"])
                add_identifiers(cur, matched_pid, [a])
            linked_ids.add((a["source"], a["authorship_id"]))
            # Mettre à jour l'index pour les passes suivantes
            ln, fn = a["last_norm"], a["first_norm"]
            linked_index[(pub_id, position)].append((matched_pid, ln, fn, a["source"]))
            linked += 1

    logger.info(f"  {linked} authorships rattachées par cross-source")
    return linked


# ---------------------------------------------------------------------------
# Étape 1b : IdRef connu
# ---------------------------------------------------------------------------


def load_idref_person_map(cur):
    """Charge les IdRef déjà mappés à une personne (status != rejected).

    Retourne : {idref: person_id}
    """
    cur.execute("""
        SELECT id_value, person_id
        FROM person_identifiers
        WHERE id_type = 'idref'
          AND status != 'rejected'
    """)
    return {r["id_value"]: r["person_id"] for r in cur.fetchall()}


def step1b_idref(cur, all_authorships, linked_ids, dry_run):
    """Si l'authorship a un IdRef déjà connu en base (non rejeté),
    rattacher à la personne correspondante.
    """
    idref_map = load_idref_person_map(cur)
    linked = 0

    for a in all_authorships:
        if (a["source"], a["authorship_id"]) in linked_ids:
            continue

        idref = a.get("idref")
        if not idref:
            continue

        pid = idref_map.get(idref)
        if pid:
            if not dry_run:
                link_to_person(cur, pid, [a])
                add_name_form(cur, pid, a["full_name"])
                add_identifiers(cur, pid, [a])
            linked_ids.add((a["source"], a["authorship_id"]))
            linked += 1

    logger.info(f"  {linked} authorships rattachées par IdRef connu")
    return linked


# ---------------------------------------------------------------------------
# Étape 2 : ORCID connu
# ---------------------------------------------------------------------------


def load_orcid_person_map(cur):
    """Charge les ORCID déjà mappés à une personne (status != rejected).

    Retourne : {orcid: person_id}
    """
    cur.execute("""
        SELECT id_value, person_id
        FROM person_identifiers
        WHERE id_type = 'orcid'
          AND status != 'rejected'
    """)
    return {r["id_value"]: r["person_id"] for r in cur.fetchall()}


def step2_orcid(cur, all_authorships, linked_ids, dry_run):
    """Si l'authorship a un ORCID déjà connu en base (non rejeté),
    rattacher à la personne correspondante.
    """
    orcid_map = load_orcid_person_map(cur)
    linked = 0

    for a in all_authorships:
        if (a["source"], a["authorship_id"]) in linked_ids:
            continue

        orcid = a.get("orcid")
        if not orcid:
            continue

        pid = orcid_map.get(orcid)
        if pid:
            if not dry_run:
                link_to_person(cur, pid, [a])
                add_name_form(cur, pid, a["full_name"])
                add_identifiers(cur, pid, [a])
            linked_ids.add((a["source"], a["authorship_id"]))
            linked += 1

    logger.info(f"  {linked} authorships rattachées par ORCID connu")
    return linked


# ---------------------------------------------------------------------------
# Étape 3 : Lookup person_name_forms
# ---------------------------------------------------------------------------


def step3_name_forms(cur, all_authorships, linked_ids, name_form_map, dry_run):
    """Lookup par author_name_normalized dans person_name_forms.

    - Mappé à 1 personne → rattacher
    - Mappé à >1 personnes → orphelin (traitement manuel)
    - Forme inconnue → créer nouvelle personne
    """
    linked = 0
    created = 0
    ambiguous = 0

    for a in all_authorships:
        if (a["source"], a["authorship_id"]) in linked_ids:
            continue

        ln, fn = a["last_norm"], a["first_norm"]
        if not ln:
            continue

        # Chercher dans les name_forms (essayer les deux ordres)
        person_ids = None
        forms_to_try = [f for f in [f"{fn} {ln}".strip(), f"{ln} {fn}".strip(), ln] if f]
        for form in forms_to_try:
            if form in name_form_map:
                person_ids = name_form_map[form]
                break

        if person_ids is not None:
            if len(person_ids) == 1:
                # Unique → rattacher
                pid = person_ids[0]
                if not dry_run:
                    link_to_person(cur, pid, [a])
                    add_name_form(cur, pid, a["full_name"])
                linked_ids.add((a["source"], a["authorship_id"]))
                linked += 1
            else:
                # Ambigu → orphelin
                ambiguous += 1
        else:
            # Forme inconnue → créer personne (sauf si création interdite)
            if not a.get("allow_create", True):
                ambiguous += 1  # comptabilisé comme orphelin
                continue
            last = a["last_name"] or a["full_name"] or "?"
            first = a["first_name"] or ""
            if not dry_run:
                pid = create_person(cur, last, first)
                link_to_person(cur, pid, [a])
                add_identifiers(cur, pid, [a])
                add_name_form(cur, pid, a["full_name"])
                # Enregistrer la nouvelle forme pour les authorships suivantes
                for form in [f"{fn} {ln}".strip(), f"{ln} {fn}".strip()]:
                    if form:
                        name_form_map[form] = [pid]
            else:
                for form in [f"{fn} {ln}".strip(), f"{ln} {fn}".strip()]:
                    if form:
                        name_form_map[form] = [-1]  # placeholder dry-run

            linked_ids.add((a["source"], a["authorship_id"]))
            created += 1

    logger.info(
        f"  {created} personnes créées, {linked} rattachées, {ambiguous} ambiguës (orphelines)"
    )
    return created, linked, ambiguous


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(dry_run=False):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    all_authorships = get_all_unlinked_authorships(cur)
    logger.info(f"{len(all_authorships)} authorships UCA non rattachées (toutes sources)")

    if not all_authorships:
        logger.info("Rien à faire.")
        conn.close()
        return

    linked_ids = set()  # (source, authorship_id)

    # ── Étape 0 : Comptes HAL ──
    logger.info("\n--- Étape 0 : comptes HAL ---")
    s0 = step0_hal_accounts(cur, all_authorships, linked_ids, dry_run)

    # ── Étape 1 : Cross-source ──
    logger.info("\n--- Étape 1 : cross-source (même publi + position) ---")
    linked_index = load_linked_authorships_by_pub(cur)
    s1 = step1_cross_source(cur, all_authorships, linked_ids, linked_index, dry_run)

    # ── Étape 1b : IdRef connu ──
    logger.info("\n--- Étape 1b : IdRef connu ---")
    s1b = step1b_idref(cur, all_authorships, linked_ids, dry_run)

    # ── Étape 2 : ORCID connu ──
    logger.info("\n--- Étape 2 : ORCID connu ---")
    s2 = step2_orcid(cur, all_authorships, linked_ids, dry_run)

    # ── Étape 3 : Name forms ──
    logger.info("\n--- Étape 3 : person_name_forms ---")
    name_form_map = load_name_form_map(cur)
    s3_created, s3_linked, s3_ambiguous = step3_name_forms(
        cur, all_authorships, linked_ids, name_form_map, dry_run
    )

    # ── Résumé ──
    total_linked = len(linked_ids)
    unlinked = len(all_authorships) - total_linked

    logger.info("\n=== Résumé ===")
    logger.info(f"  Étape 0 (comptes HAL)    : {s0} rattachées")
    logger.info(f"  Étape 1 (cross-source)   : {s1} rattachées")
    logger.info(f"  Étape 1b (IdRef connu)   : {s1b} rattachées")
    logger.info(f"  Étape 2 (ORCID connu)    : {s2} rattachées")
    logger.info(
        f"  Étape 3 (name_forms)     : {s3_created} créées, {s3_linked} rattachées, {s3_ambiguous} ambiguës"
    )
    logger.info(f"  Non résolues             : {unlinked}")

    if dry_run:
        conn.rollback()
        logger.info("\n  (dry-run — rien n'a été modifié)")
    else:
        conn.commit()
        logger.info("\n  ✓ Appliqué.")
        logger.info("  → Lancer build_authorships.py pour propager in_perimeter/structure_ids")

    cur.close()
    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Crée des personnes à partir des authorships sources UCA"
    )
    parser.add_argument("--dry-run", action="store_true", help="Simuler sans modifier la base")
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
