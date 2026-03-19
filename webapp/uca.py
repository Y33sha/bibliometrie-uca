"""UCA flag propagation for addresses."""


def propagate_uca_for_addresses(cur, address_ids: list[int]):
    """Recalcule is_uca sur openalex/wos_authorships et authorships
    pour tous les authorships liés aux adresses données.

    Appelé après chaque review/assign/unassign d'adresse pour
    propagation en temps réel.
    """
    if not address_ids:
        return

    # 1. Périmètre UCA
    cur.execute("""
        SELECT s.id FROM structures s WHERE s.code = 'uca'
        UNION
        SELECT sr.child_id FROM structure_relations sr
        JOIN structures s ON s.id = sr.parent_id
        WHERE s.code = 'uca' AND sr.relation_type = 'est_tutelle_de'
    """)
    uca_ids = [r["id"] for r in cur.fetchall()]
    if not uca_ids:
        return

    # 2a. Trouver les openalex_authorships affectés
    cur.execute("""
        SELECT DISTINCT oaa.openalex_authorship_id
        FROM openalex_authorship_addresses oaa
        WHERE oaa.address_id = ANY(%s)
    """, (address_ids,))
    oas_ids = [r["openalex_authorship_id"] for r in cur.fetchall()]

    # 2b. Trouver les wos_authorships affectés
    cur.execute("""
        SELECT DISTINCT waa.wos_authorship_id
        FROM wos_authorship_addresses waa
        WHERE waa.address_id = ANY(%s)
    """, (address_ids,))
    was_ids = [r["wos_authorship_id"] for r in cur.fetchall()]

    if not oas_ids and not was_ids:
        return

    # 3a. Recalculer is_uca sur openalex_authorships
    if oas_ids:
        cur.execute("""
            WITH affected AS (
                SELECT unnest(%s::int[]) AS oas_id
            ),
            uca_per_authorship AS (
                SELECT oaa.openalex_authorship_id AS oas_id,
                       array_agg(DISTINCT ast.structure_id) AS struct_ids
                FROM affected af
                JOIN openalex_authorship_addresses oaa ON oaa.openalex_authorship_id = af.oas_id
                JOIN address_structures ast ON ast.address_id = oaa.address_id
                WHERE ast.structure_id = ANY(%s)
                  AND ast.is_confirmed IS DISTINCT FROM FALSE
                GROUP BY oaa.openalex_authorship_id
            )
            UPDATE openalex_authorships oas
            SET is_uca = (upa.struct_ids IS NOT NULL),
                structure_ids = upa.struct_ids
            FROM affected af
            LEFT JOIN uca_per_authorship upa ON upa.oas_id = af.oas_id
            WHERE oas.id = af.oas_id
        """, (oas_ids, uca_ids))

    # 3b. Recalculer is_uca sur wos_authorships
    if was_ids:
        cur.execute("""
            WITH affected AS (
                SELECT unnest(%s::int[]) AS was_id
            ),
            uca_per_authorship AS (
                SELECT waa.wos_authorship_id AS was_id,
                       array_agg(DISTINCT ast.structure_id) AS struct_ids
                FROM affected af
                JOIN wos_authorship_addresses waa ON waa.wos_authorship_id = af.was_id
                JOIN address_structures ast ON ast.address_id = waa.address_id
                WHERE ast.structure_id = ANY(%s)
                  AND ast.is_confirmed IS DISTINCT FROM FALSE
                GROUP BY waa.wos_authorship_id
            )
            UPDATE wos_authorships was
            SET is_uca = (upa.struct_ids IS NOT NULL),
                structure_ids = upa.struct_ids
            FROM affected af
            LEFT JOIN uca_per_authorship upa ON upa.was_id = af.was_id
            WHERE was.id = af.was_id
        """, (was_ids, uca_ids))

    # 4. Propager vers authorships (vérité) pour les person_id résolus
    cur.execute("""
        WITH affected_pubs AS (
            SELECT DISTINCT od.publication_id, oas.person_id
            FROM openalex_authorships oas
            JOIN openalex_documents od ON od.id = oas.openalex_document_id
            WHERE oas.id = ANY(%s)
              AND od.publication_id IS NOT NULL
              AND oas.person_id IS NOT NULL
            UNION
            SELECT DISTINCT wd.publication_id, wa.person_id
            FROM wos_authorships was
            JOIN wos_documents wd ON wd.id = was.wos_document_id
            JOIN wos_authors wa ON wa.id = was.wos_author_id
            WHERE was.id = ANY(%s)
              AND wd.publication_id IS NOT NULL
              AND wa.person_id IS NOT NULL
        ),
        hal_uca AS (
            SELECT hd.publication_id, ha.person_id,
                   array_agg(DISTINCT sid) AS struct_ids
            FROM affected_pubs ap
            JOIN hal_documents hd ON hd.publication_id = ap.publication_id
            JOIN hal_authorships has ON has.hal_document_id = hd.id
            JOIN hal_authors ha ON ha.id = has.hal_author_id
                AND ha.person_id = ap.person_id,
            LATERAL unnest(has.structure_ids) AS sid
            WHERE has.is_uca = TRUE AND has.structure_ids IS NOT NULL
            GROUP BY hd.publication_id, ha.person_id
        ),
        oa_uca AS (
            SELECT od.publication_id, oas.person_id,
                   oas.structure_ids AS struct_ids
            FROM affected_pubs ap
            JOIN openalex_documents od ON od.publication_id = ap.publication_id
            JOIN openalex_authorships oas ON oas.openalex_document_id = od.id
                AND oas.person_id = ap.person_id
            WHERE oas.is_uca = TRUE AND oas.structure_ids IS NOT NULL
        ),
        wos_uca AS (
            SELECT wd.publication_id, wa.person_id,
                   was.structure_ids AS struct_ids
            FROM affected_pubs ap
            JOIN wos_documents wd ON wd.publication_id = ap.publication_id
            JOIN wos_authorships was ON was.wos_document_id = wd.id
            JOIN wos_authors wa ON wa.id = was.wos_author_id
                AND wa.person_id = ap.person_id
            WHERE was.is_uca = TRUE AND was.structure_ids IS NOT NULL
        ),
        merged AS (
            SELECT ap.publication_id, ap.person_id,
                   COALESCE(hu.struct_ids, '{}')
                       || COALESCE(ou.struct_ids, '{}')
                       || COALESCE(wu.struct_ids, '{}') AS all_structs,
                   (hu.struct_ids IS NOT NULL
                    OR ou.struct_ids IS NOT NULL
                    OR wu.struct_ids IS NOT NULL) AS any_uca
            FROM affected_pubs ap
            LEFT JOIN hal_uca hu ON hu.publication_id = ap.publication_id
                AND hu.person_id = ap.person_id
            LEFT JOIN oa_uca ou ON ou.publication_id = ap.publication_id
                AND ou.person_id = ap.person_id
            LEFT JOIN wos_uca wu ON wu.publication_id = ap.publication_id
                AND wu.person_id = ap.person_id
        )
        UPDATE authorships a
        SET is_uca = m.any_uca,
            structure_ids = NULLIF(
                (SELECT array_agg(DISTINCT x) FROM unnest(m.all_structs) AS x),
                '{}'
            ),
            updated_at = now()
        FROM merged m
        WHERE a.publication_id = m.publication_id
          AND a.person_id = m.person_id
          AND a.person_id IS NOT NULL
    """, (oas_ids or [], was_ids or []))
