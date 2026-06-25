"""Port DoiPrefixRepository — contrat d'accès à la table `doi_prefixes`.

Cette table sert de cache `prefix → Registration Agency + publisher`. Elle est peuplée en deux temps : la phase `resolve_ra` (avant cross_imports) insère `(prefix, ra)` via `insert_ra` ; le volet publisher de la phase `publishers_journals` interroge `/prefixes` pour les rows non encore vérifiées (`publisher_checked_at IS NULL`), renseigne les métadonnées et attache le publisher.

Pour les rows `ra='DataCite'`, on stocke aussi le nom du DataCite client (= repository) et son symbole stable dans des colonnes dédiées (`client_name_*`, `datacite_client_symbol`). Le provider DataCite (organisation-mère) occupe les mêmes colonnes `publisher_*` que le publisher Crossref, et passe par le même matching/création.

Implémenté par `infrastructure/repositories/doi_prefix_repository.py`.
"""

from typing import NamedTuple, Protocol


class PendingPublisherPrefix(NamedTuple):
    """Row `doi_prefixes` dont le publisher reste à déterminer : `publisher_id IS NULL` et `publisher_checked_at IS NULL` (`/prefixes` jamais tenté). `publisher_name_*` sont en général NULL (créées par `resolve_ra` avec la RA seule) mais peuvent être renseignés pour des rows héritées — le volet attache alors directement sans re-fetch."""

    prefix: str
    ra: str
    publisher_name_raw: str | None
    publisher_name_normalized: str | None


class DoiPrefixRepository(Protocol):
    """Contrat d'accès à la table `doi_prefixes`."""

    def get_unresolved_prefixes_with_samples(
        self, *, n_samples_per_prefix: int
    ) -> list[tuple[str, list[str]]]:
        """Renvoie `[(prefix, [doi1, doi2, ...]), ...]` pour chaque préfixe DOI du pool `candidate_dois` absent de `doi_prefixes`. Jusqu'à `n_samples_per_prefix` DOIs distincts par préfixe, ordre stable (par longueur croissante pour limiter la complexité d'encodage). Sert à `resolve_ra` (doi.org/ra résout un DOI, pas un préfixe nu)."""
        ...

    def insert_ra(self, *, prefix: str, ra: str) -> bool:
        """Insère un préfixe avec sa RA seule (`publisher_*` NULL, `publisher_checked_at` NULL). `ra='unknown'` si doi.org/ra n'a pas su classer. Retourne True si inséré, False si déjà présent (`ON CONFLICT (prefix) DO NOTHING`)."""
        ...

    def breakdown_by_registration_agency(self) -> list[tuple[str, int, int]]:
        """Pour chaque Registration Agency présente dans le pool `candidate_dois` (`Crossref` / `DataCite` / `unknown`), le couple `(ra, nombre de DOI candidats distincts, nombre de préfixes distincts)`, trié par nombre de DOI décroissant. Un DOI (ou préfixe) non encore résolu compte comme `unknown`. Sert l'observabilité de la phase `resolve_ra`."""
        ...

    def get_prefixes_pending_publisher(self) -> list[PendingPublisherPrefix]:
        """Rows à traiter par le volet publisher : `publisher_id IS NULL`, `publisher_checked_at IS NULL`, et `ra` gérée (`Crossref`/`DataCite`/`unknown` — les autres RAs n'ont pas d'endpoint `/prefixes` exploitable). Ordre par `prefix` ASC pour des logs reproductibles."""
        ...

    def set_prefix_publisher_metadata(
        self,
        *,
        prefix: str,
        ra: str,
        publisher_name_raw: str | None,
        publisher_name_normalized: str | None,
        crossref_member_id: int | None,
        client_name_raw: str | None,
        client_name_normalized: str | None,
        datacite_client_symbol: str | None,
    ) -> None:
        """Renseigne les métadonnées publisher d'une row après fetch `/prefixes` (et corrige `ra` si elle était `unknown`). N'attache pas le `publisher_id` (cf. `update_publisher_id`) ni ne marque la row vérifiée (cf. `mark_publisher_checked`)."""
        ...

    def update_publisher_id(self, prefix: str, publisher_id: int) -> None:
        """Attache un publisher à un préfixe."""
        ...

    def mark_publisher_checked(self, prefix: str) -> None:
        """Pose `publisher_checked_at = now()` : `/prefixes` a été tenté (succès ou échec) → la row ne sera plus reprise par le volet. Borne le travail à une tentative par row."""
        ...
