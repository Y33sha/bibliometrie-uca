"""Port PersonRepository : accès à l'entité Person."""

from typing import Protocol, TypedDict

from domain.persons.identifier_attribution import AttributionResult, IdentifierAttribution
from domain.persons.identifiers import IdentifierOrigin
from domain.persons.person import Person, PersonExclusion


class IdentifierStatusRow(TypedDict):
    """Identifiant après changement de statut, renvoyé par `update_identifier_status`."""

    id: int
    status: str
    person_id: int
    """Personne de l'identifiant, pour l'audit."""


class NameFormStatusRow(TypedDict):
    """Forme de nom après changement de statut, renvoyée par `update_name_form_status`."""

    person_id: int
    name_form: str
    status: str


class PersonRepository(Protocol):
    """Contrat d'accès à l'entité Person : tables `persons`, `person_identifiers`, `person_name_forms`, `distinct_persons`, et une partie de `source_contributions`."""

    # ── persons ────────────────────────────────────────────────────

    def find_by_id(self, person_id: int) -> Person | None:
        """Charge l'entité `Person` avec `identifiers` et `name_forms`, ou `None` si la personne est introuvable. Identifiants et formes de nom se modifient par les méthodes dédiées."""
        ...

    def create(self, last_name: str, first_name: str = "") -> int:
        """Crée une personne avec ses formes de nom (`compute_person_name_forms`), et renvoie son id.

        Raises:
            ValidationError: nom de famille vide, nécessaire aux formes de nom.
        """
        ...

    def rename(self, person_id: int, last_name: str, first_name: str) -> tuple[str, str]:
        """Change le nom d'une personne et recalcule ses formes de nom (`compute_person_name_forms`). Renvoie le nom validé (`validated_name`).

        Raises:
            ValidationError: nom de famille vide.
            NotFoundError: personne introuvable.
        """
        ...

    def set_exclusion(self, person_id: int, exclusion: PersonExclusion | None) -> None:
        """Pose le motif d'exclusion d'une personne, ou retire l'exclusion avec `None`. Lève `NotFoundError` si la personne est introuvable."""
        ...

    # ── Fusion ─────────────────────────────────────────────────────

    def ids_with_rh(self, person_ids: list[int]) -> set[int]:
        """Renvoie, parmi `person_ids`, les personnes ayant une fiche RH (`hr_records`)."""
        ...

    def merge_into(self, target_id: int, source_id: int) -> None:
        """Fusionne la personne `source_id` dans `target_id` : applique la règle de fusion de chaque donnée de la personne, puis supprime la source. Le service garantit en amont que la source est sans fiche RH (`merge_roles`)."""
        ...

    # ── distinct_persons ───────────────────────────────────────────

    def mark_distinct(
        self,
        person_id_a: int,
        person_id_b: int,
    ) -> tuple[int, int] | None:
        """Marque deux personnes comme distinctes (idempotent). Renvoie `(a, b)` triés si la paire est insérée, `None` si elle existait déjà."""
        ...

    def unmark_distinct(self, person_id_a: int, person_id_b: int) -> tuple[int, int] | None:
        """Retire la paire de personnes distinctes. Renvoie `(a, b)` triés si la paire existait, `None` sinon."""
        ...

    # ── person_identifiers ─────────────────────────────────────────

    def find_identifier(self, id_type: str, id_value: str) -> IdentifierAttribution | None:
        """Charge l'attribution de l'identifiant `(id_type, id_value)`, unique, ou `None` si elle est absente."""
        ...

    def insert_identifier(self, ident: IdentifierAttribution) -> int:
        """Insère l'attribution et renvoie son id, posé aussi sur `ident.id`. Lève une erreur si `(id_type, id_value)` existe déjà. L'appelant vérifie l'unicité par `find_identifier`."""
        ...

    def update_identifier(self, ident: IdentifierAttribution) -> None:
        """Écrit la personne, le statut et la source d'une attribution existante. `ident.id` doit être posé."""
        ...

    def attribute_identifier(
        self, person_id: int, id_type: str, id_value: str, *, source: IdentifierOrigin
    ) -> AttributionResult:
        """Attribue l'identifiant à la personne selon `attribution_outcome` : insertion en `pending`, ou reprise d'une attribution `rejected`. Une attribution détenue par une autre personne reste inchangée.

        Raises:
            ValidationError: valeur mal formée (`normalized_identifier_value`).
        """
        ...

    def update_identifier_status(self, ident_id: int, status: str) -> IdentifierStatusRow:
        """Change le statut d'un identifiant et renvoie la ligne. Lève `NotFoundError` s'il est absent."""
        ...

    def propagate_status_to_hal_accounts(self, ident_id: int, status: str) -> int:
        """Pose `status` sur les identifiants `pending` de la personne présents dans les contributions sources de ses comptes HAL. Ces comptes HAL sont ceux des contributions sources HAL contenant l'identifiant `ident_id`. Renvoie le nombre d'identifiants modifiés."""
        ...

    def mark_contributions_of_rejected_identifiers(self, person_id: int) -> int:
        """Marque pour redécision les contributions de la personne rattachées par un identifiant `rejected`. Renvoie le nombre de contributions marquées.

        Une telle contribution a pour mode de résolution le type de l'identifiant, et une de ses contributions sources contient la valeur.
        """
        ...

    # ── person_name_forms ──────────────────────────────────────────

    def add_name_form(
        self,
        person_id: int,
        full_name: str,
        source: str | None = None,
    ) -> None:
        """Ajoute à une personne la forme normalisée du nom, si cette forme est non vide et absente."""
        ...

    def update_name_form_status(
        self, person_id: int, name_form: str, status: str
    ) -> NameFormStatusRow:
        """Change le statut d'une forme de nom et renvoie la ligne. Lève `NotFoundError` si le couple (forme, personne) est absent.

        Une forme rejetée sort durablement du rattachement par nom. Une forme confirmée corrobore les rattachements par identifiant et dispense du test de nom.
        """
        ...

    def delete_orphan_name_forms_for_person(self, person_id: int) -> int:
        """Supprime les formes de nom en attente de la personne, absentes de ses contributions sources. Les formes dérivées de son nom (source `persons`) sont conservées. Renvoie le nombre de formes supprimées."""
        ...
