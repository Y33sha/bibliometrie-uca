"""Import APC payment data from CSV files into apc_payments table.

Usage:
    python processing/import_apc.py
"""

import os
import csv
import re

import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
from config.settings import DB

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "imports_manuels", "APC")


def parse_amount(s: str) -> float | None:
    """Parse un montant EUR HT au format français (espace insécable, virgule décimale)."""
    if not s or s.strip().lower() in ('', 'na', 'non identifié'):
        return None
    s = s.replace('\xa0', '').replace(' ', '').replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return None


def parse_year(s: str) -> int | None:
    if not s or not s.strip().isdigit():
        return None
    y = int(s.strip())
    return y if 1990 <= y <= 2100 else None


def clean(s: str) -> str | None:
    """Strip et retourne None si vide."""
    s = (s or '').strip()
    return s if s else None


def import_main_file(cur):
    """Importe le fichier principal APC."""
    fname = None
    for f in os.listdir(DATA_DIR):
        if f.startswith('APC') and f.endswith('.csv'):
            fname = f
            break
    if not fname:
        print("Fichier principal APC introuvable")
        return 0

    path = os.path.join(DATA_DIR, fname)
    with open(path, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = []
        for r in reader:
            doi = clean(r.get('DOI', ''))
            if doi and doi.lower() in ('non identifié', 'na'):
                doi = None
            rows.append((
                clean(r.get('Laboratoire')),
                clean(r.get('Editeur')),
                clean(r.get('TypeEditeur')),
                clean(r.get('Revue')),
                clean(r.get('Issn_l')),
                clean(r.get('TypeRevue')),
                doi,
                clean(r.get('TitreArticle')),
                parse_amount(r.get('MontantEURHT', '')),
                parse_year(r.get('AnneeFacturation', '')),
                parse_year(r.get('AnneePublication', '')),
                clean(r.get('Budget')),
                clean(r.get('Etablissement')),
                clean(r.get('TypeEtablissement')),
                int(r['CoManId']) if r.get('CoManId', '').strip().isdigit() else None,
                clean(r.get('EtablissementsRepondantsAToutesLesEnquetes')),
                clean(r.get('PaiementPartage')),
                'enquete_apc',
                None,  # expense_type
                clean(r.get('Remarques')),
            ))

    execute_values(cur, """
        INSERT INTO apc_payments (
            lab_name, publisher_name, publisher_type, journal_name, issn,
            journal_type, doi, article_title, amount_eur_ht, billing_year,
            pub_year, budget, institution, institution_type, coman_id,
            all_surveys_answered, shared_payment, source_file, expense_type, remarks
        ) VALUES %s
    """, rows)
    return len(rows)


def import_fp_hors_oa(cur):
    """Importe FP hors OA."""
    path = os.path.join(DATA_DIR, "FP hors OA.csv")
    if not os.path.exists(path):
        return 0

    with open(path, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = []
        for r in reader:
            doi = clean(r.get('DOI', ''))
            if doi and doi.lower() in ('non identifié', 'na'):
                doi = None
            rows.append((
                clean(r.get('Laboratoire')),
                clean(r.get('Editeur')),
                clean(r.get("Type d'éditeur*")),
                clean(r.get('Revue')),
                clean(r.get('ISSN')),
                clean(r.get("Type de revue*")),
                doi,
                None,  # article_title
                parse_amount(r.get('Montant payé en EURHT', '')),
                parse_year(r.get('Année de facturation', '')),
                parse_year(r.get('Année de publication', '')),
                clean(r.get('Budget')),
                None,  # institution (pas de colonne dédiée, budget = institution)
                clean(r.get("Type d'établissement")),
                int(r['CoMan Id.']) if r.get('CoMan Id.', '').strip().isdigit() else None,
                clean(r.get("Etablissement ayant répondu à toutes les enquêtes\ndepuis 2017")),
                None,  # shared_payment
                'fp_hors_oa',
                clean(r.get("Nature de la dépense*")),
                clean(r.get('Remarques')),
            ))

    execute_values(cur, """
        INSERT INTO apc_payments (
            lab_name, publisher_name, publisher_type, journal_name, issn,
            journal_type, doi, article_title, amount_eur_ht, billing_year,
            pub_year, budget, institution, institution_type, coman_id,
            all_surveys_answered, shared_payment, source_file, expense_type, remarks
        ) VALUES %s
    """, rows)
    return len(rows)


def map_dois(cur):
    """Mappe les DOI vers publication_id."""
    cur.execute("""
        UPDATE apc_payments ap
        SET publication_id = p.id
        FROM publications p
        WHERE ap.doi IS NOT NULL
          AND LOWER(ap.doi) = LOWER(p.doi)
          AND ap.publication_id IS NULL
    """)
    return cur.rowcount


def map_journals(cur):
    """Mappe les ISSN vers journal_id."""
    cur.execute("""
        UPDATE apc_payments ap
        SET journal_id = j.id
        FROM journals j
        WHERE ap.issn IS NOT NULL
          AND (ap.issn = j.issn OR ap.issn = j.eissn)
          AND ap.journal_id IS NULL
    """)
    return cur.rowcount


def map_publishers(cur):
    """Mappe les noms d'éditeurs vers publisher_id."""
    cur.execute("""
        UPDATE apc_payments ap
        SET publisher_id = pub.id
        FROM publishers pub
        WHERE ap.publisher_name IS NOT NULL
          AND LOWER(ap.publisher_name) = LOWER(pub.name)
          AND ap.publisher_id IS NULL
    """)
    return cur.rowcount


def main():
    conn = psycopg2.connect(**DB)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Vider la table avant import (ré-importable)
    cur.execute("TRUNCATE apc_payments RESTART IDENTITY")

    n1 = import_main_file(cur)
    print(f"Fichier principal: {n1} lignes importées")

    n2 = import_fp_hors_oa(cur)
    print(f"FP hors OA: {n2} lignes importées")

    # Mapping
    m_doi = map_dois(cur)
    print(f"DOI mappés → publication_id: {m_doi}")

    m_j = map_journals(cur)
    print(f"ISSN mappés → journal_id: {m_j}")

    m_p = map_publishers(cur)
    print(f"Éditeurs mappés → publisher_id: {m_p}")

    # Stats
    cur.execute("SELECT COUNT(*) AS total, COUNT(publication_id) AS with_pub, COUNT(journal_id) AS with_journal, COUNT(publisher_id) AS with_publisher FROM apc_payments")
    s = cur.fetchone()
    print(f"\nTotal: {s['total']} lignes")
    print(f"  avec publication_id: {s['with_pub']}")
    print(f"  avec journal_id: {s['with_journal']}")
    print(f"  avec publisher_id: {s['with_publisher']}")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
