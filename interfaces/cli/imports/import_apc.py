# STATUS: recurring (imports)
"""Import APC payment data from CSV files into apc_payments table.

Usage:
    python -m interfaces.cli.imports.import_apc
"""

import csv
import os

from sqlalchemy import Connection, text

from infrastructure.db.engine import get_sync_engine

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "imports_manuels",
    "APC",
)

INSERT_APC_PAYMENT = text("""
    INSERT INTO apc_payments (
        lab_name, publisher_name, publisher_type, journal_name, issn,
        journal_type, doi, article_title, amount_eur_ht, billing_year,
        pub_year, budget, institution, institution_type, coman_id,
        all_surveys_answered, shared_payment, source_file, expense_type, remarks
    ) VALUES (
        :lab_name, :publisher_name, :publisher_type, :journal_name, :issn,
        :journal_type, :doi, :article_title, :amount_eur_ht, :billing_year,
        :pub_year, :budget, :institution, :institution_type, :coman_id,
        :all_surveys_answered, :shared_payment, :source_file, :expense_type, :remarks
    )
""")


def parse_amount(s: str) -> float | None:
    """Parse un montant EUR HT au format français (espace insécable, virgule décimale)."""
    if not s or s.strip().lower() in ("", "na", "non identifié"):
        return None
    s = s.replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_year(s: str) -> int | None:
    if not s or not s.strip().isdigit():
        return None
    y = int(s.strip())
    return y if 1990 <= y <= 2100 else None


def clean(s: str | None) -> str | None:
    """Strip et retourne None si vide."""
    s = (s or "").strip()
    return s if s else None


def import_main_file(conn: Connection) -> int:
    """Importe le fichier principal APC."""
    fname = None
    for name in os.listdir(DATA_DIR):
        if name.startswith("APC") and name.endswith(".csv"):
            fname = name
            break
    if not fname:
        print("Fichier principal APC introuvable")
        return 0

    path = os.path.join(DATA_DIR, fname)
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = []
        for r in reader:
            doi = clean(r.get("DOI", ""))
            if doi and doi.lower() in ("non identifié", "na"):
                doi = None
            rows.append(
                {
                    "lab_name": clean(r.get("Laboratoire")),
                    "publisher_name": clean(r.get("Editeur")),
                    "publisher_type": clean(r.get("TypeEditeur")),
                    "journal_name": clean(r.get("Revue")),
                    "issn": clean(r.get("Issn_l")),
                    "journal_type": clean(r.get("TypeRevue")),
                    "doi": doi,
                    "article_title": clean(r.get("TitreArticle")),
                    "amount_eur_ht": parse_amount(r.get("MontantEURHT", "")),
                    "billing_year": parse_year(r.get("AnneeFacturation", "")),
                    "pub_year": parse_year(r.get("AnneePublication", "")),
                    "budget": clean(r.get("Budget")),
                    "institution": clean(r.get("Etablissement")),
                    "institution_type": clean(r.get("TypeEtablissement")),
                    "coman_id": int(r["CoManId"])
                    if r.get("CoManId", "").strip().isdigit()
                    else None,
                    "all_surveys_answered": clean(
                        r.get("EtablissementsRepondantsAToutesLesEnquetes")
                    ),
                    "shared_payment": clean(r.get("PaiementPartage")),
                    "source_file": "enquete_apc",
                    "expense_type": None,
                    "remarks": clean(r.get("Remarques")),
                }
            )

    conn.execute(INSERT_APC_PAYMENT, rows)
    return len(rows)


def import_fp_hors_oa(conn: Connection) -> int:
    """Importe FP hors OA."""
    path = os.path.join(DATA_DIR, "FP hors OA.csv")
    if not os.path.exists(path):
        return 0

    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = []
        for r in reader:
            doi = clean(r.get("DOI", ""))
            if doi and doi.lower() in ("non identifié", "na"):
                doi = None
            rows.append(
                {
                    "lab_name": clean(r.get("Laboratoire")),
                    "publisher_name": clean(r.get("Editeur")),
                    "publisher_type": clean(r.get("Type d'éditeur*")),
                    "journal_name": clean(r.get("Revue")),
                    "issn": clean(r.get("ISSN")),
                    "journal_type": clean(r.get("Type de revue*")),
                    "doi": doi,
                    "article_title": None,
                    "amount_eur_ht": parse_amount(r.get("Montant payé en EURHT", "")),
                    "billing_year": parse_year(r.get("Année de facturation", "")),
                    "pub_year": parse_year(r.get("Année de publication", "")),
                    "budget": clean(r.get("Budget")),
                    # Pas de colonne dédiée institution : budget = institution
                    "institution": None,
                    "institution_type": clean(r.get("Type d'établissement")),
                    "coman_id": int(r["CoMan Id."])
                    if r.get("CoMan Id.", "").strip().isdigit()
                    else None,
                    "all_surveys_answered": clean(
                        r.get("Etablissement ayant répondu à toutes les enquêtes\ndepuis 2017")
                    ),
                    "shared_payment": None,
                    "source_file": "fp_hors_oa",
                    "expense_type": clean(r.get("Nature de la dépense*")),
                    "remarks": clean(r.get("Remarques")),
                }
            )

    conn.execute(INSERT_APC_PAYMENT, rows)
    return len(rows)


def map_dois(conn: Connection) -> int:
    """Mappe les DOI vers publication_id."""
    return conn.execute(
        text("""
            UPDATE apc_payments ap
            SET publication_id = p.id
            FROM publications p
            WHERE ap.doi IS NOT NULL
              AND LOWER(ap.doi) = LOWER(p.doi)
              AND ap.publication_id IS NULL
        """)
    ).rowcount


def map_journals(conn: Connection) -> int:
    """Mappe les ISSN vers journal_id."""
    return conn.execute(
        text("""
            UPDATE apc_payments ap
            SET journal_id = j.id
            FROM journals j
            WHERE ap.issn IS NOT NULL
              AND (ap.issn = j.issn OR ap.issn = j.eissn)
              AND ap.journal_id IS NULL
        """)
    ).rowcount


def map_publishers(conn: Connection) -> int:
    """Mappe les noms d'éditeurs vers publisher_id."""
    return conn.execute(
        text("""
            UPDATE apc_payments ap
            SET publisher_id = pub.id
            FROM publishers pub
            WHERE ap.publisher_name IS NOT NULL
              AND LOWER(ap.publisher_name) = LOWER(pub.name)
              AND ap.publisher_id IS NULL
        """)
    ).rowcount


def main() -> None:
    engine = get_sync_engine()
    with engine.connect() as conn, conn.begin():
        # Vider la table avant import (ré-importable)
        conn.execute(text("TRUNCATE apc_payments RESTART IDENTITY"))

        n1 = import_main_file(conn)
        print(f"Fichier principal: {n1} lignes importées")

        n2 = import_fp_hors_oa(conn)
        print(f"FP hors OA: {n2} lignes importées")

        m_doi = map_dois(conn)
        print(f"DOI mappés → publication_id: {m_doi}")

        m_j = map_journals(conn)
        print(f"ISSN mappés → journal_id: {m_j}")

        m_p = map_publishers(conn)
        print(f"Éditeurs mappés → publisher_id: {m_p}")

        s = conn.execute(
            text("""
                SELECT COUNT(*) AS total,
                       COUNT(publication_id) AS with_pub,
                       COUNT(journal_id) AS with_journal,
                       COUNT(publisher_id) AS with_publisher
                FROM apc_payments
            """)
        ).one()
        print(f"\nTotal: {s.total} lignes")
        print(f"  avec publication_id: {s.with_pub}")
        print(f"  avec journal_id: {s.with_journal}")
        print(f"  avec publisher_id: {s.with_publisher}")


if __name__ == "__main__":
    main()
