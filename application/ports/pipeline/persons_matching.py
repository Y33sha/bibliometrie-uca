"""Port : lectures et réinitialisations de la phase personnes.

Les lectures alimentent la cascade de matching (signatures non liées, index d'ancrage, maps identifiant→personne, formes de nom et leurs verdicts) ; les écritures sont les réinitialisations ordre-indépendantes de la phase (détachement, re-orphelinage, suppression des personnes vides). La création d'une personne relève du service (`application.services.persons`), pas de ce port.

Implémenté par `infrastructure.queries.pipeline.persons_matching.PgPersonsMatchingQueries`.
"""

from typing import NamedTuple, Protocol

from sqlalchemy import Connection


class BareUnlinkedAuthorship(NamedTuple):
    """Projection SQL brute : `source_authorships` non rattaché à une personne.

    `roles` non vide en pratique uniquement pour theses (auteur vs directeur).

    `in_perimeter` reflète la détection d'une structure du périmètre sur cette signature. Les candidats `in_perimeter = FALSE` ne sont rattachables que par les barreaux non-nominaux de la cascade (identifiants forts, cross-source) — le matching/création par forme de nom reste réservé au périmètre (cf. `decide_name_form_outcome` et l'orchestrateur).
    """

    authorship_id: int
    source: str
    full_name: str
    author_name_normalized: str | None
    orcid: str | None
    hal_person_id: str | None
    idref: str | None
    roles: list[str] | None
    publication_id: int | None
    author_position: int
    in_perimeter: bool
    # `person_id` courant si la signature est déjà liée en cross-source et re-jugée ce run ; `None` pour une signature non liée. Sert à diffuser l'écriture (no-op / update) et le détachement des sans-appui.
    current_person_id: int | None


class LinkedAuthorshipRow(NamedTuple):
    """Projection SQL : `source_authorships` déjà rattaché à une personne, toutes sources confondues. Sert au matching cross-source par `(publication_id, author_position)`."""

    person_id: int
    author_position: int
    publication_id: int
    full_name: str
    source: str


class PersonsMatchingQueries(Protocol):
    """Opérations SQL pour le rattachement des authorships aux personnes."""

    def fetch_unlinked_authorships(self, conn: Connection) -> list[BareUnlinkedAuthorship]:
        """Les `source_authorships` in-périmètre non rattachés à une personne, toutes sources confondues — matière première de la cascade de matching."""
        ...

    def fetch_out_of_perimeter_candidates(self, conn: Connection) -> list[BareUnlinkedAuthorship]:
        """Les candidats hors-périmètre (`in_perimeter = FALSE`) rattachables sans forme de nom : par identifiant fort partagé, ou par ancrage cross-source."""
        ...

    def fetch_linked_authorships(self, conn: Connection) -> list[LinkedAuthorshipRow]:
        """Les `source_authorships` déjà rattachés par un canal ferme (identifiant, nom, épinglage), hors liens cross-source — index d'ancrage du matching cross-source."""
        ...

    def fetch_cross_source_linked(self, conn: Connection) -> list[BareUnlinkedAuthorship]:
        """Les signatures déjà liées en cross-source (non épinglées), à re-juger contre les ancres fermes ; `current_person_id` porte le rattachement courant."""
        ...

    def fetch_identifier_to_person_map(
        self, conn: Connection, id_type: str
    ) -> dict[str, tuple[int, str, str]]:
        """`{id_value: (person_id, nom, prénom) normalisés}` pour les valeurs connues non rejetées d'un type d'identifiant (`idref`, `orcid`, `hal_person_id`)."""
        ...

    def fetch_name_form_map(self, conn: Connection) -> dict[str, list[int]]:
        """`{name_form: [person_id, ...]}` — les personnes que porte chaque forme de nom, `person_id` croissant pour la stabilité du matching."""
        ...

    def fetch_name_form_status_map(self, conn: Connection) -> dict[tuple[str, int], str]:
        """`{(name_form, person_id): verdict}` — les verdicts de lien forme↔personne, qui corroborent (`confirmed`) ou refusent (`rejected`) un match par identifiant."""
        ...

    def fetch_rejected_person_ids_by_pub(self, conn: Connection) -> dict[int, frozenset[int]]:
        """`{publication_id: {person_id, ...}}` depuis `rejected_authorships` — les paires rejetées, que la cascade écarte de ses candidats."""
        ...

    def fetch_identifier_consensus(
        self, conn: Connection, id_type: str, values: list[str]
    ) -> dict[str, str]:
        """`{id_value: author_name_normalized}` — pour chaque valeur demandée, le nom porté par le plus de signatures (poids en signatures, non en identités)."""
        ...

    def fetch_person_name_forms(
        self, conn: Connection, person_ids: list[int]
    ) -> dict[int, tuple[str, str, list[str]]]:
        """`{person_id: (nom, prénom normalisés, [formes confirmées])}` — le nom canonique et ses formes `confirmed`, pour l'arbitrage des conflits d'identifiant."""
        ...

    def fetch_identifier_owners(self, conn: Connection, id_type: str) -> dict[str, tuple[int, str]]:
        """`{id_value: (person_id, status)}` — les propriétaires non rejetés d'un type d'identifiant, à confronter aux personnes qui en portent des signatures."""
        ...

    def fetch_identifier_bearer_persons(
        self, conn: Connection, id_type: str, sources: tuple[str, ...] | None = None
    ) -> list[tuple[str, int]]:
        """Couples `(id_value, person_id)` : les personnes portant des signatures rattachées d'une valeur d'identifiant, optionnellement restreint à `sources`."""
        ...

    def null_identifier_signatures(
        self, conn: Connection, id_type: str, id_value: str, old_owner_person_id: int
    ) -> int:
        """Remet à NULL les signatures encore attribuées à `old_owner_person_id` et résolues par `(id_type, id_value)`, pour que la cascade les re-résolve. Retourne le nombre détaché."""
        ...

    def reorphan_ambiguous_nominal(self, conn: Connection) -> int:
        """Re-orpheline les signatures résolues par forme de nom (non épinglées) dont la forme désigne au moins deux personnes. Retourne le nombre détaché."""
        ...

    def detach_authorships(self, conn: Connection, authorship_ids: list[int]) -> int:
        """Détache un lot de signatures par id (`person_id` et `resolution_mode` → NULL). Retourne le nombre détaché."""
        ...

    def delete_empty_persons(self, conn: Connection) -> int:
        """Supprime les personnes vidées de toute signature, hors référentiel RH ; leurs formes de nom partent en cascade. Retourne le nombre supprimé."""
        ...
