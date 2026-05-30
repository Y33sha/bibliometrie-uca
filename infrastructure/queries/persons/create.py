"""Query service : lectures pour `create_persons_from_source_authorships`.

Appelé par `application/pipeline/create/create_persons_from_source_authorships.py`.
Regroupe les SELECT nécessaires aux 4 passes de rattachement
(comptes HAL, cross-source, IdRef/ORCID connus, lookup `person_name_forms`).
"""

from sqlalchemy import Connection, text

from application.ports.pipeline.persons_create import (
    BareUnlinkedAuthorship,
    LinkedAuthorshipRow,
    PersonsCreateQueries,
)


def fetch_unlinked_authorships(conn: Connection) -> list[BareUnlinkedAuthorship]:
    """Liste les `source_authorships` in-perimeter non rattachés à une `person`, toutes sources confondues.

    Colonnes :

    - `orcid`, `idref` : lus directement depuis `person_identifiers` (JSONB), sans filtre par source. La restriction de l'ORCID aux sources fiables (cf. `ORCID_MATCH_SOURCES`) est appliquée côté cascade de matching, pas ici.
    - `roles` : remonté tel quel ; en pratique non vide uniquement pour theses (distingue auteur vs directeur).

    Le nom (last/first) est parsé côté caller via `parse_raw_author_name(full_name)`.

    Les lignes sans `raw_author_name` sont exclues toutes sources confondues (sans nom, l'authorship est inexploitable pour le matching personnes).
    """
    rows = conn.execute(
        text("""
            SELECT sa_auth.id AS authorship_id,
                   sa_auth.source::text AS source,
                   sa_auth.raw_author_name AS full_name,
                   sa_auth.author_name_normalized,
                   sa_auth.person_identifiers->>'orcid' AS orcid,
                   sa_auth.person_identifiers->>'idref' AS idref,
                   sa_auth.roles,
                   sd.publication_id,
                   sa_auth.author_position
            FROM source_authorships sa_auth
            JOIN source_publications sd ON sd.id = sa_auth.source_publication_id
            JOIN v_active_publications vap ON vap.id = sd.publication_id
            WHERE sa_auth.person_id IS NULL
              AND sa_auth.in_perimeter = TRUE
              AND sd.publication_id IS NOT NULL
              AND sa_auth.raw_author_name IS NOT NULL
        """)
    ).all()
    return [
        BareUnlinkedAuthorship(
            authorship_id=r.authorship_id,
            source=r.source,
            full_name=r.full_name,
            author_name_normalized=r.author_name_normalized,
            orcid=r.orcid,
            idref=r.idref,
            roles=r.roles,
            publication_id=r.publication_id,
            author_position=r.author_position,
        )
        for r in rows
    ]


def fetch_linked_authorships(conn: Connection) -> list[LinkedAuthorshipRow]:
    """`source_authorships` déjà rattachées (toutes sources confondues).

    Ramène `raw_author_name` ; le caller parse via `domain.names.parse_raw_author_name` pour toutes les sources uniformément.
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
    return [
        LinkedAuthorshipRow(
            person_id=r.person_id,
            author_position=r.author_position,
            publication_id=r.publication_id,
            full_name=r.full_name,
            source=r.source,
        )
        for r in rows
    ]


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
    """Charge `person_name_forms` sous forme `{name_form: [person_id, ...]}`.

    Agrégation par `name_form` sur la table dénormalisée
    `(name_form, person_id, sources[])` : un dict trié par
    `person_id` croissant pour stabilité.
    """
    rows = conn.execute(
        text("""
            SELECT name_form,
                   array_agg(person_id ORDER BY person_id) AS person_ids
            FROM person_name_forms
            GROUP BY name_form
        """)
    ).all()
    return {r.name_form: r.person_ids for r in rows}


class PgPersonsCreateQueries(PersonsCreateQueries):
    """Adapter PostgreSQL pour `application.ports.persons_create.PersonsCreateQueries`."""

    def fetch_unlinked_authorships(self, conn: Connection) -> list[BareUnlinkedAuthorship]:
        return fetch_unlinked_authorships(conn)

    def fetch_linked_authorships(self, conn: Connection) -> list[LinkedAuthorshipRow]:
        return fetch_linked_authorships(conn)

    def fetch_idref_to_person_map(self, conn: Connection) -> dict[str, int]:
        return fetch_idref_to_person_map(conn)

    def fetch_orcid_to_person_map(self, conn: Connection) -> dict[str, int]:
        return fetch_orcid_to_person_map(conn)

    def fetch_name_form_map(self, conn: Connection) -> dict[str, list[int]]:
        return fetch_name_form_map(conn)
