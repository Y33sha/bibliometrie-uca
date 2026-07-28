"""Port AuthorshipRepository — contrat d'accès aux agrégats Authorship.

Un seul port pour `authorships` et `source_authorships` : leurs opérations sont étroitement couplées.
"""

from datetime import datetime
from typing import Protocol, TypedDict


class AuthorshipPersonRow(TypedDict):
    """Ligne renvoyée par `get_authorship_person` : identité d'une ligne consolidée `authorships`."""

    id: int
    person_id: int | None
    publication_id: int


class AssignedSignatureRow(TypedDict):
    """Ligne renvoyée par `assign_orphan_source_authorship` : source et forme de nom de la signature rattachée."""

    source: str
    author_name_normalized: str | None


class AuthorshipRepository(Protocol):
    """Contrat d'accès aux tables authorships et source_authorships."""

    # ── source_authorships : lien personne ↔ signature ─────────────

    def link_authorship(
        self,
        person_id: int,
        source: str,
        source_authorship_id: int,
        resolution_mode: str,
    ) -> None:
        """Rattache une signature source à une personne et marque le canal de résolution. `resolution_mode` (`identifier` / `name` / `cross_source`) enregistre par quel canal le `person_id` a été posé."""
        ...

    def assign_orphan_source_authorship(
        self,
        person_id: int,
        source_authorship_id: int,
    ) -> AssignedSignatureRow | None:
        """Pose `person_id` sur une signature source orpheline. Retourne `{source, author_name_normalized}`, ou `None` si la signature n'existe pas ou porte déjà un `person_id` — `find_source_authorship_owner` départage."""
        ...

    def find_source_authorship_owner(self, source_authorship_id: int) -> int | None:
        """`person_id` d'une signature source. `None` si elle est orpheline ou n'existe pas."""
        ...

    def assign_orphan_source_authorships_to_person(
        self,
        person_id: int,
        source_authorship_ids: list[int],
    ) -> int:
        """Pose `person_id` sur les signatures du lot qui sont orphelines et retourne le nombre touché ; les signatures déjà rattachées restent intactes."""
        ...

    def get_distinct_name_forms_from_source_authorships(
        self,
        source_authorship_ids: list[int],
    ) -> list[str]:
        """Les `author_name_normalized` distincts observés dans le lot de signatures."""
        ...

    def find_publication_id_for_source_authorship(
        self,
        source_authorship_id: int,
    ) -> int | None:
        """`publication_id` d'une signature, ou `None` si elle n'existe pas ou n'est pas rattachée à une publication."""
        ...

    def find_publication_ids_for_source_authorships(
        self,
        source_authorship_ids: list[int],
    ) -> list[int]:
        """Les `publication_id` distincts couverts par un lot de signatures. Sert au pré-contrôle de rejet en batch."""
        ...

    def null_person_id_for_name_form(self, person_id: int, name_form: str) -> int:
        """Détache (person_id → NULL) les signatures d'une personne portant une forme de nom donnée. Retourne le nombre de signatures détachées."""
        ...

    # ── authorships ────────────────────────────────────────────────

    def get_authorship_person(self, authorship_id: int) -> AuthorshipPersonRow | None:
        """La ligne `authorships` (`id`, `person_id`, `publication_id`), ou `None` si l'id n'existe pas."""
        ...

    def reject_authorship(self, publication_id: int, person_id: int) -> None:
        """Enregistre le rejet d'une paire (publication, personne) dans `rejected_authorships`. Idempotent."""
        ...

    def find_rejected_authorship(self, publication_id: int, person_id: int) -> datetime | None:
        """Date du rejet de la paire (publication, personne) dans `rejected_authorships`, ou None si la paire y est absente."""
        ...

    def delete_rejected_authorship(self, publication_id: int, person_id: int) -> None:
        """Lève le rejet d'une paire (publication, personne) : la retire de `rejected_authorships`. Idempotent."""
        ...

    def unlink_all_source_authorships_for_pair(
        self,
        publication_id: int,
        person_id: int,
    ) -> int:
        """Détache (person_id → NULL) toutes les signatures de la personne sur cette publication. Retourne le nombre de signatures détachées."""
        ...

    def delete_authorship(self, authorship_id: int) -> None: ...

    def delete_orphan_authorships_for_person(self, person_id: int) -> int:
        """Supprime les lignes consolidées de la personne dépourvues de toute signature source active. Retourne le nombre supprimé."""
        ...

    # ── confirmed_authorships (épinglage admin, must-link grain signature) ──

    def pin_authorships(self, source_authorship_ids: list[int], person_id: int) -> None:
        """Épingle des signatures à une personne dans `confirmed_authorships` (résolution admin d'orphelines). Upsert par signature : le dernier épinglage l'emporte."""
        ...

    def unpin_authorships_for_pair(self, publication_id: int, person_id: int) -> int:
        """Retire les épinglages des signatures de la paire (publication, personne) — détachement admin. Retourne le nombre d'épinglages retirés."""
        ...

    def unpin_authorships_for_name_form(self, person_id: int, name_form: str) -> int:
        """Retire les épinglages des signatures d'une personne portant une forme de nom donnée — rejet de forme. Retourne le nombre d'épinglages retirés."""
        ...

    # ── Propagation UCA depuis les adresses ────────────────────────

    def find_source_authorships_by_addresses(
        self,
        address_ids: list[int],
    ) -> list[int]:
        """Ids des signatures liées à l'une des adresses données (via `source_authorship_addresses`)."""
        ...

    # ── Recomposition d'une authorship depuis ses signatures ───────

    def insert_authorship_if_missing(self, publication_id: int, person_id: int) -> None:
        """Crée la ligne consolidée de la paire si elle manque. Écarte les paires figurant dans `rejected_authorships`."""
        ...

    def create_authorships_from_sources(
        self,
        person_id: int,
        source_authorship_ids: list[int],
        source_priority: tuple[str, ...],
    ) -> None:
        """Crée les lignes consolidées manquantes pour la personne, une par publication couverte par le lot, depuis la signature la plus prioritaire."""
        ...

    def link_source_authorships_to_authorship(
        self,
        publication_id: int,
        person_id: int,
    ) -> None:
        """Pose `source_authorships.authorship_id` vers la ligne consolidée de la paire, sur les signatures encore non liées."""
        ...

    def link_source_authorships_batch(
        self,
        person_id: int,
        source_authorship_ids: list[int],
    ) -> None:
        """Pose `source_authorships.authorship_id` vers la ligne consolidée, pour un lot de signatures désignées par id (attribution d'orphelines à une personne) — variante par lot de `link_source_authorships_to_authorship`."""
        ...

    def recompute_authorship_author_position_and_corresponding(
        self,
        publication_id: int,
        person_id: int,
        source_priority: tuple[str, ...],
    ) -> None:
        """Réagrège `author_position` (par priorité de source) et `is_corresponding` (OR des signatures) sur la ligne consolidée."""
        ...

    def recompute_authorship_in_perimeter(self, publication_id: int, person_id: int) -> None:
        """Réagrège `in_perimeter` (OR des signatures) sur la ligne consolidée d'une paire. `recompute_in_perimeter_on_source_authorships` couvre le cas ensembliste, par adresses."""
        ...
