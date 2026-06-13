"""Aggregate root ``Publication`` — référence biblio canonique.

Une `Publication` est la vue UCA d'un document scientifique, agrégée depuis une ou plusieurs `SourcePublication`. Identité = `id` (clé surrogate). Identifiant naturel principal : `doi` (quand renseigné ; les autres identifiants — HALId, NNT — vivent côté `source_publications.external_ids`).

Composition : `Publication.authorships` (entité fille `Authorship`). Les `SourcePublication` attachées sont un aggregate séparé, accédées en projection lecture si besoin.

La logique métier touchant à une publication canonique (déduplication, fusion, agrégation cross-sources, canonicalisation des titres) vit ici.
"""

from dataclasses import dataclass, field
from datetime import datetime

from domain.errors import ConflictError
from domain.publications.authorship import Authorship
from domain.publications.identifiers import DOI
from domain.publications.metadata import absorb_oa_status
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

    def has_minimal_metadata(self) -> bool:
        """Indique si la publication a les métadonnées minimales requises pour exister en base (titre non vide ET année renseignée).

        Une `pub_year` à 0 est considérée comme absente (`bool(0) is False`).
        """
        return bool(self.title) and bool(self.pub_year)

    def absorb(self, other: "Publication") -> None:
        """Absorbe la publication `other` dans `self` (typiquement après une collision DOI ou une fusion explicite). `self` survit et conserve son `id` ; `other` est destinée à être supprimée par l'appelant (côté infrastructure).

        Règle d'enrichissement métadonnées (mutation in-place sur `self`) :

        - **scalaires nullable** (`doi`, `journal_id`, `container_title`, `language`) : `self` garde sa valeur si non-null, sinon prend celle de `other`.
        - **`oa_status`** : règle pairwise asymétrique (cf. `domain.publications.metadata.absorb_oa_status`) — `'diamond'` côté `other` gagne ; sinon `other` upgrade `self` uniquement si `self` est non-ouvert ; sinon `self` est conservé.
        - **`countries`** : union dédupliquée, ordre stable (l'ordre de `self` d'abord, puis les nouveaux de `other`).

        Les autres champs (`title`, `title_normalized`, `doc_type`, `pub_year`, `authorships`) restent inchangés sur `self` (les authorships de `other` sont déplacées par l'appelant via repo plumbing). Lève `ConflictError` si `self.id == other.id` (self-absorption interdite).
        """
        if self.id is not None and self.id == other.id:
            raise ConflictError(
                f"Publication ne peut pas s'absorber elle-même (id={self.id})",
            )
        if self.doi is None:
            self.doi = other.doi
        if self.journal_id is None:
            self.journal_id = other.journal_id
        if self.container_title is None:
            self.container_title = other.container_title
        if self.language is None:
            self.language = other.language
        self.oa_status = absorb_oa_status(self.oa_status, other.oa_status)
        self.countries = _union_countries(self.countries, other.countries)


def _union_countries(a: tuple[str, ...], b: tuple[str, ...]) -> tuple[str, ...]:
    """Union dédupliquée préservant l'ordre : éléments de `a` d'abord, puis nouveaux de `b`."""
    seen = set(a)
    extras = tuple(c for c in b if c not in seen)
    return a + extras
