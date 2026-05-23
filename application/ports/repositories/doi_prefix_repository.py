"""Port DoiPrefixRepository — contrat d'accès à la table `doi_prefixes`.

Cette table sert de cache `prefix → Registration Agency + publisher` peuplé par la phase pipeline `resolve_doi_prefixes`. Le port expose le strict nécessaire pour cette phase : lecture des préfixes à résoudre, insertion, et reprise des rows existantes pour rattacher un publisher créé après coup.

Pour les rows `ra='DataCite'`, on stocke aussi le nom du DataCite client (= repository) et son symbole stable dans des colonnes dédiées (`client_name_*`, `datacite_client_symbol`). Le provider DataCite (organisation-mère) occupe les mêmes colonnes `publisher_*` que le publisher Crossref, et passe par le même matching/création.

Implémenté par `infrastructure/repositories/doi_prefix_repository.py`.
"""

from typing import NamedTuple, Protocol


class UnmatchedPrefix(NamedTuple):
    """Row `doi_prefixes` avec un `publisher_name_normalized` renseigné mais sans `publisher_id`. Sert à la passe de rattrapage : on retente le match, et on crée le publisher si toujours absent. Agnostique à la RA — vaut pour Crossref (publisher Crossref) et DataCite (provider DataCite)."""

    prefix: str
    publisher_name_raw: str
    publisher_name_normalized: str


class DoiPrefixRepository(Protocol):
    """Contrat d'accès à la table `doi_prefixes`."""

    def get_unresolved_prefixes_with_samples(
        self, *, n_samples_per_prefix: int
    ) -> list[tuple[str, list[str]]]:
        """Renvoie `[(prefix, [doi1, doi2, ...]), ...]` pour chaque préfixe DOI présent en staging mais absent de `doi_prefixes`. Jusqu'à `n_samples_per_prefix` DOIs distincts par préfixe, ordre stable (par longueur croissante pour limiter la complexité d'encodage)."""
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
        client_name_raw: str | None,
        client_name_normalized: str | None,
        datacite_client_symbol: str | None,
    ) -> bool:
        """Insère un préfixe résolu. Retourne True si inséré, False si déjà présent (`ON CONFLICT (prefix) DO NOTHING`). `crossref_member_id` peuplé uniquement si `ra='Crossref'` ; `client_name_*` et `datacite_client_symbol` peuplés uniquement si `ra='DataCite'`."""
        ...

    def get_unmatched_prefixes(self) -> list[UnmatchedPrefix]:
        """Rows existantes avec `publisher_name_normalized` rempli mais `publisher_id IS NULL`. Couvre Crossref et DataCite indifféremment. Ordre stable par `prefix` ASC pour des logs reproductibles."""
        ...

    def update_publisher_id(self, prefix: str, publisher_id: int) -> None:
        """Rattache un préfixe existant à un publisher (passe de rattrapage). Pas d'effet si le préfixe a déjà un `publisher_id` (caller à vérifier)."""
        ...
