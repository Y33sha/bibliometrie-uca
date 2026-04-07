"""
Service Référentiel bibliographique — accès exclusif en écriture
aux tables `publishers` et `journals`.

Toute création ou recherche de journal/éditeur passe par ce module.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.normalize import normalize_text


# ── Publishers ──

def _add_publisher_name_form(cur, publisher_id: int, form_normalized: str):
    """Ajoute une forme de nom si elle n'existe pas encore."""
    cur.execute("""
        INSERT INTO publisher_name_forms (publisher_id, form_normalized)
        VALUES (%s, %s)
        ON CONFLICT (form_normalized) DO NOTHING
    """, (publisher_id, form_normalized))


def find_or_create_publisher(cur, name: str | None, *,
                             openalex_id: str | None = None) -> int | None:
    """Trouve ou crée un éditeur.

    Cascade de recherche :
    1. openalex_id (si fourni)
    2. publisher_name_forms (par nom normalisé)
    3. Création + enregistrement de la forme de nom

    Retourne publisher.id ou None si name est vide.
    """
    if not name:
        return None

    name_normalized = normalize_text(name)
    if not name_normalized:
        return None

    # 1. Par openalex_id
    if openalex_id:
        cur.execute("SELECT id FROM publishers WHERE openalex_id = %s", (openalex_id,))
        row = cur.fetchone()
        if row:
            _add_publisher_name_form(cur, row["id"], name_normalized)
            return row["id"]

    # 2. Par forme de nom
    cur.execute("""
        SELECT publisher_id FROM publisher_name_forms
        WHERE form_normalized = %s LIMIT 1
    """, (name_normalized,))
    row = cur.fetchone()
    if row:
        pub_id = row["publisher_id"]
        # Rattacher l'openalex_id si on ne l'avait pas
        if openalex_id:
            cur.execute("""
                UPDATE publishers SET openalex_id = %s
                WHERE id = %s AND openalex_id IS NULL
            """, (openalex_id, pub_id))
        return pub_id

    # 3. Créer
    cur.execute("""
        INSERT INTO publishers (name, name_normalized, openalex_id)
        VALUES (%s, %s, %s)
        RETURNING id
    """, (name.strip(), name_normalized, openalex_id))
    pub_id = cur.fetchone()["id"]
    _add_publisher_name_form(cur, pub_id, name_normalized)
    return pub_id


# ── Journals ──

def _add_journal_name_form(cur, journal_id: int, form_normalized: str,
                           publisher_id: int | None = None):
    """Ajoute une forme de nom si elle n'existe pas encore."""
    if not form_normalized:
        return
    cur.execute("""
        INSERT INTO journal_name_forms (journal_id, form_normalized, publisher_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (form_normalized, publisher_id) DO NOTHING
    """, (journal_id, form_normalized, publisher_id))


def _enrich_journal(cur, journal_id: int, *, issn=None, eissn=None,
                    publisher_id=None, openalex_id=None, oa_model=None):
    """Enrichit un journal existant avec les métadonnées manquantes."""
    cur.execute("""
        UPDATE journals SET
            issn = COALESCE(journals.issn, %s),
            eissn = COALESCE(journals.eissn, %s),
            publisher_id = COALESCE(journals.publisher_id, %s),
            openalex_id = COALESCE(journals.openalex_id, %s),
            oa_model = COALESCE(journals.oa_model, %s)
        WHERE id = %s
    """, (issn, eissn, publisher_id, openalex_id, oa_model, journal_id))


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

    # 1. Par openalex_id
    if openalex_id:
        cur.execute("SELECT id FROM journals WHERE openalex_id = %s", (openalex_id,))
        row = cur.fetchone()
        if row:
            _enrich_journal(cur, row["id"], issn=issn, eissn=eissn,
                            publisher_id=publisher_id)
            _add_journal_name_form(cur, row["id"], title_normalized, publisher_id)
            return row["id"]
        # openalex_id inconnu : on cherche quand même par ISSN/name_form
        # avant de créer, pour rattacher l'openalex_id à un journal existant

    # 2. Par ISSN (cherche dans issn, eissn, issnl)
    if issn:
        cur.execute(
            "SELECT id FROM journals WHERE issn = %s OR eissn = %s OR issnl = %s LIMIT 1",
            (issn, issn, issn))
        row = cur.fetchone()
        if row:
            _enrich_journal(cur, row["id"], issn=issn, eissn=eissn,
                            publisher_id=publisher_id, openalex_id=openalex_id,
                            oa_model=oa_model)
            _add_journal_name_form(cur, row["id"], title_normalized, publisher_id)
            return row["id"]

    # 3. Par eISSN (cherche dans issn, eissn, issnl)
    if eissn:
        cur.execute(
            "SELECT id FROM journals WHERE issn = %s OR eissn = %s OR issnl = %s LIMIT 1",
            (eissn, eissn, eissn))
        row = cur.fetchone()
        if row:
            _enrich_journal(cur, row["id"], issn=issn, eissn=eissn,
                            publisher_id=publisher_id, openalex_id=openalex_id,
                            oa_model=oa_model)
            _add_journal_name_form(cur, row["id"], title_normalized, publisher_id)
            return row["id"]

    # 4. Par ISSN-L (cherche dans issn, eissn, issnl)
    if issnl:
        cur.execute(
            "SELECT id FROM journals WHERE issn = %s OR eissn = %s OR issnl = %s LIMIT 1",
            (issnl, issnl, issnl))
        row = cur.fetchone()
        if row:
            _enrich_journal(cur, row["id"], issn=issn, eissn=eissn,
                            publisher_id=publisher_id, openalex_id=openalex_id,
                            oa_model=oa_model)
            _add_journal_name_form(cur, row["id"], title_normalized, publisher_id)
            return row["id"]

    # 5. Par forme de nom (journal_name_forms)
    # Priorité aux journals avec eISSN (plus fiable que les ISSN print)
    cur.execute("""
        SELECT nf.journal_id FROM journal_name_forms nf
        JOIN journals j ON j.id = nf.journal_id
        WHERE nf.form_normalized = %s
          AND (nf.publisher_id IS NOT DISTINCT FROM %s OR nf.publisher_id IS NULL OR %s IS NULL)
        ORDER BY (j.eissn IS NOT NULL) DESC, j.id ASC
        LIMIT 1
    """, (title_normalized, publisher_id, publisher_id))
    row = cur.fetchone()
    if row:
        _enrich_journal(cur, row["journal_id"], issn=issn, eissn=eissn,
                        publisher_id=publisher_id, openalex_id=openalex_id,
                        oa_model=oa_model)
        return row["journal_id"]

    # 6. Créer + enregistrer la forme de nom
    cur.execute("""
        INSERT INTO journals (title, title_normalized, issn, eissn, issnl,
                              publisher_id, openalex_id, oa_model)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (title.strip(), title_normalized, issn, eissn, issnl,
          publisher_id, openalex_id, oa_model))
    journal_id = cur.fetchone()["id"]
    cur.execute("""
        INSERT INTO journal_name_forms (journal_id, form_normalized, publisher_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (form_normalized, publisher_id) DO NOTHING
    """, (journal_id, title_normalized, publisher_id))
    return journal_id


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
