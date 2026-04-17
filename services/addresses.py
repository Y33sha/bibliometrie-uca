"""
Service Addresses — accès exclusif en écriture aux tables `addresses`,
`address_structures`, et propagation des pays vers les publications.

Les routers passent par ces fonctions pour toute écriture sur les adresses.
Les lectures restent autorisées dans les routers (convention du projet).
"""

import logging

from psycopg2.extras import execute_values

from services.authorships import propagate_uca_for_addresses

logger = logging.getLogger(__name__)


# ── Validation des liens adresse ↔ structure ──────────────────────


def review_structure_link(cur, address_id: int, structure_id: int,
                           is_confirmed: bool | None) -> None:
    """Upsert le lien address ↔ structure (validation manuelle).

    - is_confirmed = True  → confirme (crée le lien si besoin)
    - is_confirmed = False → rejette (crée le lien si besoin)
    - is_confirmed = None  → reset (supprime le lien manuel, remet l'auto à NULL)

    Propage automatiquement l'UCA aux source_authorships et authorships vérité
    (via services.authorships.propagate_uca_for_addresses).
    """
    if is_confirmed is None:
        # Reset : retirer le lien manuel (sans matched_form_id), puis remettre
        # is_confirmed à NULL pour les liens auto-détectés restants.
        cur.execute(
            """
            DELETE FROM address_structures
            WHERE address_id = %s AND structure_id = %s AND matched_form_id IS NULL
            """,
            (address_id, structure_id),
        )
        cur.execute(
            """
            UPDATE address_structures SET is_confirmed = NULL
            WHERE address_id = %s AND structure_id = %s
            """,
            (address_id, structure_id),
        )
    else:
        cur.execute(
            """
            INSERT INTO address_structures (address_id, structure_id, is_confirmed)
            VALUES (%s, %s, %s)
            ON CONFLICT (address_id, structure_id) DO UPDATE
                SET is_confirmed = EXCLUDED.is_confirmed
            """,
            (address_id, structure_id, is_confirmed),
        )

    propagate_uca_for_addresses(cur, [address_id])


def batch_review_structure_link(cur, address_ids: list[int], structure_id: int,
                                 is_confirmed: bool | None) -> int:
    """Comme review_structure_link mais sur un lot d'adresses.

    Retourne le nombre d'adresses touchées (pour les reset, nombre de lignes
    UPDATEes ; pour les upserts, taille du lot passé).
    """
    if not address_ids:
        return 0

    if is_confirmed is None:
        cur.execute(
            """
            DELETE FROM address_structures
            WHERE address_id = ANY(%s) AND structure_id = %s AND matched_form_id IS NULL
            """,
            (address_ids, structure_id),
        )
        cur.execute(
            """
            UPDATE address_structures SET is_confirmed = NULL
            WHERE address_id = ANY(%s) AND structure_id = %s
            """,
            (address_ids, structure_id),
        )
        updated = cur.rowcount
    else:
        execute_values(
            cur,
            """
            INSERT INTO address_structures (address_id, structure_id, is_confirmed)
            VALUES %s
            ON CONFLICT (address_id, structure_id) DO UPDATE
                SET is_confirmed = EXCLUDED.is_confirmed
            """,
            [(aid, structure_id, is_confirmed) for aid in address_ids],
        )
        updated = len(address_ids)

    propagate_uca_for_addresses(cur, address_ids)
    return updated


def unassign_manual_structure(cur, address_id: int, structure_id: int) -> bool:
    """Supprime uniquement le lien manuel (matched_form_id IS NULL) entre
    une adresse et une structure. Les liens auto-détectés et leurs is_confirmed
    ne sont pas touchés (contrairement à review_structure_link(None)).

    Propage automatiquement l'UCA.
    Retourne True si un lien manuel a été supprimé, False sinon.
    """
    cur.execute(
        """
        DELETE FROM address_structures
        WHERE address_id = %s AND structure_id = %s AND matched_form_id IS NULL
        """,
        (address_id, structure_id),
    )
    deleted = cur.rowcount > 0
    propagate_uca_for_addresses(cur, [address_id])
    return deleted


# ── Attribution des pays ──────────────────────────────────────────


def _propagate_to_similar_addresses(cur, address_id: int) -> list[int]:
    """Réplique addresses.countries d'une adresse vers toutes les adresses
    partageant le même normalized_text (len >= 5).

    Retourne la liste des IDs propagés (sans l'adresse source).
    """
    cur.execute(
        """
        UPDATE addresses a2
        SET countries = a1.countries
        FROM addresses a1
        WHERE a1.id = %s
          AND a2.normalized_text = a1.normalized_text
          AND a2.id <> a1.id
          AND LENGTH(a2.normalized_text) >= 5
        RETURNING a2.id
        """,
        (address_id,),
    )
    return [r["id"] for r in cur.fetchall()]


def set_country(cur, address_id: int, countries: list[str] | None) -> list[int]:
    """Attribue une liste de pays à une adresse.

    - `countries=None` ou `[]` → remet la colonne à NULL.
    - Propage la même valeur aux adresses partageant le même normalized_text.

    Retourne la liste des IDs affectés (y compris address_id).
    Ne valide pas les codes pays : c'est au caller de le faire.
    """
    cur.execute(
        "UPDATE addresses SET countries = %s WHERE id = %s",
        (countries if countries else None, address_id),
    )
    affected = [address_id]
    if countries:
        affected.extend(_propagate_to_similar_addresses(cur, address_id))
    return affected


def batch_set_country_by_ids(cur, country_code: str, address_ids: list[int]) -> list[int]:
    """Ajoute `country_code` à `addresses.countries` pour la liste d'IDs donnée.

    - Si `countries` est NULL → le crée à [country_code].
    - Si `country_code` est déjà dans `countries` → no-op.
    - Sinon → append.

    Retourne les IDs effectivement modifiés (= tous ceux passés en entrée).
    """
    cur.execute(
        """
        UPDATE addresses
        SET countries = CASE
            WHEN countries IS NULL THEN ARRAY[%s]::char(2)[]
            WHEN %s = ANY(countries) THEN countries
            ELSE array_append(countries, %s::char(2))
        END
        WHERE id = ANY(%s)
        RETURNING id
        """,
        (country_code, country_code, country_code, address_ids),
    )
    return [r["id"] for r in cur.fetchall()]


def batch_set_country_by_filter(
    cur,
    country_code: str,
    *,
    search: str | None = None,
    has_country: str | None = None,
    country_code_filter: str | None = None,
    suggested_country: str | None = None,
) -> list[int]:
    """Ajoute `country_code` à toutes les adresses correspondant aux filtres.

    Filtres combinés en AND (tous doivent matcher). Si aucun filtre n'est
    fourni, applique à TOUTES les adresses (use with caution).

    Retourne les IDs modifiés.
    """
    conditions: list[str] = []
    params: list = []
    if search:
        conditions.append("unaccent(raw_text) ILIKE unaccent(%s)")
        params.append(f"%{search}%")
    if has_country == "yes":
        conditions.append("countries IS NOT NULL")
    elif has_country == "no":
        conditions.append("countries IS NULL")
    if country_code_filter:
        conditions.append("%s = ANY(countries)")
        params.append(country_code_filter)
    if suggested_country:
        conditions.append("%s = ANY(suggested_countries)")
        params.append(suggested_country)

    where = " AND ".join(conditions) if conditions else "TRUE"

    cur.execute(
        f"""
        UPDATE addresses
        SET countries = CASE
            WHEN countries IS NULL THEN ARRAY[%s]::char(2)[]
            WHEN %s = ANY(countries) THEN countries
            ELSE array_append(countries, %s::char(2))
        END
        WHERE {where}
        RETURNING id
        """,
        [country_code, country_code, country_code] + params,
    )
    return [r["id"] for r in cur.fetchall()]


def propagate_countries_to_similar(cur) -> list[int]:
    """Propage addresses.countries vers toutes les adresses partageant le même
    normalized_text, quand l'autre adresse a des countries différents.

    Appelée après un batch_set_country_by_* pour propager à travers tout le
    référentiel d'adresses. Retourne les IDs propagés.
    """
    cur.execute(
        """
        UPDATE addresses a2
        SET countries = a1.countries
        FROM addresses a1
        WHERE a1.countries IS NOT NULL
          AND a2.normalized_text = a1.normalized_text
          AND a2.countries IS DISTINCT FROM a1.countries
          AND LENGTH(a2.normalized_text) >= 5
          AND a2.id <> a1.id
        RETURNING a2.id
        """,
    )
    return [r["id"] for r in cur.fetchall()]


# ── Propagation pays vers source_publications et publications ────


def propagate_countries_to_publications(cur, address_ids: list[int]) -> None:
    """Propage addresses.countries → source_publications.countries → publications.countries.

    Appelée après une modification de pays sur les adresses (typiquement en
    background task). Recalcule par agrégation, idempotent.
    """
    if not address_ids:
        return

    # 1. Recalculer countries des source_publications concernés.
    # Cast c::text nécessaire car addresses.countries est char(2)[] alors que
    # source_publications.countries est text[] — l'IS DISTINCT FROM planterait
    # sinon sur "operator does not exist: text[] = character[]".
    cur.execute(
        """
        UPDATE source_publications sd
        SET countries = sub.new_countries
        FROM (
            SELECT sa.source_publication_id AS doc_id,
                   (SELECT array_agg(DISTINCT c::text ORDER BY c::text)
                    FROM source_authorship_addresses saa2
                    JOIN addresses a2 ON a2.id = saa2.address_id
                    JOIN source_authorships sa2 ON sa2.id = saa2.source_authorship_id,
                    LATERAL unnest(a2.countries) AS c
                    WHERE sa2.source_publication_id = sa.source_publication_id
                      AND a2.countries IS NOT NULL
                   ) AS new_countries
            FROM source_authorship_addresses saa
            JOIN source_authorships sa ON sa.id = saa.source_authorship_id
            WHERE saa.address_id = ANY(%s)
            GROUP BY sa.source_publication_id
        ) sub
        WHERE sd.id = sub.doc_id
          AND sd.countries IS DISTINCT FROM sub.new_countries
        """,
        (address_ids,),
    )
    addr_docs = cur.rowcount

    # 2. Recalculer publications.countries (maintenant que source_publications est à jour)
    cur.execute(
        """
        WITH affected_pubs AS (
            SELECT DISTINCT sd.publication_id
            FROM source_authorship_addresses saa
            JOIN source_authorships sa ON sa.id = saa.source_authorship_id
            JOIN source_publications sd ON sd.id = sa.source_publication_id
            WHERE saa.address_id = ANY(%s) AND sd.publication_id IS NOT NULL
        )
        UPDATE publications p
        SET countries = sub.all_countries
        FROM (
            SELECT ap.publication_id,
                   (SELECT array_agg(DISTINCT c::text ORDER BY c::text)
                    FROM source_publications sd,
                    LATERAL unnest(sd.countries) AS c
                    WHERE sd.publication_id = ap.publication_id
                      AND sd.countries IS NOT NULL
                   ) AS all_countries
            FROM affected_pubs ap
        ) sub
        WHERE p.id = sub.publication_id
          AND p.countries IS DISTINCT FROM sub.all_countries
        """,
        (address_ids,),
    )
    pubs = cur.rowcount

    if addr_docs or pubs:
        logger.info(f"Propagation pays : {addr_docs} docs source, {pubs} publications")
