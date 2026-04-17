"""
Service Référentiel bibliographique — accès exclusif en écriture
aux tables `publishers` et `journals`.

Toute création ou recherche de journal/éditeur passe par ce module.
Compatible avec les curseurs tuples (standard) et RealDictCursor.
"""

from utils.db_helpers import row_val as _val
from utils.normalize import normalize_text

# ── Publishers ──


def _add_publisher_name_form(cur, publisher_id: int, form_normalized: str):
    """Ajoute une forme de nom si elle n'existe pas encore."""
    cur.execute(
        """
        INSERT INTO publisher_name_forms (publisher_id, form_normalized)
        VALUES (%s, %s)
        ON CONFLICT (form_normalized) DO NOTHING
    """,
        (publisher_id, form_normalized),
    )


def find_or_create_publisher(
    cur, name: str | None, *, openalex_id: str | None = None
) -> int | None:
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
            _add_publisher_name_form(cur, _val(row, 0), name_normalized)
            return _val(row, 0)

    # 2. Par forme de nom
    cur.execute(
        """
        SELECT publisher_id FROM publisher_name_forms
        WHERE form_normalized = %s LIMIT 1
    """,
        (name_normalized,),
    )
    row = cur.fetchone()
    if row:
        pub_id = _val(row, 0)
        # Rattacher l'openalex_id si on ne l'avait pas
        if openalex_id:
            cur.execute(
                """
                UPDATE publishers SET openalex_id = %s
                WHERE id = %s AND openalex_id IS NULL
            """,
                (openalex_id, pub_id),
            )
        return pub_id

    # 3. Créer
    cur.execute(
        """
        INSERT INTO publishers (name, name_normalized, openalex_id)
        VALUES (%s, %s, %s)
        RETURNING id
    """,
        (name.strip(), name_normalized, openalex_id),
    )
    pub_id = _val(cur.fetchone(), 0)
    _add_publisher_name_form(cur, pub_id, name_normalized)
    return pub_id


# ── Journals ──


def _add_journal_name_form(
    cur, journal_id: int, form_normalized: str, publisher_id: int | None = None
):
    """Ajoute une forme de nom si elle n'existe pas encore."""
    if not form_normalized:
        return
    cur.execute(
        """
        INSERT INTO journal_name_forms (journal_id, form_normalized, publisher_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (form_normalized, publisher_id) DO NOTHING
    """,
        (journal_id, form_normalized, publisher_id),
    )


def _enrich_journal(
    cur,
    journal_id: int,
    *,
    issn=None,
    eissn=None,
    publisher_id=None,
    openalex_id=None,
    oa_model=None,
):
    """Enrichit un journal existant avec les métadonnées manquantes."""
    cur.execute(
        """
        UPDATE journals SET
            issn = COALESCE(journals.issn, %s),
            eissn = COALESCE(journals.eissn, %s),
            publisher_id = COALESCE(journals.publisher_id, %s),
            openalex_id = COALESCE(journals.openalex_id, %s),
            oa_model = COALESCE(journals.oa_model, %s)
        WHERE id = %s
    """,
        (issn, eissn, publisher_id, openalex_id, oa_model, journal_id),
    )


def find_or_create_journal(
    cur,
    title: str | None,
    *,
    issn: str | None = None,
    eissn: str | None = None,
    issnl: str | None = None,
    publisher_id: int | None = None,
    openalex_id: str | None = None,
    oa_model: str | None = None,
) -> int | None:
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
            _enrich_journal(cur, _val(row, 0), issn=issn, eissn=eissn, publisher_id=publisher_id)
            _add_journal_name_form(cur, _val(row, 0), title_normalized, publisher_id)
            return _val(row, 0)
        # openalex_id inconnu : on cherche quand même par ISSN/name_form
        # avant de créer, pour rattacher l'openalex_id à un journal existant

    # 2. Par ISSN (cherche dans issn, eissn, issnl)
    if issn:
        cur.execute(
            "SELECT id FROM journals WHERE issn = %s OR eissn = %s OR issnl = %s LIMIT 1",
            (issn, issn, issn),
        )
        row = cur.fetchone()
        if row:
            _enrich_journal(
                cur,
                _val(row, 0),
                issn=issn,
                eissn=eissn,
                publisher_id=publisher_id,
                openalex_id=openalex_id,
                oa_model=oa_model,
            )
            _add_journal_name_form(cur, _val(row, 0), title_normalized, publisher_id)
            return _val(row, 0)

    # 3. Par eISSN (cherche dans issn, eissn, issnl)
    if eissn:
        cur.execute(
            "SELECT id FROM journals WHERE issn = %s OR eissn = %s OR issnl = %s LIMIT 1",
            (eissn, eissn, eissn),
        )
        row = cur.fetchone()
        if row:
            _enrich_journal(
                cur,
                _val(row, 0),
                issn=issn,
                eissn=eissn,
                publisher_id=publisher_id,
                openalex_id=openalex_id,
                oa_model=oa_model,
            )
            _add_journal_name_form(cur, _val(row, 0), title_normalized, publisher_id)
            return _val(row, 0)

    # 4. Par ISSN-L (cherche dans issn, eissn, issnl)
    if issnl:
        cur.execute(
            "SELECT id FROM journals WHERE issn = %s OR eissn = %s OR issnl = %s LIMIT 1",
            (issnl, issnl, issnl),
        )
        row = cur.fetchone()
        if row:
            _enrich_journal(
                cur,
                _val(row, 0),
                issn=issn,
                eissn=eissn,
                publisher_id=publisher_id,
                openalex_id=openalex_id,
                oa_model=oa_model,
            )
            _add_journal_name_form(cur, _val(row, 0), title_normalized, publisher_id)
            return _val(row, 0)

    # 5. Par forme de nom (journal_name_forms)
    # Priorité aux journals avec eISSN (plus fiable que les ISSN print)
    cur.execute(
        """
        SELECT nf.journal_id FROM journal_name_forms nf
        JOIN journals j ON j.id = nf.journal_id
        WHERE nf.form_normalized = %s
          AND (nf.publisher_id IS NOT DISTINCT FROM %s OR nf.publisher_id IS NULL OR %s IS NULL)
        ORDER BY (j.eissn IS NOT NULL) DESC, j.id ASC
        LIMIT 1
    """,
        (title_normalized, publisher_id, publisher_id),
    )
    row = cur.fetchone()
    if row:
        _enrich_journal(
            cur,
            _val(row, 0),
            issn=issn,
            eissn=eissn,
            publisher_id=publisher_id,
            openalex_id=openalex_id,
            oa_model=oa_model,
        )
        return _val(row, 0)

    # 6. Créer + enregistrer la forme de nom
    cur.execute(
        """
        INSERT INTO journals (title, title_normalized, issn, eissn, issnl,
                              publisher_id, openalex_id, oa_model)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """,
        (title.strip(), title_normalized, issn, eissn, issnl, publisher_id, openalex_id, oa_model),
    )
    journal_id = _val(cur.fetchone(), 0)
    cur.execute(
        """
        INSERT INTO journal_name_forms (journal_id, form_normalized, publisher_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (form_normalized, publisher_id) DO NOTHING
    """,
        (journal_id, title_normalized, publisher_id),
    )
    return journal_id


def update_journal_apc(
    cur,
    journal_id: int,
    *,
    apc_amount: float | None = None,
    apc_currency: str | None = None,
    is_in_doaj: bool | None = None,
):
    """Met à jour les informations APC/DOAJ d'un journal."""
    cur.execute(
        """
        UPDATE journals SET
            apc_amount = COALESCE(%s, journals.apc_amount),
            apc_currency = COALESCE(%s, journals.apc_currency),
            is_in_doaj = COALESCE(%s, journals.is_in_doaj)
        WHERE id = %s
    """,
        (apc_amount, apc_currency, is_in_doaj, journal_id),
    )


def reset_journal_apc(cur):
    """Réinitialise les APC/DOAJ de toutes les revues avec openalex_id."""
    cur.execute("""
        UPDATE journals
        SET apc_amount = NULL, apc_currency = 'EUR', is_in_doaj = FALSE
        WHERE openalex_id IS NOT NULL
    """)
    return cur.rowcount


# ── Fusions ──


def merge_publishers(cur, target_id: int, source_id: int):
    """Fusionne l'éditeur source dans l'éditeur cible.

    1. Fusionne les journals qui auraient le même titre normalisé
    2. Transfère les journals restants
    3. Transfère les formes de nom
    4. Transfère les apc_payments
    5. Enrichit la cible (openalex_id, country)
    6. Supprime la source
    """
    if target_id == source_id:
        raise RuntimeError("Impossible de fusionner un éditeur avec lui-même")

    # 1. Journals avec même titre normalisé → fusionner
    cur.execute(
        """
        SELECT jt.id AS target_journal_id, js.id AS source_journal_id
        FROM journals jt
        JOIN journals js ON js.title_normalized = jt.title_normalized
        WHERE jt.publisher_id = %s AND js.publisher_id = %s
    """,
        (target_id, source_id),
    )
    journal_pairs = cur.fetchall()

    for pair in journal_pairs:
        tj_id = pair["target_journal_id"]
        sj_id = pair["source_journal_id"]
        # Vérifier les conflits ISSN avant de fusionner
        cur.execute("SELECT issn, eissn, issnl FROM journals WHERE id = %s", (tj_id,))
        target_j = cur.fetchone()
        cur.execute("SELECT issn, eissn, issnl FROM journals WHERE id = %s", (sj_id,))
        source_j = cur.fetchone()

        for field in ("issn", "eissn", "issnl"):
            tv = target_j[field]
            sv = source_j[field]
            if tv and sv and tv != sv:
                raise RuntimeError(
                    f"Conflit {field} lors de la fusion des revues "
                    f"(cible #{tj_id}: {tv}, source #{sj_id}: {sv}). "
                    f"Fusionner les revues manuellement d'abord."
                )

        merge_journals(cur, tj_id, sj_id)

    # 2. Transférer les journals restants
    cur.execute(
        "UPDATE journals SET publisher_id = %s WHERE publisher_id = %s", (target_id, source_id)
    )

    # 3. Transférer les formes de nom
    cur.execute(
        """
        UPDATE publisher_name_forms SET publisher_id = %s
        WHERE publisher_id = %s
          AND form_normalized NOT IN (
              SELECT form_normalized FROM publisher_name_forms WHERE publisher_id = %s
          )
    """,
        (target_id, source_id, target_id),
    )
    cur.execute("DELETE FROM publisher_name_forms WHERE publisher_id = %s", (source_id,))

    # 3b. Transférer les journal_name_forms référençant le publisher source
    #     Supprimer celles qui existent déjà pour le publisher cible (UNIQUE form_normalized + publisher_id)
    cur.execute(
        """
        DELETE FROM journal_name_forms
        WHERE publisher_id = %s
          AND form_normalized IN (
              SELECT form_normalized FROM journal_name_forms WHERE publisher_id = %s
          )
    """,
        (source_id, target_id),
    )
    cur.execute(
        "UPDATE journal_name_forms SET publisher_id = %s WHERE publisher_id = %s",
        (target_id, source_id),
    )

    # 4. Transférer les apc_payments
    cur.execute(
        "UPDATE apc_payments SET publisher_id = %s WHERE publisher_id = %s", (target_id, source_id)
    )

    # 5. Enrichir la cible
    # Ordre : capturer les valeurs src → NULL-er openalex_id src (pour libérer
    # la contrainte UNIQUE) → enrichir target avec les valeurs capturées → DELETE.
    cur.execute(
        "SELECT openalex_id, country, is_predatory FROM publishers WHERE id = %s",
        (source_id,),
    )
    src = cur.fetchone()
    cur.execute("UPDATE publishers SET openalex_id = NULL WHERE id = %s", (source_id,))
    cur.execute(
        """
        UPDATE publishers SET
            openalex_id = COALESCE(openalex_id, %s),
            country = COALESCE(country, %s),
            is_predatory = is_predatory OR %s,
            updated_at = now()
        WHERE id = %s
    """,
        (src["openalex_id"], src["country"], src["is_predatory"], target_id),
    )

    # 6. Supprimer la source
    cur.execute("DELETE FROM publishers WHERE id = %s", (source_id,))


def merge_journals(cur, target_id: int, source_id: int):
    """Fusionne le journal source dans le journal cible.

    1. Transfère les publications
    2. Transfère les formes de nom
    3. Transfère les apc_payments
    4. Enrichit la cible (ISSN, openalex_id, APC, flags)
    5. Supprime la source
    """
    if target_id == source_id:
        raise RuntimeError("Impossible de fusionner un journal avec lui-même")

    # 1. Transférer les publications et source_publications
    cur.execute(
        "UPDATE publications SET journal_id = %s WHERE journal_id = %s", (target_id, source_id)
    )
    cur.execute(
        "UPDATE source_publications SET journal_id = %s WHERE journal_id = %s",
        (target_id, source_id),
    )

    # 2. Transférer les formes de nom
    cur.execute(
        """
        UPDATE journal_name_forms SET journal_id = %s
        WHERE journal_id = %s
          AND (form_normalized, COALESCE(publisher_id, 0)) NOT IN (
              SELECT form_normalized, COALESCE(publisher_id, 0)
              FROM journal_name_forms WHERE journal_id = %s
          )
    """,
        (target_id, source_id, target_id),
    )
    cur.execute("DELETE FROM journal_name_forms WHERE journal_id = %s", (source_id,))

    # 3. Transférer les apc_payments
    cur.execute(
        "UPDATE apc_payments SET journal_id = %s WHERE journal_id = %s", (target_id, source_id)
    )

    # 4. Enrichir la cible
    cur.execute(
        """
        UPDATE journals dest SET
            issn = COALESCE(dest.issn, src.issn),
            eissn = COALESCE(dest.eissn, src.eissn),
            issnl = COALESCE(dest.issnl, src.issnl),
            publisher_id = COALESCE(dest.publisher_id, src.publisher_id),
            openalex_id = COALESCE(dest.openalex_id, src.openalex_id),
            is_in_doaj = dest.is_in_doaj OR src.is_in_doaj,
            is_predatory = dest.is_predatory OR src.is_predatory,
            apc_amount = COALESCE(dest.apc_amount, src.apc_amount),
            apc_currency = COALESCE(dest.apc_currency, src.apc_currency),
            oa_model = COALESCE(dest.oa_model, src.oa_model),
            updated_at = now()
        FROM journals src
        WHERE dest.id = %s AND src.id = %s
    """,
        (target_id, source_id),
    )

    # 5. Supprimer la source
    cur.execute("DELETE FROM journals WHERE id = %s", (source_id,))
