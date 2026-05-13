"""Aggregate root ``Publication`` — référence biblio canonique.

Une `Publication` est la vue UCA d'un document scientifique, agrégée
depuis une ou plusieurs `SourcePublication`. Identité = `id` (clé
surrogate). Identifiant naturel principal : `doi` (quand renseigné).

Composition : `Publication.authorships` (entité fille `Authorship`).
Hors aggregate mais associés en lecture : les `SourcePublication`
attachées (cf. décision 3 du chantier `CODE_rich-domain-model` —
`SourcePublication` est un aggregate séparé).

La logique métier touchant à une publication canonique
(déduplication, fusion, agrégation cross-sources, canonicalisation
des titres) vit ici. Les chantiers METIER_dedup-fusion-publications,
METIER_doc-types, METIER_crossref, METIER_doi-ra-datacite y déposent
leurs méthodes dans leurs phases dédiées.

Scaffolding Phase 1 : attributs minimaux + invariant
`has_minimal_metadata`. Les méthodes de fusion, résolution de conflit
DOI, agrégation OA, etc. arrivent en Phase 2 + chantiers METIER_*.
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

        Invariant rapatrié depuis `domain/publications/dedup.py`
        (fonction libre `has_minimal_publication_metadata`).
        Une `pub_year` à 0 est considérée comme absente (`bool(0) is False`).
        """
        return bool(self.title) and bool(self.pub_year)
