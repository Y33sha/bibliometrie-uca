"""Query service : lectures pour `create_persons_from_source_authorships`.

Appelé par `application/pipeline/create/create_persons_from_source_authorships.py`.
Regroupe les SELECT nécessaires aux 4 passes de rattachement
(comptes HAL, cross-source, IdRef/ORCID connus, lookup `person_name_forms`).
"""

from typing import Any

from sqlalchemy import Connection, text


def fetch_unlinked_authorships(conn: Connection) -> list[dict[str, Any]]:
    """Liste tous les `source_authorships` in-perimeter non rattachés à une
    `person`, toutes sources confondues (HAL, OpenAlex, WoS, ScanR, theses).

    Une seule requête (un seul round-trip DB) — les différences sémantiques
    entre sources sont portées par des CASE expressions :

    - `orcid` : NULL pour OpenAlex/WoS/CrossRef (filtré à part via
      `oa_orcid` ci-dessous, ces sources n'étant pas fiables pour
      l'ORCID au niveau matching).
    - `idhal` : renseigné uniquement pour HAL. Pas exploité par le
      matching actuel — le matching par idhal sera réintroduit dans le
      chantier `METIER_decide-person-match`.
    - `idref` : renseigné toutes sources (le pipeline `persons`
      l'utilise comme critère de match cross-source).
    - `oa_orcid` / `oa_full_name` : exposés pour OpenAlex/WoS/CrossRef
      pour permettre au caller la vérification de compatibilité des noms.
    - `roles` : renseigné pour theses uniquement (distingue auteur vs
      directeur de thèse).

    Tous les identifiants sont lus depuis
    `source_authorships.person_identifiers` (JSONB).

    Le nom (last/first) est parsé côté caller via
    `domain.names.parse_raw_author_name(full_name)` — uniformément pour
    toutes les sources.

    Filtre supplémentaire : OpenAlex/WoS/CrossRef exclus des lignes avec
    `raw_author_name IS NULL` (pas de nom utilisable).
    """
    rows = conn.execute(
        text("""
            SELECT sa_auth.id AS authorship_id,
                   sa_auth.source::text AS source,
                   sa_auth.raw_author_name AS full_name,
                   sa_auth.author_name_normalized,
                   CASE WHEN sa_auth.source IN ('openalex', 'wos', 'crossref') THEN NULL::text
                        ELSE sa_auth.person_identifiers->>'orcid' END AS orcid,
                   CASE WHEN sa_auth.source = 'hal'
                        THEN sa_auth.person_identifiers->>'idhal'
                        ELSE NULL::text END AS idhal,
                   sa_auth.person_identifiers->>'idref' AS idref,
                   CASE WHEN sa_auth.source IN ('openalex', 'wos', 'crossref')
                        THEN sa_auth.person_identifiers->>'orcid'
                        ELSE NULL::text END AS oa_orcid,
                   CASE WHEN sa_auth.source IN ('openalex', 'wos', 'crossref')
                        THEN sa_auth.raw_author_name
                        ELSE NULL::text END AS oa_full_name,
                   CASE WHEN sa_auth.source = 'theses' THEN sa_auth.roles
                        ELSE NULL END AS roles,
                   sd.publication_id,
                   sa_auth.author_position
            FROM source_authorships sa_auth
            JOIN source_publications sd ON sd.id = sa_auth.source_publication_id
            JOIN v_active_publications vap ON vap.id = sd.publication_id
            WHERE sa_auth.person_id IS NULL
              AND sa_auth.in_perimeter = TRUE
              AND sd.publication_id IS NOT NULL
              AND (sa_auth.source NOT IN ('openalex', 'wos', 'crossref')
                   OR sa_auth.raw_author_name IS NOT NULL)
        """)
    ).all()
    return [dict(r._mapping) for r in rows]


def fetch_linked_authorships(conn: Connection) -> list[dict[str, Any]]:
    """`source_authorships` déjà rattachées (toutes sources confondues).

    Ramène `raw_author_name` ; le caller parse via
    `domain.names.parse_raw_author_name` pour toutes les sources
    uniformément.
    """
    rows = conn.execute(
        text("""
            SELECT sa_auth.person_id, sa_auth.author_position,
                   sd.publication_id,
                   sa_auth.raw_author_name AS full_name,
                   sa_auth.source::text AS source
            FROM source_authorships sa_auth
            JOIN source_publications sd ON sd.id = sa_auth.source_publication_id
            WHERE sa_auth.person_id IS NOT NULL
              AND sd.publication_id IS NOT NULL
        """)
    ).all()
    return [dict(r._mapping) for r in rows]


def fetch_idref_to_person_map(conn: Connection) -> dict[str, int]:
    """`{idref: person_id}` pour les IdRef connus non rejetés."""
    rows = conn.execute(
        text("""
            SELECT id_value, person_id
            FROM person_identifiers
            WHERE id_type = 'idref'
              AND status != 'rejected'
        """)
    ).all()
    return {r.id_value: r.person_id for r in rows}


def fetch_orcid_to_person_map(conn: Connection) -> dict[str, int]:
    """`{orcid: person_id}` pour les ORCID connus non rejetés."""
    rows = conn.execute(
        text("""
            SELECT id_value, person_id
            FROM person_identifiers
            WHERE id_type = 'orcid'
              AND status != 'rejected'
        """)
    ).all()
    return {r.id_value: r.person_id for r in rows}


def fetch_name_form_map(conn: Connection) -> dict[str, list[int]]:
    """Charge `person_name_forms` sous forme `{name_form: [person_id, ...]}`."""
    rows = conn.execute(text("SELECT name_form, person_ids FROM person_name_forms")).all()
    return {r.name_form: r.person_ids for r in rows}


class PgPersonsCreateQueries:
    """Adapter PostgreSQL pour `application.ports.persons_create.PersonsCreateQueries`."""

    def fetch_unlinked_authorships(self, conn: Connection) -> list[dict[str, Any]]:
        return fetch_unlinked_authorships(conn)

    def fetch_linked_authorships(self, conn: Connection) -> list[dict[str, Any]]:
        return fetch_linked_authorships(conn)

    def fetch_idref_to_person_map(self, conn: Connection) -> dict[str, int]:
        return fetch_idref_to_person_map(conn)

    def fetch_orcid_to_person_map(self, conn: Connection) -> dict[str, int]:
        return fetch_orcid_to_person_map(conn)

    def fetch_name_form_map(self, conn: Connection) -> dict[str, list[int]]:
        return fetch_name_form_map(conn)
