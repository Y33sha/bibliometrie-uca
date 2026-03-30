"""
Fonction unique de fusion de deux personnes.
Utilisée par l'API et par tous les scripts batch de dédoublonnage.
"""


def merge_person(cur, target_id, source_id):
    """Fusionne la personne source_id dans target_id.

    Transfère tous les auteurs liés, identifiants, authorships et person_name_forms
    de source vers target, puis supprime la personne source.

    Lève RuntimeError si les deux personnes ont chacune une fiche RH distincte.
    """
    # Garde-fou : ne JAMAIS fusionner si les deux ont une fiche RH
    cur.execute("""
        SELECT COUNT(*) AS n FROM persons_rh
        WHERE person_id IN (%s, %s)
    """, (target_id, source_id))
    if cur.fetchone()["n"] >= 2:
        raise RuntimeError(
            f"REFUS de fusion : les personnes #{target_id} et #{source_id} "
            f"ont chacune une fiche RH distincte."
        )

    # 1. Transférer les auteurs HAL (comptes avec hal_person_id)
    cur.execute("UPDATE hal_authors SET person_id = %s WHERE person_id = %s",
                (target_id, source_id))

    # 1b. Transférer les hal_authorships (source de vérité pour person_id)
    cur.execute("UPDATE hal_authorships SET person_id = %s WHERE person_id = %s",
                (target_id, source_id))

    # 2. Transférer les authorships OpenAlex
    cur.execute("UPDATE openalex_authorships SET person_id = %s WHERE person_id = %s",
                (target_id, source_id))

    # 3. Transférer les authorships WoS
    cur.execute("UPDATE wos_authorships SET person_id = %s WHERE person_id = %s",
                (target_id, source_id))

    # 4. Transférer les authorships consolidées (supprimer les doublons publication)
    cur.execute("""
        DELETE FROM authorships
        WHERE person_id = %s
          AND publication_id IN (
              SELECT publication_id FROM authorships WHERE person_id = %s
          )
    """, (source_id, target_id))
    cur.execute("UPDATE authorships SET person_id = %s WHERE person_id = %s",
                (target_id, source_id))

    # 5. Transférer les identifiants (supprimer doublons)
    cur.execute("""
        DELETE FROM person_identifiers
        WHERE person_id = %s
          AND (id_type, id_value) IN (
              SELECT id_type, id_value FROM person_identifiers WHERE person_id = %s
          )
    """, (source_id, target_id))
    cur.execute("UPDATE person_identifiers SET person_id = %s WHERE person_id = %s",
                (target_id, source_id))

    # 6. Transférer persons_rh de la source vers la cible (si la cible n'en a pas)
    cur.execute("""
        UPDATE persons_rh SET person_id = %s
        WHERE person_id = %s
          AND NOT EXISTS (SELECT 1 FROM persons_rh WHERE person_id = %s)
    """, (target_id, source_id, target_id))

    # 7. Mettre à jour person_name_forms : remplacer source_id par target_id
    cur.execute("""
        UPDATE person_name_forms
        SET person_ids = (
                SELECT array_agg(DISTINCT v ORDER BY v)
                FROM unnest(array_replace(person_ids, %s, %s)) AS v
            ),
            updated_at = now()
        WHERE %s = ANY(person_ids)
    """, (source_id, target_id, source_id))

    # 8. Supprimer la personne source
    cur.execute("DELETE FROM persons WHERE id = %s", (source_id,))
