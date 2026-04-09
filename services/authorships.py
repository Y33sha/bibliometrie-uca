"""
Service Authorships vérité — accès en écriture à la table `authorships`.

Opérations unitaires sur les authorships consolidées. Le script batch
`build_authorships.py` reste le constructeur principal (reconstruction
complète), et `webapp/uca.py` gère le recalcul UCA incrémental.

Ce service encapsule les opérations ponctuelles utilisées par les routeurs
et les scripts de correction.
"""

# Config par source : table source, FK dans authorships
_SOURCE_CONFIG = {
    "hal": {
        "authorship_table": "hal_authorships",
        "truth_fk": "hal_authorship_id",
    },
    "openalex": {
        "authorship_table": "openalex_authorships",
        "truth_fk": "openalex_authorship_id",
    },
    "wos": {
        "authorship_table": "wos_authorships",
        "truth_fk": "wos_authorship_id",
    },
}

ALL_TRUTH_FKS = [cfg["truth_fk"] for cfg in _SOURCE_CONFIG.values()]


def exclude_authorship(cur, authorship_id: int) -> dict | None:
    """Marque une authorship vérité comme exclue et détache les authorships sources.

    1. Marque l'authorship vérité excluded = TRUE
    2. Met person_id = NULL sur les authorships sources liées
       (pour que build_authorships ne recrée pas le lien)
    """
    cur.execute("""
        SELECT id, person_id, hal_authorship_id, openalex_authorship_id, wos_authorship_id
        FROM authorships WHERE id = %s
    """, (authorship_id,))
    row = cur.fetchone()
    if not row:
        return None

    person_id = row["person_id"]

    # 1. Marquer exclue
    cur.execute("""
        UPDATE authorships SET excluded = TRUE, updated_at = now()
        WHERE id = %s RETURNING id, excluded
    """, (authorship_id,))
    result = cur.fetchone()

    # 2. Détacher les authorships sources (person_id = NULL)
    if person_id:
        for source, cfg in _SOURCE_CONFIG.items():
            fk = cfg["truth_fk"]
            source_id = row.get(fk)
            if source_id:
                cur.execute(f"""
                    UPDATE {cfg['authorship_table']}
                    SET person_id = NULL
                    WHERE id = %s AND person_id = %s
                """, (source_id, person_id))

    return result


def detach_source(cur, authorship_id: int, source: str):
    """Détache une FK source d'une authorship vérité.
    Si plus aucune source ne l'atteste, supprime l'authorship.

    Retourne True si l'authorship a été supprimée, False sinon.
    """
    cfg = _SOURCE_CONFIG.get(source)
    if not cfg:
        raise ValueError(f"Source inconnue : {source}")

    fk_col = cfg["truth_fk"]

    # Détacher la FK source
    cur.execute(f"""
        UPDATE authorships SET {fk_col} = NULL, updated_at = now()
        WHERE {fk_col} = %s
        RETURNING id
    """, (authorship_id,))
    row = cur.fetchone()
    if not row:
        return False

    truth_id = row["id"]

    # Vérifier s'il reste d'autres sources
    checks = " AND ".join(f"{fk} IS NULL" for fk in ALL_TRUTH_FKS)
    cur.execute(f"""
        SELECT 1 FROM authorships WHERE id = %s AND {checks}
    """, (truth_id,))

    if cur.fetchone():
        # Plus aucune source → supprimer
        cur.execute("DELETE FROM authorships WHERE id = %s", (truth_id,))
        return True

    return False


def delete_orphan_authorships(cur, person_id: int) -> int:
    """Supprime les authorships vérité d'une personne qui ne sont plus attestées
    par aucune authorship source.
    Retourne le nombre d'authorships supprimées.
    """
    cur.execute("""
        DELETE FROM authorships a
        WHERE a.person_id = %s
          AND NOT EXISTS (SELECT 1 FROM hal_authorships has
                          JOIN source_documents sd ON sd.id = has.source_document_id
                          WHERE has.person_id = %s AND sd.publication_id = a.publication_id
                            AND NOT has.excluded)
          AND NOT EXISTS (SELECT 1 FROM openalex_authorships oas
                          JOIN source_documents sd ON sd.id = oas.source_document_id
                          WHERE oas.person_id = %s AND sd.publication_id = a.publication_id
                            AND NOT oas.excluded)
          AND NOT EXISTS (SELECT 1 FROM wos_authorships was
                          JOIN source_documents sd ON sd.id = was.source_document_id
                          WHERE was.person_id = %s AND sd.publication_id = a.publication_id
                            AND NOT was.excluded)
    """, (person_id, person_id, person_id, person_id))
    return cur.rowcount


def move_authorships_for_source(cur, source: str, source_authorship_ids: list[int],
                                from_pub_id: int, to_pub_id: int):
    """Déplace des authorships vérité d'une publication à une autre,
    pour les authorships liées aux source_authorship_ids donnés.
    Utilisé par split_bad_merges.
    """
    cfg = _SOURCE_CONFIG.get(source)
    if not cfg:
        raise ValueError(f"Source inconnue : {source}")

    fk_col = cfg["truth_fk"]
    for said in source_authorship_ids:
        cur.execute(f"""
            UPDATE authorships a
            SET publication_id = %s, updated_at = now()
            WHERE a.{fk_col} = %s AND a.publication_id = %s
        """, (to_pub_id, said, from_pub_id))


def sync_person_id_from_source(cur, source: str, source_authorship_ids: list[int]):
    """Propage le person_id des authorships sources vers les authorships vérité.
    Évite les doublons (publication_id, person_id).
    Utilisé par fix_oa_person_conflicts.
    """
    cfg = _SOURCE_CONFIG.get(source)
    if not cfg:
        raise ValueError(f"Source inconnue : {source}")

    fk_col = cfg["truth_fk"]
    auth_tbl = cfg["authorship_table"]

    cur.execute(f"""
        UPDATE authorships a
        SET person_id = src.person_id, updated_at = now()
        FROM {auth_tbl} src
        WHERE a.{fk_col} = src.id
          AND a.person_id IS DISTINCT FROM src.person_id
          AND src.person_id IS NOT NULL
          AND src.id = ANY(%s)
          AND NOT EXISTS (
              SELECT 1 FROM authorships a2
              WHERE a2.publication_id = a.publication_id
                AND a2.person_id = src.person_id
                AND a2.id <> a.id
          )
    """, (source_authorship_ids,))
    return cur.rowcount


def propagate_uca_for_addresses(cur, address_ids: list[int]):
    """Recalcule is_uca sur openalex/wos_authorships et authorships vérité
    pour tous les authorships liés aux adresses données.

    Appelé après chaque review/assign/unassign d'adresse pour
    propagation en temps réel.
    """
    if not address_ids:
        return

    # 1. Périmètre UCA
    from utils.uca_perimeter import get_uca_structure_ids_list
    uca_ids = get_uca_structure_ids_list(cur)
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
            SELECT DISTINCT sd.publication_id, oas.person_id
            FROM openalex_authorships oas
            JOIN source_documents sd ON sd.id = oas.source_document_id
            WHERE oas.id = ANY(%s)
              AND sd.publication_id IS NOT NULL
              AND oas.person_id IS NOT NULL
            UNION
            SELECT DISTINCT sd.publication_id, was.person_id
            FROM wos_authorships was
            JOIN source_documents sd ON sd.id = was.source_document_id
            WHERE was.id = ANY(%s)
              AND sd.publication_id IS NOT NULL
              AND was.person_id IS NOT NULL
        ),
        hal_uca AS (
            SELECT sd.publication_id, has.person_id,
                   array_agg(DISTINCT sid) AS struct_ids
            FROM affected_pubs ap
            JOIN source_documents sd ON sd.publication_id = ap.publication_id
                AND sd.source = 'hal'
            JOIN hal_authorships has ON has.source_document_id = sd.id
                AND has.person_id = ap.person_id,
            LATERAL unnest(has.structure_ids) AS sid
            WHERE has.is_uca = TRUE AND has.structure_ids IS NOT NULL
            GROUP BY sd.publication_id, has.person_id
        ),
        oa_uca AS (
            SELECT sd.publication_id, oas.person_id,
                   oas.structure_ids AS struct_ids
            FROM affected_pubs ap
            JOIN source_documents sd ON sd.publication_id = ap.publication_id
                AND sd.source = 'openalex'
            JOIN openalex_authorships oas ON oas.source_document_id = sd.id
                AND oas.person_id = ap.person_id
            WHERE oas.is_uca = TRUE AND oas.structure_ids IS NOT NULL
        ),
        wos_uca AS (
            SELECT sd.publication_id, was.person_id,
                   was.structure_ids AS struct_ids
            FROM affected_pubs ap
            JOIN source_documents sd ON sd.publication_id = ap.publication_id
                AND sd.source = 'wos'
            JOIN wos_authorships was ON was.source_document_id = sd.id
                AND was.person_id = ap.person_id
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
