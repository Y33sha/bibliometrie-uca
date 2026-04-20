"""Query service : lectures pour `create_persons_from_source_authorships`.

Appelé par `application/pipeline/create/create_persons_from_source_authorships.py`.
Regroupe les SELECT nécessaires aux 4 passes de rattachement
(comptes HAL, cross-source, IdRef/ORCID connus, lookup `person_name_forms`).
"""

from typing import Any

from domain.sources import SOURCES_WITH_STRUCTURED_NAMES_SQL
from infrastructure.db_helpers import rows_as_dicts


def fetch_unlinked_hal_authorships(cur: Any) -> list[dict[str, Any]]:
    """`source_authorships` HAL in-perimeter non rattachées avec infos compte HAL."""
    cur.execute("""
        SELECT sa_auth.id AS authorship_id, 'hal' AS source,
               sa_auth.raw_author_name AS full_name, sa.last_name, sa.first_name,
               sa.orcid,
               sa.source_ids->>'idhal' AS idhal,
               sa.idref,
               sa.id AS source_person_id,
               ((sa.source_ids->>'hal_person_id') IS NOT NULL) AS has_hal_person_id,
               (sa.source_ids->>'hal_person_id')::int AS hal_person_id,
               sd.publication_id,
               sa_auth.author_position
        FROM source_authorships sa_auth
        JOIN source_persons sa ON sa.id = sa_auth.source_person_id
        JOIN source_publications sd ON sd.id = sa_auth.source_publication_id
        JOIN v_active_publications vap ON vap.id = sd.publication_id
        WHERE sa_auth.source = 'hal'
          AND sa_auth.person_id IS NULL
          AND sa_auth.in_perimeter = TRUE
          AND sd.publication_id IS NOT NULL
    """)
    return rows_as_dicts(cur)


def fetch_unlinked_openalex_authorships(cur: Any) -> list[dict[str, Any]]:
    """`source_authorships` OpenAlex in-perimeter non rattachées (avec ORCID OA brut)."""
    cur.execute("""
        SELECT sa_auth.id AS authorship_id, 'openalex' AS source,
               sa_auth.raw_author_name AS full_name,
               NULL::text AS last_name, NULL::text AS first_name,
               sa.orcid AS oa_orcid, sa.full_name AS oa_full_name,
               NULL::text AS idhal,
               NULL::int AS source_person_id,
               FALSE AS has_hal_person_id,
               NULL::int AS hal_person_id,
               sd.publication_id,
               sa_auth.author_position
        FROM source_authorships sa_auth
        JOIN source_persons sa ON sa.id = sa_auth.source_person_id
        JOIN source_publications sd ON sd.id = sa_auth.source_publication_id
        JOIN v_active_publications vap ON vap.id = sd.publication_id
        WHERE sa_auth.source = 'openalex'
          AND sa_auth.person_id IS NULL
          AND sa_auth.in_perimeter = TRUE
          AND sa_auth.raw_author_name IS NOT NULL
          AND sd.publication_id IS NOT NULL
    """)
    return rows_as_dicts(cur)


def fetch_unlinked_wos_authorships(cur: Any) -> list[dict[str, Any]]:
    """`source_authorships` WoS in-perimeter non rattachées."""
    cur.execute("""
        SELECT sa_auth.id AS authorship_id, 'wos' AS source,
               sa_auth.raw_author_name AS full_name, sa.last_name, sa.first_name,
               sa.orcid, NULL::text AS idhal,
               NULL::int AS source_person_id,
               FALSE AS has_hal_person_id,
               NULL::int AS hal_person_id,
               sd.publication_id,
               sa_auth.author_position
        FROM source_authorships sa_auth
        JOIN source_persons sa ON sa.id = sa_auth.source_person_id
        JOIN source_publications sd ON sd.id = sa_auth.source_publication_id
        JOIN v_active_publications vap ON vap.id = sd.publication_id
        WHERE sa_auth.source = 'wos'
          AND sa_auth.person_id IS NULL
          AND sa_auth.in_perimeter = TRUE
          AND sd.publication_id IS NOT NULL
    """)
    return rows_as_dicts(cur)


def fetch_unlinked_scanr_authorships(cur: Any) -> list[dict[str, Any]]:
    """`source_authorships` ScanR in-perimeter non rattachées (avec idref)."""
    cur.execute("""
        SELECT sa_auth.id AS authorship_id, 'scanr' AS source,
               sa_auth.raw_author_name AS full_name, sa.last_name, sa.first_name,
               sa.orcid, NULL::text AS idhal, sa.idref,
               NULL::int AS source_person_id,
               FALSE AS has_hal_person_id,
               NULL::int AS hal_person_id,
               sd.publication_id,
               sa_auth.author_position
        FROM source_authorships sa_auth
        JOIN source_persons sa ON sa.id = sa_auth.source_person_id
        JOIN source_publications sd ON sd.id = sa_auth.source_publication_id
        JOIN v_active_publications vap ON vap.id = sd.publication_id
        WHERE sa_auth.source = 'scanr'
          AND sa_auth.person_id IS NULL
          AND sa_auth.in_perimeter = TRUE
          AND sd.publication_id IS NOT NULL
    """)
    return rows_as_dicts(cur)


def fetch_unlinked_theses_authorships(cur: Any) -> list[dict[str, Any]]:
    """`source_authorships` theses.fr in-perimeter non rattachées (avec roles)."""
    cur.execute("""
        SELECT sa_auth.id AS authorship_id, 'theses' AS source,
               sa_auth.raw_author_name AS full_name, sa.last_name, sa.first_name,
               sa.orcid, NULL::text AS idhal, sa.idref,
               NULL::int AS source_person_id,
               FALSE AS has_hal_person_id,
               NULL::int AS hal_person_id,
               sd.publication_id,
               sa_auth.author_position,
               sa_auth.roles
        FROM source_authorships sa_auth
        JOIN source_persons sa ON sa.id = sa_auth.source_person_id
        JOIN source_publications sd ON sd.id = sa_auth.source_publication_id
        JOIN v_active_publications vap ON vap.id = sd.publication_id
        WHERE sa_auth.source = 'theses'
          AND sa_auth.person_id IS NULL
          AND sa_auth.in_perimeter = TRUE
          AND sd.publication_id IS NOT NULL
    """)
    return rows_as_dicts(cur)


def fetch_linked_authorships_structured(cur: Any) -> list[dict[str, Any]]:
    """`source_authorships` rattachées pour les sources avec noms structurés
    (HAL/WoS/ScanR/theses : `source_persons.last_name`/`first_name`)."""
    cur.execute(f"""
        SELECT sa_auth.person_id, sa_auth.author_position,
               sd.publication_id,
               sa.last_name, sa.first_name, sa_auth.raw_author_name AS full_name,
               sa_auth.source
        FROM source_authorships sa_auth
        JOIN source_persons sa ON sa.id = sa_auth.source_person_id
        JOIN source_publications sd ON sd.id = sa_auth.source_publication_id
        WHERE sa_auth.source IN {SOURCES_WITH_STRUCTURED_NAMES_SQL}
          AND sa_auth.person_id IS NOT NULL
          AND sd.publication_id IS NOT NULL
    """)
    return rows_as_dicts(cur)


def fetch_linked_authorships_openalex(cur: Any) -> list[dict[str, Any]]:
    """`source_authorships` rattachées pour OpenAlex (nom via raw_author_name)."""
    cur.execute("""
        SELECT sa_auth.person_id, sa_auth.author_position,
               sd.publication_id,
               sa_auth.raw_author_name AS full_name,
               'openalex' AS source
        FROM source_authorships sa_auth
        JOIN source_publications sd ON sd.id = sa_auth.source_publication_id
        WHERE sa_auth.source = 'openalex'
          AND sa_auth.person_id IS NOT NULL
          AND sd.publication_id IS NOT NULL
    """)
    return rows_as_dicts(cur)


def fetch_hal_account_to_person_map(cur: Any) -> dict[int, int]:
    """`{hal_person_id: person_id}` pour les comptes HAL déjà rattachés."""
    cur.execute("""
        SELECT (sa.source_ids->>'hal_person_id')::int AS hal_person_id, sa.person_id
        FROM source_persons sa
        WHERE sa.source = 'hal'
          AND (sa.source_ids->>'hal_person_id') IS NOT NULL
          AND sa.person_id IS NOT NULL
    """)
    return {r["hal_person_id"]: r["person_id"] for r in rows_as_dicts(cur)}


def fetch_idref_to_person_map(cur: Any) -> dict[str, int]:
    """`{idref: person_id}` pour les IdRef connus non rejetés."""
    cur.execute("""
        SELECT id_value, person_id
        FROM person_identifiers
        WHERE id_type = 'idref'
          AND status != 'rejected'
    """)
    return {r["id_value"]: r["person_id"] for r in rows_as_dicts(cur)}


def fetch_orcid_to_person_map(cur: Any) -> dict[str, int]:
    """`{orcid: person_id}` pour les ORCID connus non rejetés."""
    cur.execute("""
        SELECT id_value, person_id
        FROM person_identifiers
        WHERE id_type = 'orcid'
          AND status != 'rejected'
    """)
    return {r["id_value"]: r["person_id"] for r in rows_as_dicts(cur)}


def fetch_name_form_map(cur: Any) -> dict[str, list[int]]:
    """Charge `person_name_forms` sous forme `{name_form: [person_id, ...]}`."""
    cur.execute("SELECT name_form, person_ids FROM person_name_forms")
    return {r["name_form"]: r["person_ids"] for r in rows_as_dicts(cur)}


class PgPersonsCreateQueries:
    """Adapter PostgreSQL pour `application.ports.persons_create.PersonsCreateQueries`."""

    def fetch_unlinked_hal_authorships(self, cur: Any) -> list[dict[str, Any]]:
        return fetch_unlinked_hal_authorships(cur)

    def fetch_unlinked_openalex_authorships(self, cur: Any) -> list[dict[str, Any]]:
        return fetch_unlinked_openalex_authorships(cur)

    def fetch_unlinked_wos_authorships(self, cur: Any) -> list[dict[str, Any]]:
        return fetch_unlinked_wos_authorships(cur)

    def fetch_unlinked_scanr_authorships(self, cur: Any) -> list[dict[str, Any]]:
        return fetch_unlinked_scanr_authorships(cur)

    def fetch_unlinked_theses_authorships(self, cur: Any) -> list[dict[str, Any]]:
        return fetch_unlinked_theses_authorships(cur)

    def fetch_linked_authorships_structured(self, cur: Any) -> list[dict[str, Any]]:
        return fetch_linked_authorships_structured(cur)

    def fetch_linked_authorships_openalex(self, cur: Any) -> list[dict[str, Any]]:
        return fetch_linked_authorships_openalex(cur)

    def fetch_hal_account_to_person_map(self, cur: Any) -> dict[int, int]:
        return fetch_hal_account_to_person_map(cur)

    def fetch_idref_to_person_map(self, cur: Any) -> dict[str, int]:
        return fetch_idref_to_person_map(cur)

    def fetch_orcid_to_person_map(self, cur: Any) -> dict[str, int]:
        return fetch_orcid_to_person_map(cur)

    def fetch_name_form_map(self, cur: Any) -> dict[str, list[int]]:
        return fetch_name_form_map(cur)
