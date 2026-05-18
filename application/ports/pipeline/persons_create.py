"""Port : lectures pour `create_persons_from_source_authorships`.

Implémenté par `infrastructure.queries.persons.create.PgPersonsCreateQueries`.
"""

from typing import NamedTuple, Protocol

from sqlalchemy import Connection


class BareUnlinkedAuthorship(NamedTuple):
    """Projection SQL brute : `source_authorships` UCA non rattaché à une personne.

    `oa_display_name` est renseigné uniquement pour les rows OpenAlex (sert au filtre `keep_orcid_if_name_matches` côté caller). `None` pour les autres sources. `roles` non vide en pratique uniquement pour theses (auteur vs directeur).
    """

    authorship_id: int
    source: str
    full_name: str
    author_name_normalized: str | None
    orcid: str | None
    idref: str | None
    oa_display_name: str | None
    roles: list[str] | None
    publication_id: int | None
    author_position: int


class LinkedAuthorshipRow(NamedTuple):
    """Projection SQL : `source_authorships` déjà rattaché à une personne, toutes sources confondues. Sert au matching cross-source par `(publication_id, author_position)`."""

    person_id: int
    author_position: int
    publication_id: int
    full_name: str
    source: str


class PersonsCreateQueries(Protocol):
    """Opérations SQL pour le rattachement des authorships aux personnes."""

    def fetch_unlinked_authorships(self, conn: Connection) -> list[BareUnlinkedAuthorship]: ...

    def fetch_linked_authorships(self, conn: Connection) -> list[LinkedAuthorshipRow]: ...

    def fetch_idref_to_person_map(self, conn: Connection) -> dict[str, int]: ...

    def fetch_orcid_to_person_map(self, conn: Connection) -> dict[str, int]: ...

    def fetch_name_form_map(self, conn: Connection) -> dict[str, list[int]]: ...
