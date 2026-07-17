"""Port : écriture d'un enregistrement source dans `source_publications`, commun aux normaliseurs.

Implémenté par `infrastructure.queries.pipeline.normalize.source_publications.PgSourcePublicationQueries`.
"""

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from sqlalchemy import Connection

from domain.types import JsonValue


@dataclass(frozen=True, slots=True, kw_only=True)
class SourcePublicationRow:
    """Un enregistrement `source_publications` tel qu'une source le fournit.

    Le jeu de colonnes est commun à toutes les sources ; celles qu'une source ne renseigne pas restent à `None`. Cette absence reflète ce que la source expose : theses.fr ne fournit pas de résumé, HAL et theses.fr pas de compte de citations, `hal_collections` et `embargo_until` n'existent que pour HAL, `is_retracted` que pour OpenAlex.

    Deux colonnes de `source_publications` n'y figurent pas. `title_normalized` se dérive de `title` au moment de l'écriture. `publication_id` est le rattachement à la publication canonique, que la phase `publications` pose et que l'import ne connaît pas.
    """

    # Identité de l'enregistrement source
    source: str
    source_id: str
    """Identifiant natif de la source : hal-id, id OpenAlex, UT WoS, id ScanR, id theses.fr ou NNT, DOI pour crossref et datacite."""
    staging_id: int

    # Rattachement
    doi: str | None = None
    external_ids: JsonValue = None

    # Métadonnées bibliographiques
    title: str
    pub_year: int | None = None
    doc_type: str | None = None
    journal_id: int | None = None
    container_title: str | None = None
    language: str | None = None
    biblio: JsonValue = None

    # Contenu
    abstract: str | None = None
    keywords: list[str] | None = None
    topics: JsonValue = None

    # Accès ouvert
    oa_status: str | None = None
    urls: list[str] | None = None
    embargo_until: date | None = None

    # Métriques et drapeaux
    cited_by_count: int | None = None
    is_retracted: bool | None = None

    # Collections HAL
    hal_collections: list[str] | None = None

    # Charge utile propre à la source
    meta: JsonValue = None


class SourcePublicationQueries(Protocol):
    """Écriture des `source_publications`, commune aux normaliseurs de toutes les sources."""

    def upsert_source_publication(self, conn: Connection, row: SourcePublicationRow) -> int:
        """UPSERT de l'enregistrement sur la clé `(source, source_id)`. Retourne l'id de la ligne."""
        ...
