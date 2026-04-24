"""Query service : lectures pour `create_persons_from_source_authorships`.

Appelé par `application/pipeline/create/create_persons_from_source_authorships.py`.
Regroupe les SELECT nécessaires aux 4 passes de rattachement
(comptes HAL, cross-source, IdRef/ORCID connus, lookup `person_name_forms`).
"""

from typing import Any

from domain.sources import SOURCES_WITH_STRUCTURED_NAMES_SQL
from infrastructure.db_helpers import rows_as_dicts


def fetch_unlinked_authorships(cur: Any) -> list[dict[str, Any]]:
    """Liste tous les `source_authorships` in-perimeter non rattachés à une
    `person`, toutes sources confondues (HAL, OpenAlex, WoS, ScanR, theses).

    Une seule requête (un seul round-trip DB) — les différences sémantiques
    entre sources sont portées par des CASE expressions :

    - `last_name` / `first_name` / `orcid` : NULL pour OpenAlex (entités OA
      non fiables, cf. MEMORY — le caller applique `parse_raw_author_name`).
    - `idhal`, `source_person_id`, `has_hal_person_id`, `hal_person_id` :
      renseignés uniquement pour HAL (dual-write sur `hal_authorships.person_id`).
    - `idref` : renseigné pour ScanR et theses.
    - `oa_orcid` / `oa_full_name` : exposés pour OpenAlex uniquement, pour
      permettre au caller la vérification de compatibilité des noms.
    - `roles` : renseigné pour theses uniquement (distingue auteur vs
      directeur de thèse).

    Filtre supplémentaire : OpenAlex exclu des lignes avec
    `raw_author_name IS NULL` (pas de nom utilisable sans `source_persons`).

    Remplace 5 fonctions quasi-identiques (ancienne dette : copier-coller
    par source). Les colonnes sont la réunion des SELECT par source — si
    une colonne n'est pas significative pour la source, elle vaut NULL.
    """
    cur.execute("""
        SELECT sa_auth.id AS authorship_id,
               sa_auth.source AS source,
               sa_auth.raw_author_name AS full_name,
               CASE WHEN sa_auth.source = 'openalex' THEN NULL::text
                    ELSE sa.last_name END AS last_name,
               CASE WHEN sa_auth.source = 'openalex' THEN NULL::text
                    ELSE sa.first_name END AS first_name,
               CASE WHEN sa_auth.source = 'openalex' THEN NULL::text
                    ELSE sa.orcid END AS orcid,
               CASE WHEN sa_auth.source = 'hal'
                    THEN sa.source_ids->>'idhal' ELSE NULL::text END AS idhal,
               sa.idref,
               CASE WHEN sa_auth.source = 'hal' THEN sa.id
                    ELSE NULL::int END AS source_person_id,
               CASE WHEN sa_auth.source = 'hal'
                    THEN ((sa.source_ids->>'hal_person_id') IS NOT NULL)
                    ELSE FALSE END AS has_hal_person_id,
               CASE WHEN sa_auth.source = 'hal'
                    THEN (sa.source_ids->>'hal_person_id')::int
                    ELSE NULL::int END AS hal_person_id,
               CASE WHEN sa_auth.source = 'openalex' THEN sa.orcid
                    ELSE NULL::text END AS oa_orcid,
               CASE WHEN sa_auth.source = 'openalex' THEN sa.full_name
                    ELSE NULL::text END AS oa_full_name,
               CASE WHEN sa_auth.source = 'theses' THEN sa_auth.roles
                    ELSE NULL END AS roles,
               sd.publication_id,
               sa_auth.author_position
        FROM source_authorships sa_auth
        JOIN source_persons sa ON sa.id = sa_auth.source_person_id
        JOIN source_publications sd ON sd.id = sa_auth.source_publication_id
        JOIN v_active_publications vap ON vap.id = sd.publication_id
        WHERE sa_auth.person_id IS NULL
          AND sa_auth.in_perimeter = TRUE
          AND sd.publication_id IS NOT NULL
          AND (sa_auth.source != 'openalex' OR sa_auth.raw_author_name IS NOT NULL)
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

    def fetch_unlinked_authorships(self, cur: Any) -> list[dict[str, Any]]:
        return fetch_unlinked_authorships(cur)

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
