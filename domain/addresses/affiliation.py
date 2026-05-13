"""Aggregate root ``AddressAffiliation`` — état de résolution d'une
adresse vers des structures de recherche.

Une `AddressAffiliation` porte un `Address` (VO) accompagné de son
état de résolution : structures liées (avec leur statut de
confirmation), pays détectés/suggérés, comptage d'usage, horodatage
de résolution.

Identité = `id` (clé surrogate ; aligné sur `addresses.id` côté
schéma — l'adresse et son état partagent la même ligne).

Composition : `structure_links: tuple[StructureLink, ...]` où chaque
`StructureLink` est un VO interne (pas de transition cross-aggregate
qui justifierait un aggregate séparé). Une mutation sur un link
remplace le VO dans le tuple.

La logique métier touchant à la résolution d'adresses (matching,
confirmation manuelle, suggestion automatique) vit ici.
"""

from dataclasses import dataclass, field
from datetime import datetime

from domain.addresses.address import Address
from domain.errors import ConflictError, NotFoundError


@dataclass(frozen=True, slots=True)
class StructureLink:
    """Lien d'une adresse vers une structure (VO interne à AddressAffiliation).

    `is_confirmed` tri-état :
    - `None` : suggéré (état initial après matching automatique)
    - `True` : confirmé (validation manuelle ou par règle)
    - `False` : rejeté (rejet manuel)

    `matched_form_id` pointe vers la `structure_name_forms` qui a
    permis le match (nullable pour les liens créés sans matching de
    forme).
    """

    structure_id: int
    matched_form_id: int | None
    is_confirmed: bool | None


@dataclass(slots=True)
class AddressAffiliation:
    """Adresse + état de résolution vers les structures (aggregate root)."""

    id: int | None
    address: Address
    raw_text: str
    countries: tuple[str, ...] = ()
    suggested_countries: tuple[str, ...] = ()
    resolved_at: datetime | None = None
    pub_count: int = 0
    structure_links: tuple[StructureLink, ...] = field(default=())

    def confirm_structure(self, structure_id: int) -> None:
        """Marque le lien vers `structure_id` comme confirmé.

        Lève `NotFoundError` si aucun lien n'existe pour cette structure.
        """
        self._update_link(structure_id, is_confirmed=True)

    def reject_structure(self, structure_id: int) -> None:
        """Marque le lien vers `structure_id` comme rejeté.

        Lève `NotFoundError` si aucun lien n'existe pour cette structure.
        """
        self._update_link(structure_id, is_confirmed=False)

    def suggest_structure(self, structure_id: int, matched_form_id: int | None) -> None:
        """Ajoute une suggestion (lien `is_confirmed=None`) vers une structure.

        Lève `ConflictError` si la structure est déjà liée (peu importe
        son statut). Pour modifier un statut existant, utiliser
        `confirm_structure` ou `reject_structure`.
        """
        if any(link.structure_id == structure_id for link in self.structure_links):
            raise ConflictError(
                f"AddressAffiliation #{self.id} : structure {structure_id} déjà liée",
            )
        self.structure_links = (
            *self.structure_links,
            StructureLink(
                structure_id=structure_id,
                matched_form_id=matched_form_id,
                is_confirmed=None,
            ),
        )

    def mark_resolved(self, at: datetime) -> None:
        """Marque l'adresse comme résolue à l'instant `at`.

        Le caller fournit le timestamp (pureté du domaine).
        """
        self.resolved_at = at

    def _update_link(self, structure_id: int, *, is_confirmed: bool) -> None:
        new_links: list[StructureLink] = []
        found = False
        for link in self.structure_links:
            if link.structure_id == structure_id:
                new_links.append(
                    StructureLink(
                        structure_id=link.structure_id,
                        matched_form_id=link.matched_form_id,
                        is_confirmed=is_confirmed,
                    )
                )
                found = True
            else:
                new_links.append(link)
        if not found:
            raise NotFoundError(
                f"AddressAffiliation #{self.id} : aucun lien vers structure {structure_id}",
            )
        self.structure_links = tuple(new_links)
