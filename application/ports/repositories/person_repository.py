"""Port PersonRepository — contrat d'accès à l'agrégat Person."""

from enum import StrEnum
from typing import Protocol, TypedDict

from domain.persons.person import Person
from domain.persons.person_identifier import PersonIdentifier


class AuthenticateOrcidOutcome(StrEnum):
    """Issue de l'authentification d'un ORCID par `authenticate_orcid`."""

    INSERTED = "inserted"  # l'ORCID n'existait pas, créé authentifié
    UPGRADED = "upgraded"  # déjà rattaché à cette personne, statut renforcé
    REASSIGNED = "reassigned"  # déplacé depuis une autre personne, puis authentifié
    NOOP = "noop"  # déjà authentifié sur cette personne


class IdentifierStatusRow(TypedDict):
    """Ligne renvoyée par `update_identifier_status` (changement de statut d'un identifiant ; `person_id` sert à l'audit)."""

    id: int
    status: str
    person_id: int


class NameFormStatusRow(TypedDict):
    """Ligne renvoyée par `update_name_form_status` (changement de statut d'une forme de nom). Alimente le DTO `NameFormStatusResponse`."""

    person_id: int
    name_form: str
    status: str


class PersonRepository(Protocol):
    """Contrat d'accès à l'agrégat Person (tables persons, person_identifiers, person_name_forms, distinct_persons, et certaines opérations sur source_authorships)."""

    # ── persons ────────────────────────────────────────────────────

    def find_by_id(self, person_id: int) -> Person | None:
        """Charge l'agrégat `Person` complet (avec `identifiers` et `name_forms`), ou `None` si la personne n'existe pas. Les `identifiers` et `name_forms` accompagnent l'agrégat en projection lecture ; leurs mutations passent par les méthodes dédiées."""
        ...

    def create(self, last_name: str, first_name: str = "") -> int:
        """Crée une personne (formes normalisées des noms dérivées) et retourne son `id`."""
        ...

    def update_name(self, person_id: int, last_name: str, first_name: str) -> None:
        """Met à jour le nom d'une personne. Lève `NotFoundError` si elle est introuvable."""
        ...

    def set_rejected(self, person_id: int, rejected: bool) -> None:
        """Pose le drapeau `rejected` d'une personne et recalcule `publications.in_perimeter` pour ses publications (une personne rejetée en est exclue). Lève `NotFoundError` si la personne est introuvable."""
        ...

    # ── persons_rh (fiches RH) ─────────────────────────────────────

    def find_rh_person_duplicate(
        self, last_name: str, first_name: str, department: str | None, role: str | None
    ) -> int | None:
        """`id` d'une personne portant les mêmes nom et prénom normalisés et la même fiche RH (`department`, `role`, comparaison NULL-safe), ou `None`. Clé de déduplication de l'import RH : une même personne, même service, même fonction, n'est pas réinsérée."""
        ...

    def insert_rh_record(
        self,
        person_id: int,
        *,
        email: str | None,
        role: str | None,
        department: str | None,
        start_date: str | None,
        end_date: str | None,
        export_date: str | None,
    ) -> None:
        """Ajoute une fiche RH (`persons_rh`) à une personne : email, fonction, service, période et date d'export du fichier RH."""
        ...

    def map_rh_emails_to_person_ids(self) -> dict[str, list[int]]:
        """`{email minusculisé: [person_id, ...]}` depuis `persons_rh` — résout les emails de l'import des ORCID authentifiés vers les personnes qui les portent."""
        ...

    # ── Fusion ─────────────────────────────────────────────────────

    def has_distinct_rh(self, id_a: int, id_b: int) -> bool:
        """Vrai si les deux personnes portent chacune une fiche RH distincte (`persons_rh`) : au moins deux fiches sur la paire."""
        ...

    def merge_into(self, target_id: int, source_id: int) -> None:
        """Fusionne la personne `source_id` dans `target_id` : transfère contributions, identifiants, fiche RH et formes de nom vers la cible, recalcule ses formes canoniques, puis supprime la source. Le service garantit en amont l'invariant « au plus une fiche RH sur la paire » via `has_distinct_rh`."""
        ...

    # ── distinct_persons ───────────────────────────────────────────

    def mark_distinct(
        self,
        person_id_a: int,
        person_id_b: int,
    ) -> tuple[int, int] | None:
        """Marque deux personnes comme distinctes (idempotent). Retourne `(a, b)` triés si la paire vient d'être insérée, `None` si elle existait déjà."""
        ...

    # ── person_identifiers ─────────────────────────────────────────

    def find_identifier(self, id_type: str, id_value: str) -> PersonIdentifier | None:
        """Charge le `PersonIdentifier` d'une paire `(id_type, id_value)` (unique dans la table), ou `None` si absent."""
        ...

    def find_identifier_holders(
        self, id_type: str, id_values: list[str]
    ) -> dict[str, tuple[int, str]]:
        """`{id_value: (person_id, statut)}` des porteurs actuels des valeurs `id_values` déjà présentes sous ce type d'identifiant — pour prévoir les déplacements avant l'import des ORCID authentifiés."""
        ...

    def insert_identifier(self, ident: PersonIdentifier) -> int:
        """Insère le `PersonIdentifier` et retourne son id (posé aussi sur `ident.id`). Lève si `(id_type, id_value)` existe déjà ; l'unicité est vérifiée en amont via `find_identifier`."""
        ...

    def update_identifier(self, ident: PersonIdentifier) -> None:
        """Persiste les mutations d'un `PersonIdentifier` existant (`person_id`, `status`, `source`) ; `id_type` et `id_value` sont immuables. Requiert `ident.id` posé."""
        ...

    def remove_identifier(self, person_id: int, id_type: str, id_value: str) -> None:
        """Supprime l'identifiant `(person_id, id_type, id_value)`. Lève `NotFoundError` s'il est absent."""
        ...

    def update_identifier_status(self, ident_id: int, status: str) -> IdentifierStatusRow:
        """Change le statut d'un identifiant et retourne la ligne. Lève `NotFoundError` s'il est absent."""
        ...

    def reassign_identifier(self, ident_id: int, target_person_id: int) -> None:
        """Réattribue un identifiant à une autre personne, statut repassé à `pending`. Lève `NotFoundError` s'il est absent."""
        ...

    def begin_authenticated_orcid_import(self) -> None:
        """Ouvre, pour la transaction courante, le droit d'écrire le statut `authenticated`. À appeler avant `authenticate_orcid`, dans la même transaction ; réservé à l'import des ORCID authentifiés, seul contexte autorisé à poser ce statut."""
        ...

    def authenticate_orcid(self, person_id: int, orcid: str) -> AuthenticateOrcidOutcome:
        """Pose le statut `authenticated` sur `orcid`, rattaché à `person_id`, et retourne l'issue. Requiert `begin_authenticated_orcid_import` dans la même transaction. Idempotent ; `orcid` supposé normalisé. Un ORCID porté par une autre personne est déplacé, l'authentification faisant autorité sur l'identité."""
        ...

    # ── person_name_forms ──────────────────────────────────────────

    def refresh_name_forms(self, person_id: int, forms: set[str]) -> None:
        """Recalcule les formes de nom canoniques (source `'persons'`) d'une personne à partir de `forms`, l'ensemble des formes normalisées calculées par le domaine (`compute_person_name_forms`). Les formes attestées par d'autres sources sont préservées."""
        ...

    def add_name_form(
        self,
        person_id: int,
        full_name: str,
        source: str | None = None,
    ) -> None:
        """Ajoute une forme de nom à une personne (idempotent). `full_name` est normalisé ; no-op s'il est vide ou se normalise en chaîne vide."""
        ...

    def update_name_form_status(
        self, person_id: int, name_form: str, status: str
    ) -> NameFormStatusRow:
        """Change le statut d'une forme de nom et retourne la ligne. Lève `NotFoundError` si le couple `(name_form, person_id)` est absent. `rejected` bloque durablement le retour de la forme au matching par nom ; `confirmed` corrobore les matchs par identifiant et court-circuite le test de nom."""
        ...

    def delete_orphan_name_forms_for_person(self, person_id: int) -> int:
        """Élague les formes de nom attestées par une source : garde celles qu'au moins une `source_authorship` active de la personne porte encore, supprime les autres. Se limite aux formes `pending` ; les formes calculées (source `'persons'`) et les verdicts `confirmed`/`rejected` sont préservés. Retourne le nombre de formes supprimées."""
        ...
