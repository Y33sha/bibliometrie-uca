"""
Étape 2.7 — Migration des tables d'adresses

1. address_laboratories → address_structures
   - Utilise structure_id directement quand disponible (9291/9345)
   - Mappe les 54 restants via laboratories.ror_id → structures.ror_id

2. publication_author_addresses → openalex_authorship_addresses
   - Retrouve l'openalex_authorship_id via la chaîne :
     publication_authors → legacy_authors.openalex_id → openalex_authors
     publication_authors.publication_id → openalex_documents.publication_id
     → openalex_authorships
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.connection import get_connection


def migrate_address_structures(cur, dry_run=False):
    """address_laboratories → address_structures"""

    print("\n" + "=" * 60)
    print("1. address_laboratories → address_structures")
    print("=" * 60)

    # Stats avant
    cur.execute("SELECT count(*) FROM address_laboratories")
    total = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM address_laboratories WHERE structure_id IS NOT NULL")
    with_struct = cur.fetchone()[0]
    cur.execute("""
        SELECT count(*) FROM address_laboratories
        WHERE structure_id IS NULL AND laboratory_id IS NOT NULL
    """)
    lab_only = cur.fetchone()[0]
    cur.execute("""
        SELECT count(*) FROM address_laboratories
        WHERE structure_id IS NULL AND laboratory_id IS NULL
    """)
    no_link = cur.fetchone()[0]

    print(f"  Total address_laboratories: {total}")
    print(f"  Avec structure_id:          {with_struct}")
    print(f"  laboratory_id seulement:    {lab_only}")
    print(f"  Sans aucun lien:            {no_link}")

    # D'abord, résoudre les 54 via ror_id
    cur.execute("""
        UPDATE address_laboratories al
        SET structure_id = s.id
        FROM laboratories l
        JOIN structures s ON s.ror_id = l.ror_id
        WHERE al.laboratory_id = l.id
          AND al.structure_id IS NULL
          AND l.ror_id IS NOT NULL
    """)
    mapped = cur.rowcount
    print(f"\n  Mappés via ror_id: {mapped}")

    # Vérifier s'il reste des orphelins
    cur.execute("""
        SELECT count(*) FROM address_laboratories
        WHERE structure_id IS NULL AND laboratory_id IS NOT NULL
    """)
    still_orphan = cur.fetchone()[0]
    if still_orphan > 0:
        print(f"  ⚠ Encore {still_orphan} lignes sans structure_id après mapping ror_id")
        cur.execute("""
            SELECT al.id, al.laboratory_id, l.code, l.name
            FROM address_laboratories al
            JOIN laboratories l ON l.id = al.laboratory_id
            WHERE al.structure_id IS NULL
            LIMIT 10
        """)
        for row in cur.fetchall():
            print(f"    al.id={row[0]}, lab_id={row[1]}, code={row[2]}, name={row[3]}")

    # Vider la table cible
    cur.execute("DELETE FROM address_structures")
    print(f"\n  address_structures vidée")

    # Insérer depuis address_laboratories
    cur.execute("""
        INSERT INTO address_structures (address_id, structure_id, matched_form_id, is_confirmed)
        SELECT al.address_id, al.structure_id, al.matched_form_id, al.is_valid
        FROM address_laboratories al
        WHERE al.structure_id IS NOT NULL
        ON CONFLICT (address_id, structure_id) DO NOTHING
    """)
    inserted = cur.rowcount
    print(f"  Insérés dans address_structures: {inserted}")

    # Lignes ignorées (structure_id NULL)
    cur.execute("SELECT count(*) FROM address_laboratories WHERE structure_id IS NULL")
    skipped = cur.fetchone()[0]
    if skipped > 0:
        print(f"  Ignorés (structure_id NULL): {skipped}")

    return inserted


def migrate_authorship_addresses(cur, dry_run=False):
    """publication_author_addresses → openalex_authorship_addresses"""

    print("\n" + "=" * 60)
    print("2. publication_author_addresses → openalex_authorship_addresses")
    print("=" * 60)

    # Stats
    cur.execute("SELECT count(*) FROM publication_author_addresses")
    total = cur.fetchone()[0]
    print(f"  Total publication_author_addresses: {total}")

    # Compter ceux qui viennent d'OpenAlex
    cur.execute("""
        SELECT count(*)
        FROM publication_author_addresses paa
        JOIN publication_authors pa ON pa.id = paa.publication_author_id
        WHERE pa.source = 'openalex'
    """)
    openalex_count = cur.fetchone()[0]
    print(f"  Dont source OpenAlex: {openalex_count}")

    # Vider la table cible
    cur.execute("DELETE FROM openalex_authorship_addresses")

    # Jointure complète pour retrouver l'openalex_authorship_id
    # Chaîne : publication_authors → legacy_authors (via author_id)
    #          legacy_authors.openalex_id → openalex_authors.openalex_id
    #          publication_authors.publication_id → openalex_documents.publication_id
    #          → openalex_authorships (doc_id + author_id)
    cur.execute("""
        INSERT INTO openalex_authorship_addresses (openalex_authorship_id, address_id)
        SELECT DISTINCT oas.id, paa.address_id
        FROM publication_author_addresses paa
        JOIN publication_authors pa ON pa.id = paa.publication_author_id
        JOIN legacy_authors la ON la.id = pa.author_id
        JOIN openalex_authors oa ON oa.openalex_id = la.openalex_id
        JOIN openalex_documents od ON od.publication_id = pa.publication_id
        JOIN openalex_authorships oas ON oas.openalex_author_id = oa.id
                                     AND oas.openalex_document_id = od.id
        WHERE pa.source = 'openalex'
          AND la.openalex_id IS NOT NULL
        ON CONFLICT (openalex_authorship_id, address_id) DO NOTHING
    """)
    inserted = cur.rowcount
    print(f"\n  Insérés dans openalex_authorship_addresses: {inserted}")

    # Vérifier les non-mappés
    not_mapped = openalex_count - inserted
    if not_mapped > 0:
        print(f"  ⚠ Non mappés: {not_mapped}")

        # Diagnostic : pourquoi non mappés ?
        cur.execute("""
            SELECT count(*)
            FROM publication_author_addresses paa
            JOIN publication_authors pa ON pa.id = paa.publication_author_id
            JOIN legacy_authors la ON la.id = pa.author_id
            WHERE pa.source = 'openalex' AND la.openalex_id IS NULL
        """)
        no_oaid = cur.fetchone()[0]

        cur.execute("""
            SELECT count(*)
            FROM publication_author_addresses paa
            JOIN publication_authors pa ON pa.id = paa.publication_author_id
            JOIN legacy_authors la ON la.id = pa.author_id
            LEFT JOIN openalex_authors oa ON oa.openalex_id = la.openalex_id
            WHERE pa.source = 'openalex'
              AND la.openalex_id IS NOT NULL
              AND oa.id IS NULL
        """)
        no_oa_match = cur.fetchone()[0]

        cur.execute("""
            SELECT count(*)
            FROM publication_author_addresses paa
            JOIN publication_authors pa ON pa.id = paa.publication_author_id
            LEFT JOIN openalex_documents od ON od.publication_id = pa.publication_id
            WHERE pa.source = 'openalex'
              AND od.id IS NULL
        """)
        no_doc_match = cur.fetchone()[0]

        print(f"    legacy_authors sans openalex_id:          {no_oaid}")
        print(f"    openalex_id non trouvé dans openalex_authors: {no_oa_match}")
        print(f"    publication_id non trouvé dans openalex_documents: {no_doc_match}")

    return inserted


def main():
    dry_run = "--dry-run" in sys.argv

    conn = get_connection()
    try:
        cur = conn.cursor()

        n1 = migrate_address_structures(cur, dry_run)
        n2 = migrate_authorship_addresses(cur, dry_run)

        print("\n" + "=" * 60)
        print("RÉSUMÉ")
        print("=" * 60)
        print(f"  address_structures:              {n1} lignes")
        print(f"  openalex_authorship_addresses:   {n2} lignes")

        if dry_run:
            print("\n  🔶 DRY RUN — rollback")
            conn.rollback()
        else:
            conn.commit()
            print("\n  ✅ Migration commitée")

    except Exception as e:
        conn.rollback()
        print(f"\n  ❌ Erreur : {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
