#!/usr/bin/env python3
"""
Migration des données JSON vers les tables structures / name_forms.

Lit labos.json et config_validation.json, et peuple :
  - structures (UCA, labos, tutelles, partenaires, sites, CHU)
  - structure_relations (tutelles de chaque labo)
  - name_forms (toutes les formes de noms, avec requires_context_of)

Usage:
    cd publisher-stats
    python db/seed_structures.py              # peuple les structures
    python db/seed_structures.py --dry-run    # affiche sans écrire
"""

import argparse
import json
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection


CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")
LABOS_JSON = os.path.join(CONFIG_DIR, "labos.json")
CONFIG_JSON = os.path.join(CONFIG_DIR, "config_validation.json")


def normalize(text):
    if not text:
        return ""
    text = text.lower().strip()
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def make_code(name, acronym=None):
    """Génère un code unique à partir de l'acronyme ou du nom."""
    base = acronym or name
    code = base.lower().strip()
    code = unicodedata.normalize("NFKD", code)
    code = code.encode("ascii", "ignore").decode("ascii")
    code = re.sub(r"[^a-z0-9]", "_", code)
    code = re.sub(r"_+", "_", code).strip("_")
    return code[:50]


def upsert_structure(cur, code, name, acronym, stype, ror_id=None, rnsr_id=None,
                     hal_collection=None, laboratory_id=None):
    """Insère ou met à jour une structure, retourne l'id."""
    cur.execute("""
        INSERT INTO structures (code, name, acronym, type, ror_id, rnsr_id, hal_collection, laboratory_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (code) DO UPDATE SET
            name = EXCLUDED.name,
            acronym = EXCLUDED.acronym,
            type = EXCLUDED.type,
            ror_id = COALESCE(EXCLUDED.ror_id, structures.ror_id),
            rnsr_id = COALESCE(EXCLUDED.rnsr_id, structures.rnsr_id),
            hal_collection = COALESCE(EXCLUDED.hal_collection, structures.hal_collection),
            laboratory_id = COALESCE(EXCLUDED.laboratory_id, structures.laboratory_id)
        RETURNING id
    """, (code, name, acronym, stype, ror_id, rnsr_id, hal_collection, laboratory_id))
    return cur.fetchone()[0]


def upsert_relation(cur, parent_id, child_id, rel_type):
    cur.execute("""
        INSERT INTO structure_relations (parent_id, child_id, relation_type)
        VALUES (%s, %s, %s)
        ON CONFLICT (parent_id, child_id, relation_type) DO NOTHING
    """, (parent_id, child_id, rel_type))


def insert_form(cur, structure_id, form_text, is_regex=False, requires_context_of=None,
                notes=None):
    form_normalized = normalize(form_text)
    ctx_json = json.dumps(requires_context_of) if requires_context_of else None
    cur.execute("""
        INSERT INTO name_forms (structure_id, form_text, form_normalized, is_regex,
                                requires_context_of, notes)
        VALUES (%s, %s, %s, %s, %s::jsonb, %s)
    """, (structure_id, form_text, form_normalized, is_regex, ctx_json, notes))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with open(LABOS_JSON, "r", encoding="utf-8") as f:
        labos_data = json.load(f)
    with open(CONFIG_JSON, "r", encoding="utf-8") as f:
        config = json.load(f)

    conn = get_connection()
    cur = conn.cursor()

    try:
        # ============================================================
        # 1. Structures fondamentales : UCA, sites
        # ============================================================
        print("=== Structures fondamentales ===")

        uca_id = upsert_structure(cur, "uca", "Université Clermont Auvergne", "UCA",
                                  "universite", ror_id="https://ror.org/01a8ajp46")
        print(f"  UCA → id={uca_id}")

        # Sites géographiques
        site_clermont_id = upsert_structure(
            cur, "site_clermont", "Site de Clermont-Ferrand", None, "site")
        print(f"  Site Clermont-Ferrand → id={site_clermont_id}")

        # Formes pour site_clermont
        for form in ["Clermont-Ferrand", "Clermont Ferrand", "Clermont Fd",
                      "Clermont-Fd", "Montpied", "Estaing", "63000", "63100",
                      "63001", "F-63000", "F-63001", "F-63100"]:
            insert_form(cur, site_clermont_id, form)

        site_cezeaux_id = upsert_structure(
            cur, "site_cezeaux", "Campus des Cézeaux", None, "site")
        print(f"  Campus Cézeaux → id={site_cezeaux_id}")
        for form in ["Cezeaux", "Cézeaux", "Les Cézeaux", "les Cezeaux",
                      "Campus Universitaire des Cezeaux", "63170", "63178",
                      "Aubiere", "Aubière"]:
            insert_form(cur, site_cezeaux_id, form)

        # Formes UCA (depuis config_validation.json)
        for form in config["universite"]["formes_acceptees"]:
            insert_form(cur, uca_id, form)
        for form in config["universite"]["formes_obsoletes"]:
            is_regex = "\\b" in form
            insert_form(cur, uca_id, form, is_regex=is_regex)

        # INP Clermont Auvergne
        inp_id = upsert_structure(cur, "inp_clermont", "Clermont Auvergne INP",
                                  "INP", "ecole")
        print(f"  INP Clermont → id={inp_id}")
        for form in config["inp"]["formes_acceptees"]:
            insert_form(cur, inp_id, form)
        # INP est partenaire de l'UCA
        upsert_relation(cur, inp_id, uca_id, "est_partenaire_de")

        # ============================================================
        # 2. Tutelles et partenaires (depuis config_validation.json)
        # ============================================================
        print("\n=== Tutelles et partenaires ===")

        tutelle_ids = {}  # nom canonique → structure_id

        for key, tdata in config.get("tutelles_courantes", {}).items():
            acronym = tdata.get("acronyme", None)
            name = tdata.get("nom_complet", key)
            code = make_code(key, acronym)

            # Déterminer le type
            stype = "onr"
            if any(x in name.lower() for x in ["école", "ecole", "mines", "vetagro", "esc "]):
                stype = "ecole"
            if "université" in name.lower() or "university" in name.lower():
                stype = "universite"

            tid = upsert_structure(cur, code, name, acronym, stype)
            tutelle_ids[key] = tid
            print(f"  {key} → id={tid} (type={stype})")

            # Formes
            for form_text, props in tdata.get("formes", {}).items():
                is_regex = "\\b" in form_text
                ctx = None
                if props.get("ambigu", False):
                    # Forme ambiguë d'une tutelle → nécessite le contexte UCA
                    ctx = [uca_id]
                insert_form(cur, tid, form_text, is_regex=is_regex,
                            requires_context_of=ctx)

        # ============================================================
        # 3. CHU Clermont-Ferrand
        # ============================================================
        print("\n=== CHU ===")

        chu_id = upsert_structure(cur, "chu_clermont", "CHU Clermont-Ferrand",
                                  "CHU", "chu")
        print(f"  CHU Clermont → id={chu_id}")
        upsert_relation(cur, chu_id, uca_id, "est_partenaire_de")

        # Formes suffisantes (entités du CHU)
        for form in config["chu"]["entites_chu_clermont"]:
            insert_form(cur, chu_id, form)

        # Formes nécessitant le contexte site_clermont
        for form in config["chu"]["indicateurs_chu"]:
            is_regex = "\\b" in form
            insert_form(cur, chu_id, form, is_regex=is_regex,
                        requires_context_of=[site_clermont_id])

        # ============================================================
        # 4. Laboratoires (depuis labos.json)
        # ============================================================
        print("\n=== Laboratoires ===")

        # Mapping nom tutelle (dans labos.json) → structure_id
        # Les tutelles dans labos.json utilisent des noms comme "CNRS", "INRAE"
        # qu'il faut mapper vers les structures créées ci-dessus
        tutelle_name_to_id = {}
        tutelle_name_to_id["Université Clermont Auvergne"] = uca_id
        for key, tid in tutelle_ids.items():
            tutelle_name_to_id[key] = tid

        # Récupérer le mapping ror_id → laboratory.id
        cur.execute("SELECT id, ror_id FROM laboratories WHERE ror_id IS NOT NULL")
        ror_to_lab_id = {row[1]: row[0] for row in cur.fetchall()}

        labo_structure_ids = {}  # ror_id → structure_id

        for ror_id, ldata in labos_data["labos"].items():
            acronym = ldata.get("acronyme", "")
            name = ldata.get("nom_complet", "")
            code = make_code(name, acronym)
            hal_collection = ldata.get("hal_collection", None)
            lab_id = ror_to_lab_id.get(ror_id)

            sid = upsert_structure(cur, code, name, acronym, "labo",
                                   ror_id=ror_id, hal_collection=hal_collection,
                                   laboratory_id=lab_id)
            labo_structure_ids[ror_id] = sid
            print(f"  {acronym or name} → id={sid} (lab_id={lab_id})")

            # Relations : tutelles
            for tutelle_name in ldata.get("tutelles", []):
                parent_id = tutelle_name_to_id.get(tutelle_name)
                if parent_id:
                    upsert_relation(cur, parent_id, sid, "est_tutelle_de")
                else:
                    print(f"    ⚠ Tutelle inconnue: {tutelle_name}")

            # Formes de noms
            for form_text, props in ldata.get("formes", {}).items():
                is_regex = "\\b" in form_text
                accepted = props.get("accepte", True)
                ambiguous = props.get("ambigu", False)

                if not accepted and not ambiguous:
                    # Forme rejetée et non ambiguë (ex: UMR6602) → on l'importe
                    # mais désactivée, pour mémoire
                    insert_form(cur, sid, form_text, is_regex=is_regex)
                elif ambiguous:
                    # Forme ambiguë → requires_context_of = ["tutelles"]
                    insert_form(cur, sid, form_text, is_regex=is_regex,
                                requires_context_of=["tutelles"])
                else:
                    # Forme suffisante
                    insert_form(cur, sid, form_text, is_regex=is_regex)

        # ============================================================
        # 5. Résumé
        # ============================================================
        cur.execute("SELECT COUNT(*) FROM structures")
        n_structures = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM structure_relations")
        n_relations = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM name_forms")
        n_forms = cur.fetchone()[0]

        print(f"\n{'='*50}")
        print(f"  Structures   : {n_structures}")
        print(f"  Relations    : {n_relations}")
        print(f"  Formes       : {n_forms}")
        print(f"{'='*50}")

        if args.dry_run:
            print("\n⚠ DRY RUN — rollback")
            conn.rollback()
        else:
            conn.commit()
            print("\n✓ Commit OK")

    except Exception as e:
        conn.rollback()
        print(f"\n✗ Erreur : {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
