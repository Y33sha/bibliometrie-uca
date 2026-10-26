"""Service Adresses — corrections à la main sur les adresses (écritures API).

L'adresse n'a pas d'objet de domaine. `AddressRepository` gère ses tables ; le SQL et ce service appliquent ses règles. La détection appartient au pipeline — matching des structures en phase `affiliations`, détection des pays en phase `countries` ; ce service corrige ses résultats à la main.

Deux sujets :
- validation manuelle des rattachements adresse ↔ structure (table `address_structures`) : confirmer, rejeter ou réinitialiser une détection, puis propager vers le périmètre des contributions sources ;
- saisie manuelle des pays, puis propagation vers les `source_records` et les `publications`.

Une saisie manuelle de pays s'écrit en candidats `manual` par `AddressRepository`, qui l'emportent sur les autres moyens. La résolution de `addresses.countries` et le recalcul des pays des enregistrements sources et des publications appartiennent au pipeline, qui les expose par `CountryRecompute`.

Les propagations peuvent toucher des dizaines de milliers de lignes : l'appelant les lance en tâche de fond.
"""

import logging

from application.audit_log import emit_event
from application.ports.pipeline.countries import CountryRecompute
from application.ports.pipeline.perimeter_structures import PerimeterStructures
from application.ports.pipeline.source_contribution_perimeter import (
    SourceContributionPerimeterRecompute,
)
from application.ports.repositories.address_repository import (
    AddressCountryFilter,
    AddressRepository,
)
from application.ports.repositories.contribution_repository import ContributionRepository
from domain.errors import ValidationError
from domain.types import JsonValue

logger = logging.getLogger(__name__)


class AddressService:
    """Écritures sur les adresses : rattachements aux structures, pays, et leurs propagations."""

    def __init__(
        self,
        *,
        addresses: AddressRepository,
        contributions: ContributionRepository,
        country_recompute: CountryRecompute,
        perimeter_structures: PerimeterStructures,
        perimeter_recompute: SourceContributionPerimeterRecompute,
    ) -> None:
        self._addresses = addresses
        self._contributions = contributions
        self._country_recompute = country_recompute
        self._perimeter_structures = perimeter_structures
        self._perimeter_recompute = perimeter_recompute

    # ── Rattachements adresse ↔ structure ──

    def review_structure_link(
        self, address_id: int, structure_id: int, is_confirmed: bool | None
    ) -> list[int]:
        """Insère ou met à jour le lien adresse ↔ structure (validation manuelle).

        - is_confirmed = True  → confirme (crée le lien si besoin)
        - is_confirmed = False → rejette (crée le lien si besoin)
        - is_confirmed = None  → reset (supprime le lien manuel, remet l'auto à NULL)

        Retourne `[address_id]` si la contribution de l'adresse au calcul in_perimeter a changé (à propager en tâche de fond), `[]` sinon — ce qui évite les cascades massives sur les no-op (ex : confirmer une adresse déjà auto-détectée).
        """
        before = self._addresses.which_contribute_to_perimeter([address_id], structure_id)

        if is_confirmed is None:
            self._addresses.reset_manual_link(address_id, structure_id)
        else:
            self._addresses.upsert_structure_link(address_id, structure_id, is_confirmed)

        after = self._addresses.which_contribute_to_perimeter([address_id], structure_id)
        emit_event(
            "address.link_reviewed",
            "address",
            address_id,
            {"structure_id": structure_id, "is_confirmed": is_confirmed},
        )
        return list(before ^ after)

    def batch_review_structure_link(
        self, address_ids: list[int], structure_id: int, is_confirmed: bool | None
    ) -> tuple[int, list[int]]:
        """Comme `review_structure_link` mais sur un lot d'adresses.

        Retourne `(nombre d'adresses touchées, adresses dont la contribution au calcul in_perimeter a changé)`. Pour les reset, le nombre touché est le nombre de lignes mises à jour ; pour les upserts, la taille du lot. La propagation des adresses changées est lancée en tâche de fond par l'appelant.

        Un lot est une décision unique : l'événement d'audit est unique lui aussi, sans identifiant d'agrégat, et contient les adresses visées et le nombre effectivement touché.
        """
        if not address_ids:
            return 0, []

        before = self._addresses.which_contribute_to_perimeter(address_ids, structure_id)

        if is_confirmed is None:
            updated = self._addresses.batch_reset_manual_links(address_ids, structure_id)
        else:
            self._addresses.batch_upsert_structure_links(address_ids, structure_id, is_confirmed)
            updated = len(address_ids)

        after = self._addresses.which_contribute_to_perimeter(address_ids, structure_id)
        emit_event(
            "address.batch_link_reviewed",
            "address",
            None,
            {
                "address_ids": address_ids,
                "structure_id": structure_id,
                "is_confirmed": is_confirmed,
                "updated": updated,
            },
        )
        return updated, list(before ^ after)

    def propagate_in_perimeter_for_addresses(self, address_ids: list[int]) -> None:
        """Recalcule le périmètre des contributions sources liées aux adresses données, de leurs groupes et de leurs publications."""
        if not address_ids:
            return

        perimeter_ids = self._perimeter_structures.persons_structure_ids()
        if not perimeter_ids:
            return

        affected_source_contribution_ids = (
            self._contributions.find_source_contributions_by_addresses(address_ids)
        )
        if not affected_source_contribution_ids:
            return

        self._perimeter_recompute.recompute_perimeter(
            affected_source_contribution_ids, perimeter_ids
        )

    # ── Pays ──

    def set_country(self, address_id: int, countries: list[str] | None) -> None:
        """Saisit à la main les pays d'une adresse, puis résout l'adresse. `countries=None` ou `[]` rend l'adresse aux moyens automatiques.

        Lève `ValidationError` sur un code absent du référentiel, `NotFoundError` sur une adresse introuvable.
        """
        self._require_known_countries(countries or [])
        self._addresses.set_manual_countries(address_id, countries)
        self._country_recompute.resolve_address_countries([address_id])
        emit_event("address.country_set", "address", address_id, {"countries": countries or []})

    def batch_set_country(
        self,
        country_code: str,
        *,
        address_ids: list[int] | None,
        search: str,
        has_country: bool | None,
        country_code_filter: str,
    ) -> list[int]:
        """Ajoute un pays à des adresses, désignées par leurs identifiants ou, à défaut, par filtre (`batch_set_country_by_ids`, `batch_set_country_by_filter`).

        Retourne les identifiants des adresses modifiées, à propager vers les publications en tâche de fond.
        """
        if address_ids:
            modified_ids = self.batch_set_country_by_ids(country_code, address_ids)
        else:
            modified_ids = self.batch_set_country_by_filter(
                country_code,
                search=search,
                has_country=has_country,
                country_code_filter=country_code_filter,
            )
        # Une sélection par filtre peut couvrir toute la table : c'est le critère qui exprime la
        # décision, non la liste qu'il rend. L'appel par identifiants, lui, les consigne.
        decision: dict[str, JsonValue] = {"country_code": country_code}
        if address_ids:
            decision["address_ids"] = address_ids
        else:
            decision["filtre"] = {
                "search": search,
                "has_country": has_country,
                "country_code_filter": country_code_filter,
            }
        emit_event(
            "address.batch_country_set",
            "address",
            None,
            {**decision, "updated": len(modified_ids)},
        )
        return modified_ids

    def batch_set_country_by_ids(self, country_code: str, address_ids: list[int]) -> list[int]:
        """Ajoute `country_code` aux pays des adresses données : leurs pays retenus et `country_code` deviennent leurs pays saisis à la main. Résout ensuite les adresses.

        Retourne les IDs atteints. Lève `ValidationError` sur un code absent du référentiel.
        """
        self._require_known_countries([country_code])
        ids = self._addresses.add_manual_country_by_ids(country_code, address_ids)
        self._country_recompute.resolve_address_countries(ids)
        return ids

    def batch_set_country_by_filter(
        self,
        country_code: str,
        *,
        search: str | None = None,
        has_country: bool | None = None,
        country_code_filter: str | None = None,
    ) -> list[int]:
        """Ajoute `country_code` aux pays des adresses correspondant aux filtres, comme `batch_set_country_by_ids`.

        Filtres combinés en AND (tous doivent correspondre). **Au moins un filtre est exigé** : un appel sans aucun filtre est refusé (`ValidationError`), garde-fou contre l'application d'un pays à toutes les adresses en masse (~475k → cascade de propagation). Pour viser un grand ensemble explicitement, passer par `batch_set_country_by_ids`.

        Retourne les IDs modifiés. Lève `ValidationError` sur un code absent du référentiel.
        """
        self._require_known_countries([country_code])
        criteria = AddressCountryFilter(
            search=search,
            has_country=has_country,
            country_code=country_code_filter,
        )
        if criteria.is_empty:
            raise ValidationError(
                "batch_set_country_by_filter exige au moins un filtre "
                "(search / has_country / country_code_filter) : "
                "refus d'appliquer un pays à toutes les adresses."
            )
        ids = self._addresses.add_manual_country_by_filter(country_code, criteria)
        self._country_recompute.resolve_address_countries(ids)
        return ids

    def propagate_countries_to_publications(self, address_ids: list[int]) -> None:
        """Propage addresses.countries → source_records.countries → publications.countries.

        Appelée après une modification de pays sur les adresses (typiquement en tâche de fond). Recalcule depuis les adresses, idempotent.
        """
        if not address_ids:
            return

        docs = self._country_recompute.refresh_source_records_countries_for_addresses(address_ids)
        publications = self._country_recompute.refresh_publications_countries_for_addresses(
            address_ids
        )

        if docs or publications:
            logger.info("Propagation pays : %s docs source, %s publications", docs, publications)

    def _require_known_countries(self, codes: list[str]) -> None:
        """Refuse un code absent du référentiel `countries`."""
        for code in codes:
            if not self._addresses.country_exists(code):
                raise ValidationError(f"Code pays inconnu : {code}")
