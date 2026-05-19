"""Port DoiPrefixRepository — contrat d'accès à la table `doi_prefixes`.

Cette table sert de cache `prefix → Registration Agency + publisher`
peuplé par la phase pipeline `resolve_doi_prefixes`. Le port expose le
strict nécessaire pour cette phase : lecture des préfixes à résoudre
(absents de la table mais présents en staging) + insertion d'un
préfixe résolu.

Implémenté par `infrastructure/repositories/doi_prefix_repository.py`.
"""

from typing import Protocol


class DoiPrefixRepository(Protocol):
    """Contrat d'accès à la table `doi_prefixes`."""

    def get_unresolved_prefixes_with_samples(
        self, *, n_samples_per_prefix: int
    ) -> list[tuple[str, list[str]]]:
        """Renvoie `[(prefix, [doi1, doi2, ...]), ...]` pour chaque préfixe
        DOI présent en staging mais absent de `doi_prefixes`. Jusqu'à
        `n_samples_per_prefix` DOIs distincts par préfixe, ordre stable
        (par longueur croissante pour limiter la complexité d'encodage)."""
        ...

    def insert_doi_prefix(
        self,
        *,
        prefix: str,
        ra: str,
        publisher_id: int | None,
        publisher_name_raw: str | None,
        publisher_name_normalized: str | None,
        crossref_member_id: int | None,
    ) -> bool:
        """Insère un préfixe résolu. Retourne True si inséré, False si
        déjà présent (`ON CONFLICT (prefix) DO NOTHING`)."""
        ...
