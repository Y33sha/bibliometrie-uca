"""
Service Authorships vérité — accès en écriture à la table `authorships`.

Opérations unitaires sur les authorships consolidées. Le script batch
`build_authorships.py` reste le constructeur principal (reconstruction
complète), et `webapp/uca.py` gère le recalcul UCA incrémental.

Ce service encapsule les opérations ponctuelles utilisées par les routeurs
et les scripts de correction.
"""

from utils.sources import BIBLIO_SOURCES as VALID_SOURCES


def exclude_authorship(cur, authorship_id: int) -> dict | None:
    """Marque une authorship vérité comme exclue et détache les authorships sources.

    1. Marque l'authorship vérité excluded = TRUE
    2. Met person_id = NULL sur les authorships sources liées
       (pour que build_authorships ne recrée pas le lien)
    """
    cur.execute(
        """
        SELECT id, person_id FROM authorships WHERE id = %s
    """,
        (authorship_id,),
    )
    row = cur.fetchone()
    if not row:
        return None

    person_id = row["person_id"]

    # 1. Marquer exclue
    cur.execute(
        """
        UPDATE authorships SET excluded = TRUE, updated_at = now()
        WHERE id = %s RETURNING id, excluded
    """,
        (authorship_id,),
    )
    result = cur.fetchone()

    # 2. Détacher les authorships sources (person_id = NULL) et casser le lien FK
    if person_id:
        cur.execute(
            """
            UPDATE source_authorships
            SET person_id = NULL, authorship_id = NULL
            WHERE authorship_id = %s AND person_id = %s
        """,
            (authorship_id, person_id),
        )

    return result


def detach_source(cur, source_authorship_id: int, source: str):
    """Détache une authorship source de son authorship vérité.
    Si plus aucune source ne l'atteste, supprime l'authorship vérité.

    Retourne True si l'authorship vérité a été supprimée, False sinon.
    """
    if source not in VALID_SOURCES:
        raise ValueError(f"Source inconnue : {source}")

    # Trouver l'authorship vérité liée
    cur.execute(
        """
        SELECT authorship_id FROM source_authorships
        WHERE id = %s AND source = %s
    """,
        (source_authorship_id, source),
    )
    row = cur.fetchone()
    if not row or not row["authorship_id"]:
        return False

    truth_id = row["authorship_id"]

    # Détacher la FK source
    cur.execute(
        """
        UPDATE source_authorships SET authorship_id = NULL
        WHERE id = %s AND source = %s
    """,
        (source_authorship_id, source),
    )

    # Vérifier s'il reste d'autres sources
    cur.execute(
        """
        SELECT 1 FROM source_authorships
        WHERE authorship_id = %s AND NOT excluded
        LIMIT 1
    """,
        (truth_id,),
    )

    if not cur.fetchone():
        # Plus aucune source → supprimer
        cur.execute("DELETE FROM authorships WHERE id = %s", (truth_id,))
        return True

    return False


def delete_orphan_authorships(cur, person_id: int) -> int:
    """Supprime les authorships vérité d'une personne qui ne sont plus attestées
    par aucune authorship source.
    Retourne le nombre d'authorships supprimées.
    """
    cur.execute(
        """
        DELETE FROM authorships a
        WHERE a.person_id = %s
          AND NOT EXISTS (SELECT 1 FROM source_authorships sa
                          JOIN source_publications sd ON sd.id = sa.source_publication_id
                          WHERE sa.person_id = %s AND sd.publication_id = a.publication_id
                            AND NOT sa.excluded)
    """,
        (person_id, person_id),
    )
    return cur.rowcount


def move_authorships_for_source(
    cur, source: str, source_authorship_ids: list[int], from_pub_id: int, to_pub_id: int
):
    """Déplace des authorships vérité d'une publication à une autre,
    pour les authorships liées aux source_authorship_ids donnés.
    Utilisé par split_bad_merges.
    """
    if source not in VALID_SOURCES:
        raise ValueError(f"Source inconnue : {source}")

    for sa_id in source_authorship_ids:
        cur.execute(
            """
            UPDATE authorships a
            SET publication_id = %s, updated_at = now()
            FROM source_authorships sa
            WHERE sa.authorship_id = a.id
              AND sa.id = %s AND a.publication_id = %s
        """,
            (to_pub_id, sa_id, from_pub_id),
        )


def sync_person_id_from_source(cur, source: str, source_authorship_ids: list[int]):
    """Propage le person_id des authorships sources vers les authorships vérité.
    Évite les doublons (publication_id, person_id).
    Utilisé par fix_oa_person_conflicts.
    """
    if source not in VALID_SOURCES:
        raise ValueError(f"Source inconnue : {source}")

    cur.execute(
        """
        UPDATE authorships a
        SET person_id = src.person_id, updated_at = now()
        FROM source_authorships src
        WHERE src.authorship_id = a.id
          AND a.person_id IS DISTINCT FROM src.person_id
          AND src.person_id IS NOT NULL
          AND src.id = ANY(%s)
          AND NOT EXISTS (
              SELECT 1 FROM authorships a2
              WHERE a2.publication_id = a.publication_id
                AND a2.person_id = src.person_id
                AND a2.id <> a.id
          )
    """,
        (source_authorship_ids,),
    )
    return cur.rowcount


def propagate_uca_for_addresses(cur, address_ids: list[int]):
    """Recalcule in_perimeter sur source_authorships (openalex/wos) et authorships vérité
    pour tous les authorships liés aux adresses données.

    Appelé après chaque review/assign/unassign d'adresse pour
    propagation en temps réel.
    """
    if not address_ids:
        return

    # 1. Périmètre UCA
    from utils.perimeter import get_persons_structure_ids_list

    perimeter_ids = get_persons_structure_ids_list(cur)
    if not perimeter_ids:
        return

    # 2. Trouver les source_authorships (openalex/wos/scanr) affectés
    cur.execute(
        """
        SELECT DISTINCT saa.source_authorship_id
        FROM source_authorship_addresses saa
        WHERE saa.address_id = ANY(%s)
    """,
        (address_ids,),
    )
    affected_sa_ids = [r["source_authorship_id"] for r in cur.fetchall()]

    if not affected_sa_ids:
        return

    # 3. Recalculer in_perimeter sur source_authorships affectés
    cur.execute(
        """
        WITH affected AS (
            SELECT unnest(%s::int[]) AS sa_id
        ),
        uca_per_authorship AS (
            SELECT saa.source_authorship_id AS sa_id,
                   array_agg(DISTINCT ast.structure_id) AS struct_ids
            FROM affected af
            JOIN source_authorship_addresses saa ON saa.source_authorship_id = af.sa_id
            JOIN address_structures ast ON ast.address_id = saa.address_id
            WHERE ast.structure_id = ANY(%s)
              AND ast.is_confirmed IS DISTINCT FROM FALSE
            GROUP BY saa.source_authorship_id
        )
        UPDATE source_authorships sa
        SET in_perimeter = (upa.struct_ids IS NOT NULL),
            structure_ids = upa.struct_ids
        FROM affected af
        LEFT JOIN uca_per_authorship upa ON upa.sa_id = af.sa_id
        WHERE sa.id = af.sa_id
    """,
        (affected_sa_ids, perimeter_ids),
    )

    # 4. Propager vers authorships (vérité) pour les person_id résolus
    cur.execute(
        """
        WITH affected_pubs AS (
            SELECT DISTINCT sd.publication_id, sa.person_id
            FROM source_authorships sa
            JOIN source_publications sd ON sd.id = sa.source_publication_id
            WHERE sa.id = ANY(%s)
              -- toutes les sources utilisent les adresses
              AND sd.publication_id IS NOT NULL
              AND sa.person_id IS NOT NULL
        ),
        src_uca AS (
            SELECT sd.publication_id, sa.person_id, sa.source,
                   sa.structure_ids AS struct_ids
            FROM affected_pubs ap
            JOIN source_publications sd ON sd.publication_id = ap.publication_id
            JOIN source_authorships sa ON sa.source_publication_id = sd.id
                AND sa.person_id = ap.person_id
                AND sa.source = sd.source
            WHERE sa.in_perimeter = TRUE AND sa.structure_ids IS NOT NULL
        ),
        merged AS (
            SELECT ap.publication_id, ap.person_id,
                   (SELECT array_agg(DISTINCT x)
                    FROM src_uca su, unnest(su.struct_ids) AS x
                    WHERE su.publication_id = ap.publication_id
                      AND su.person_id = ap.person_id
                   ) AS all_structs,
                   EXISTS (
                       SELECT 1 FROM src_uca su
                       WHERE su.publication_id = ap.publication_id
                         AND su.person_id = ap.person_id
                   ) AS any_uca
            FROM affected_pubs ap
        )
        UPDATE authorships a
        SET in_perimeter = m.any_uca,
            structure_ids = NULLIF(m.all_structs, ARRAY[]::int[]),
            updated_at = now()
        FROM merged m
        WHERE a.publication_id = m.publication_id
          AND a.person_id = m.person_id
          AND a.person_id IS NOT NULL
    """,
        (affected_sa_ids,),
    )
