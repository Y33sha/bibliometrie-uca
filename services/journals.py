"""
Service Référentiel bibliographique — accès exclusif en écriture
aux tables `publishers` et `journals`.

Toute création ou recherche de journal/éditeur passe par ce module.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.normalize import normalize_text


# ── Publishers ──

def find_or_create_publisher(cur, name: str | None, *,
                             openalex_id: str | None = None) -> int | None:
    """Trouve ou crée un éditeur.

    Recherche par openalex_id (si fourni), puis par nom normalisé.
    Retourne publisher.id ou None si name est vide.
    """
    if not name:
        return None

    name_normalized = normalize_text(name)
    if not name_normalized:
        return None

    # 1. Par openalex_id (upsert)
    if openalex_id:
        cur.execute("""
            INSERT INTO publishers (name, name_normalized, openalex_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (openalex_id) DO UPDATE SET
                name = COALESCE(NULLIF(publishers.name, ''), EXCLUDED.name)
            RETURNING id
        """, (name, name_normalized, openalex_id))
        row = cur.fetchone()
        if row:
            return row["id"]

    # 2. Par nom normalisé
    cur.execute(
        "SELECT id FROM publishers WHERE name_normalized = %s LIMIT 1",
        (name_normalized,))
    row = cur.fetchone()
    if row:
        return row["id"]

    # 3. Créer
    cur.execute("""
        INSERT INTO publishers (name, name_normalized)
        VALUES (%s, %s)
        RETURNING id
    """, (name.strip(), name_normalized))
    return cur.fetchone()["id"]


# ── Journals ──

def _enrich_journal(cur, journal_id: int, *, issn=None, eissn=None,
                    publisher_id=None):
    """Enrichit un journal existant avec les métadonnées manquantes."""
    cur.execute("""
        UPDATE journals SET
            issn = COALESCE(journals.issn, %s),
            eissn = COALESCE(journals.eissn, %s),
            publisher_id = COALESCE(journals.publisher_id, %s)
        WHERE id = %s
    """, (issn, eissn, publisher_id, journal_id))


def find_or_create_journal(cur, title: str | None, *,
                           issn: str | None = None,
                           eissn: str | None = None,
                           issnl: str | None = None,
                           publisher_id: int | None = None,
                           openalex_id: str | None = None,
                           oa_model: str | None = None) -> int | None:
    """Trouve ou crée un journal.

    Cascade de recherche :
    1. openalex_id (upsert si fourni)
    2. ISSN (+ check issnl)
    3. eISSN (+ check issnl)
    4. ISSN-L
    5. Titre normalisé

    Enrichit les métadonnées manquantes quand un journal existant est trouvé.
    Retourne journal.id ou None si title est vide.
    """
    if not title:
        return None

    title_normalized = normalize_text(title)

    # 1. Par openalex_id (upsert)
    if openalex_id:
        cur.execute("""
            INSERT INTO journals (title, title_normalized, issn, eissn, issnl,
                                  publisher_id, openalex_id, oa_model)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (openalex_id) DO UPDATE SET
                title = COALESCE(NULLIF(journals.title, ''), EXCLUDED.title),
                issnl = COALESCE(journals.issnl, EXCLUDED.issnl),
                issn = COALESCE(journals.issn, EXCLUDED.issn),
                eissn = COALESCE(journals.eissn, EXCLUDED.eissn),
                publisher_id = COALESCE(journals.publisher_id, EXCLUDED.publisher_id),
                oa_model = COALESCE(journals.oa_model, EXCLUDED.oa_model)
            RETURNING id
        """, (title, title_normalized, issn, eissn, issnl,
              publisher_id, openalex_id, oa_model))
        return cur.fetchone()["id"]

    # 2. Par ISSN
    if issn:
        cur.execute(
            "SELECT id FROM journals WHERE issn = %s OR issnl = %s LIMIT 1",
            (issn, issn))
        row = cur.fetchone()
        if row:
            _enrich_journal(cur, row["id"], eissn=eissn, publisher_id=publisher_id)
            return row["id"]

    # 3. Par eISSN
    if eissn:
        cur.execute(
            "SELECT id FROM journals WHERE eissn = %s OR issnl = %s LIMIT 1",
            (eissn, eissn))
        row = cur.fetchone()
        if row:
            _enrich_journal(cur, row["id"], issn=issn, publisher_id=publisher_id)
            return row["id"]

    # 4. Par ISSN-L
    if issnl:
        cur.execute("SELECT id FROM journals WHERE issnl = %s LIMIT 1", (issnl,))
        row = cur.fetchone()
        if row:
            _enrich_journal(cur, row["id"], issn=issn, eissn=eissn,
                            publisher_id=publisher_id)
            return row["id"]

    # 5. Par titre normalisé
    cur.execute(
        "SELECT id FROM journals WHERE title_normalized = %s LIMIT 1",
        (title_normalized,))
    row = cur.fetchone()
    if row:
        _enrich_journal(cur, row["id"], issn=issn, eissn=eissn,
                        publisher_id=publisher_id)
        return row["id"]

    # 6. Créer
    cur.execute("""
        INSERT INTO journals (title, title_normalized, issn, eissn, issnl,
                              publisher_id, oa_model)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (title.strip(), title_normalized, issn, eissn, issnl,
          publisher_id, oa_model))
    return cur.fetchone()["id"]


def update_journal_apc(cur, journal_id: int, *,
                       apc_amount: float | None = None,
                       apc_currency: str | None = None,
                       is_in_doaj: bool | None = None):
    """Met à jour les informations APC/DOAJ d'un journal."""
    cur.execute("""
        UPDATE journals SET
            apc_amount = COALESCE(%s, journals.apc_amount),
            apc_currency = COALESCE(%s, journals.apc_currency),
            is_in_doaj = COALESCE(%s, journals.is_in_doaj)
        WHERE id = %s
    """, (apc_amount, apc_currency, is_in_doaj, journal_id))


def reset_journal_apc(cur):
    """Réinitialise les APC/DOAJ de toutes les revues avec openalex_id."""
    cur.execute("""
        UPDATE journals
        SET apc_amount = NULL, apc_currency = 'EUR', is_in_doaj = FALSE
        WHERE openalex_id IS NOT NULL
    """)
    return cur.rowcount
