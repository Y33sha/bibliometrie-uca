"""Aggregate root `Publication` — référence biblio canonique.

Une `Publication` est la vue UCA d'un document scientifique, agrégée depuis une ou plusieurs `SourcePublication`. Identité = `id` (clé surrogate). Identifiant naturel principal : `doi` (quand renseigné ; les autres identifiants — HALId, NNT — vivent côté `source_publications.external_ids`).

Composition : `Publication.authorships` (entité fille `Authorship`). Les `source_publications` attachées sont lues en projection (`SourcePublication`), jamais comme un agrégat mutable.

L'entité porte la forme et l'identité de la référence canonique. Les règles qui la calculent vivent dans les modules voisins du domaine : agrégation cross-sources (`aggregation`), arbitrage des statuts et canonicalisation des titres (`metadata`), assignation et réconciliation (`reconciliation`).
"""

from dataclasses import dataclass, field
from datetime import datetime

from domain.publications.authorship import Authorship
from domain.publications.identifiers import DOI
from domain.types import JsonValue


@dataclass(slots=True)
class Publication:
    """Référence biblio canonique (aggregate root).

    Le champ `id` est None tant que la publication n'a pas été persistée ; il est positionné par le repository après insertion.
    """

    id: int | None
    title: str
    pub_year: int
    title_normalized: str | None = None
    doc_type: str | None = None
    doi: DOI | None = None
    oa_status: str | None = None
    journal_id: int | None = None
    container_title: str | None = None
    language: str | None = None
    abstract: str | None = None
    is_retracted: bool = False
    countries: tuple[str, ...] = field(default=())
    keywords: tuple[str, ...] = field(default=())
    topics: dict[str, JsonValue] | None = None
    biblio: dict[str, JsonValue] | None = None
    meta: dict[str, JsonValue] | None = None
    authorships: tuple[Authorship, ...] = field(default=())
    # Date de la dernière vérification Unpaywall (None = jamais). Quand posée,
    # Unpaywall fait autorité sur `oa_status` : l'agrégation cross-sources ne le
    # ré-écrit pas (cf. `aggregation.recompute`).
    unpaywall_checked_at: datetime | None = None
