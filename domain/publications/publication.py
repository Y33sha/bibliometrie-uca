"""Aggregate root ``Publication`` — référence biblio canonique.

Une `Publication` est la vue UCA d'un document scientifique, agrégée
depuis une ou plusieurs `SourcePublication`. Identité = `id` (clé
surrogate). Identifiant naturel principal : `doi` (quand renseigné ;
les autres identifiants — HALId, NNT — vivent côté
`source_publications.external_ids`).

Composition : `Publication.authorships` (entité fille `Authorship`).
Les `SourcePublication` attachées sont un aggregate séparé, accédées
en projection lecture si besoin.

La logique métier touchant à une publication canonique (déduplication,
fusion, agrégation cross-sources, canonicalisation des titres) vit ici.
"""

from dataclasses import dataclass, field

from domain.publications.authorship import Authorship
from domain.publications.identifiers import DOI


@dataclass(slots=True)
class Publication:
    """Référence biblio canonique (aggregate root).

    Le champ `id` est None tant que la publication n'a pas été
    persistée ; il est positionné par le repository après insertion.
    """

    id: int | None
    title: str
    pub_year: int
    title_normalized: str | None = None
    doc_type: str | None = None
    doi: DOI | None = None
    oa_status: str | None = None
    authorships: tuple[Authorship, ...] = field(default=())

    def has_minimal_metadata(self) -> bool:
        """Indique si la publication a les métadonnées minimales requises
        pour exister en base (titre non vide ET année renseignée).

        Une `pub_year` à 0 est considérée comme absente (`bool(0) is False`).
        """
        return bool(self.title) and bool(self.pub_year)
