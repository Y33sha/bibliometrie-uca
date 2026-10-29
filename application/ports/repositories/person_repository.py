"""Port PersonRepository : accès à l'agrégat Person."""

from typing import Protocol, TypedDict

from domain.persons.identifier_attribution import AttributionResult, IdentifierAttribution
from domain.persons.identifiers import IdentifierOrigin
from domain.persons.person import Person, PersonExclusion


class IdentifierStatusRow(TypedDict):
    """Ligne rendue par `update_identifier_status` (changement de statut d'un identifiant ; `person_id` sert à l'audit)."""

    id: int
    status: str
    person_id: int


class NameFormStatusRow(TypedDict):
    """Ligne rendue par `update_name_form_status` (changement de statut d'une forme de nom)."""

    person_id: int
    name_form: str
    status: str


class PersonRepository(Protocol):
    """Contrat d'accès à l'agrégat Person (tables persons, person_identifiers, person_name_forms, distinct_persons, et certaines opérations sur source_contributions)."""

    # ── persons ────────────────────────────────────────────────────

    def find_by_id(self, person_id: int) -> Person | None:
        """Charge l'agrégat `Person` complet (avec `identifiers` et `name_forms`), ou `None` si la personne n'existe pas. Identifiants et formes de nom l'accompagnent en lecture ; leurs modifications passent par les méthodes dédiées."""
        ...

    def create(self, last_name: str, first_name: str = "") -> int:
        """Crée une personne avec ses formes de nom (`compute_person_name_forms`), et renvoie son id.

        Lève `ValidationError` sans nom de famille : les formes qui rattachent des contributions à la personne en dérivent.
        """
        ...

    def rename(self, person_id: int, last_name: str, first_name: str) -> tuple[str, str]:
        """Change le nom d'une personne et recalcule ses formes de nom (`compute_person_name_forms`). Renvoie le nom validé (`validated_name`).

        Lève `ValidationError` sans nom de famille, `NotFoundError` si la personne est introuvable.
        """
        ...

    def set_exclusion(self, person_id: int, exclusion: PersonExclusion | None) -> None:
        """Pose le motif d'exclusion d'une personne (`None` la retient). Lève `NotFoundError` si la personne est introuvable."""
        ...

    # ── Fusion ─────────────────────────────────────────────────────

    def ids_with_rh(self, person_ids: list[int]) -> set[int]:
        """Ids, parmi `person_ids`, des personnes qui ont une fiche RH (`hr_records`)."""
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
        """Insère l'attribution et renvoie son id, posé aussi sur `ident.id`. Lève si `(id_type, id_value)` existe déjà : l'appelant vérifie l'unicité par `find_identifier`."""
        ...

    def update_identifier(self, ident: IdentifierAttribution) -> None:
        """Écrit les modifications d'une attribution existante (personne, statut, source) ; le type et la valeur restent. `ident.id` doit être posé."""
        ...

    def attribute_identifier(
        self, person_id: int, id_type: str, id_value: str, *, source: IdentifierOrigin
    ) -> AttributionResult:
        """Attribue l'identifiant à la personne selon `attribution_outcome` : insertion en `pending`, ou reprise d'une attribution `rejected`. Une attribution que détient une autre personne reste à elle.

        La valeur est normalisée par `normalized_identifier_value`, qui lève `ValidationError` sur une valeur mal formée.
        """
        ...

    def update_identifier_status(self, ident_id: int, status: str) -> IdentifierStatusRow:
        """Change le statut d'un identifiant et renvoie la ligne. Lève `NotFoundError` s'il est absent."""
        ...

    def propagate_status_to_hal_accounts(self, ident_id: int, status: str) -> int:
        """Pose `status` sur les identifiants `pending` de la même personne trouvés dans les contributions sources de ses comptes HAL. Ces comptes sont ceux des contributions sources HAL qui contiennent l'identifiant `ident_id`. Renvoie le nombre d'identifiants modifiés."""
        ...

    def mark_contributions_of_rejected_identifiers(self, person_id: int) -> int:
        """Marque pour la redécision de leur personne les contributions de la personne rattachées par un identifiant `rejected` : le mode de résolution de la contribution est le type de l'identifiant, et l'une de ses contributions sources contient la valeur. Les contributions `manual` et celles d'un autre mode restent en l'état. Renvoie le nombre de contributions marquées."""
        ...

    # ── person_name_forms ──────────────────────────────────────────

    def add_name_form(
        self,
        person_id: int,
        full_name: str,
        source: str | None = None,
    ) -> None:
        """Ajoute une forme de nom à une personne, si elle manque. Le nom est normalisé ; un nom vide après normalisation n'ajoute rien."""
        ...

    def update_name_form_status(
        self, person_id: int, name_form: str, status: str
    ) -> NameFormStatusRow:
        """Change le statut d'une forme de nom et renvoie la ligne. Lève `NotFoundError` si le couple (forme, personne) est absent. Une forme rejetée sort durablement du rattachement par nom ; une forme confirmée corrobore les rattachements par identifiant et dispense du test de nom."""
        ...

    def delete_orphan_name_forms_for_person(self, person_id: int) -> int:
        """Supprime les formes de nom en attente de la personne qu'aucune de ses contributions sources ne contient. Les formes dérivées de son nom (source `persons`) et les formes confirmées ou rejetées restent. Renvoie le nombre de formes supprimées."""
        ...
