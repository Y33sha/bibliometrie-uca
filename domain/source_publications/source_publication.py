"""Aggregate root ``SourcePublication`` — vue d'un document depuis une
source externe avant agrégation canonique.

Une `SourcePublication` est l'image d'un document dans une source
externe (HAL, OpenAlex, WoS, theses.fr, ScanR, …). Identité naturelle
= `(source, source_id)`. Identité surrogate = `id`.

Lifecycle autonome :
- naissance à l'extraction (`publication_id is None`)
- vie non-attachée pendant la dédup
- attachement à une publication canonique (`attach_to(pub_id)`)
- ré-attachement éventuel sur cascade de fusion (`reattach_to(new_pub_id)`)

Composition : `source_authorships: tuple[SourceAuthorship, ...]`
(entités filles).

La logique métier touchant aux publications sources (extraction,
normalisation cross-sources, attachement à la publication canonique)
vit ici.
"""

from dataclasses import dataclass, field

from domain.errors import ConflictError
from domain.json_types import JsonValue
from domain.source_publications.source_authorship import SourceAuthorship


@dataclass(slots=True)
class SourcePublication:
    """Document tel qu'extrait d'une source externe.

    `publication_id` est mutable : None tant que la source n'a pas été
    attachée à une publication canonique, puis pointe vers l'id de
    cette publication (et peut changer lors d'une cascade de fusion).
    """

    id: int | None
    source: str
    source_id: str
    title: str
    pub_year: int | None = None
    doc_type: str | None = None
    doi: str | None = None
    publication_id: int | None = None
    staging_id: int | None = None
    journal_id: int | None = None
    container_title: str | None = None
    language: str | None = None
    oa_status: str | None = None
    cited_by_count: int | None = None
    is_retracted: bool | None = None
    abstract: str | None = None
    countries: tuple[str, ...] = ()
    hal_collections: tuple[str, ...] = ()
    urls: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    external_ids: dict[str, JsonValue] | None = None
    topics: dict[str, JsonValue] | None = None
    biblio: dict[str, JsonValue] | None = None
    meta: dict[str, JsonValue] | None = None
    source_authorships: tuple[SourceAuthorship, ...] = field(default=())

    def attach_to(self, pub_id: int) -> None:
        """Attache cette source à une publication canonique.

        Lève `ConflictError` si déjà attachée — utiliser `reattach_to`
        pour changer d'attachement.
        """
        if self.publication_id is not None:
            raise ConflictError(
                f"SourcePublication {self.source}:{self.source_id} déjà attachée "
                f"à publication_id={self.publication_id}",
            )
        self.publication_id = pub_id

    def reattach_to(self, new_pub_id: int) -> None:
        """Déplace l'attachement d'une publication canonique à une autre
        (typiquement lors d'une cascade de fusion).

        Lève `ConflictError` si non encore attachée — utiliser
        `attach_to` pour le premier attachement.
        """
        if self.publication_id is None:
            raise ConflictError(
                f"SourcePublication {self.source}:{self.source_id} n'est pas attachée ; "
                "utiliser attach_to pour le premier attachement",
            )
        self.publication_id = new_pub_id
