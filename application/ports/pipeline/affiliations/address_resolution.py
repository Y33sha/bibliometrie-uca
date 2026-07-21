"""Port : résolution des adresses en structures, phase `affiliations`.

Implémenté par `infrastructure.queries.pipeline.affiliations.address_resolution.PgAddressResolutionQueries`.
"""

from typing import NamedTuple, Protocol

from sqlalchemy import Connection

from domain.structures.structure import StructureType


class StructureNameForm(NamedTuple):
    """Forme normalisée d'une structure consommée par le matching adresses → structures.

    `requires_context_of` : liste des structure_ids dont au moins une forme doit aussi matcher pour valider cette forme (anti-faux-positifs cross-établissement : un code de laboratoire ambigu n'est retenu que si son université de tutelle matche la même adresse). `None` ou liste vide = pas de contexte requis.
    `is_excluding` : si TRUE et que la forme matche, retire la structure des résultats même si d'autres formes la matchent.
    `structure_type` : type de la structure portant la forme. Détermine si un appariement vaut affiliation à retenir ou seulement contexte de reconnaissance (`StructureType.is_affiliation`).
    """

    id: int
    structure_id: int
    form_text: str
    is_word_boundary: bool
    requires_context_of: list[int] | None
    is_excluding: bool
    structure_type: StructureType


class KeptPair(NamedTuple):
    """Détection `(address_id, structure_id)` encore présente, à préserver de la purge."""

    address_id: int
    structure_id: int


class DetectedStructure(NamedTuple):
    """Détection à écrire : structure `structure_id` reconnue dans l'adresse `address_id` par la forme `form_id`."""

    address_id: int
    structure_id: int
    form_id: int


class AddressResolutionQueries(Protocol):
    """Opérations SQL pour résoudre les adresses → structures.

    Chaque run est un recalcul complet idempotent : toutes les adresses sont traitées par tranches (keyset par `id`), et seules les détections `address_structures` qui changent sont écrites. Mémoire et allers-retours SQL bornés par la taille de tranche, pas par le total.
    """

    def load_name_forms(self, conn: Connection) -> list[StructureNameForm]:
        """Toutes les formes de `structure_name_forms`, triées par `id` : l'entrée du matcher, chargée une fois par run."""
        ...

    def fetch_addresses_chunk(
        self, conn: Connection, *, after_id: int, limit: int
    ) -> list[tuple[int, str]]:
        """Tranche `(id, normalized_text)` triée par `id`, `id > after_id`.

        Liste vide = plus rien à traiter.
        """
        ...

    def delete_obsolete_detections_bulk(
        self, conn: Connection, addr_ids: list[int], kept_pairs: list[KeptPair]
    ) -> int:
        """Supprime les détections auto non confirmées devenues obsolètes.

        Pour les adresses `addr_ids`, retire les liens `matched_form_id IS NOT NULL` / `is_confirmed IS NULL` dont le `(address_id, structure_id)` n'est pas dans `kept_pairs` (encore détectés). Retourne le rowcount.
        """
        ...

    def unflag_obsolete_detections_bulk(
        self, conn: Connection, addr_ids: list[int], kept_pairs: list[KeptPair]
    ) -> None:
        """Retire `matched_form_id` des liens manuels (is_confirmed) obsolètes."""
        ...

    def upsert_detected_structures_bulk(
        self, conn: Connection, detections: list[DetectedStructure]
    ) -> None:
        """Insère/maj en bloc les détections `(address_id, structure_id, form_id)`.

        Idempotent : ne réécrit pas les liens dont le `matched_form_id` est déjà à jour. L'appelant garantit l'unicité de `(address_id, structure_id)` dans le lot.
        """
        ...
