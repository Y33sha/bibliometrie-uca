"""Normalisation des enregistrements sources INSPIRE-HEP.

- `staging` garde le `metadata` de la fiche, réduit aux champs demandés (`FIELDS`).
- L'adresse d'une contribution source est le nom de chaque institution rattachée par INSPIRE à l'auteur (`affiliations.value`). L'affiliation brute est écartée : elle reproduit les décalages d'affiliations de l'éditeur.
- Le ROR donné par INSPIRE (`affiliations_identifiers`) va sur l'adresse d'un auteur à une seule institution : la liste des ROR d'un auteur ne dit pas à quelle institution chacun correspond.
- Le titre abrégé de la revue (`Phys.Rev.D`), donné sans ISSN, reste un titre libre du conteneur.
"""

from __future__ import annotations

from collections.abc import Mapping

from domain.contributions.contribution_roles import ContributionRole
from domain.documents.dates import PublicationDate
from domain.persons.contributor_name import ContributorName
from domain.persons.identifiers import ORCID
from domain.source_records.biblio import compact_biblio
from domain.structures.identifiers import parse_ror_ids
from domain.types import JsonValue, as_mapping, as_sequence, as_str
from pipeline.ingestion.common.normalizer import Document, SourceNormalizer
from pipeline.ingestion.common.source_contributions import (
    AddressRecord,
    AuthorBlock,
    AuthorRecord,
    contributor_identifiers,
)
from pipeline.ingestion.common.source_records import SourceRecordUpsert
from pipeline.ingestion.common.staging import StagingRow
from pipeline.ingestion.inspire.payload import (
    abstract,
    biblio_parts,
    doc_type_token,
    journal_title,
    publication_date,
    record_id,
    record_identifiers,
    title,
)

_ROLES: dict[str, ContributionRole] = {
    "author": ContributionRole.AUTHOR,
    "editor": ContributionRole.EDITOR,
    "supervisor": ContributionRole.THESIS_DIRECTOR,
}
"""Rôles d'INSPIRE (`inspire_roles`). Un auteur sans rôle déclaré est auteur."""


def _author_name(author: Mapping[str, JsonValue]) -> ContributorName | None:
    """Lit le nom d'un auteur : nom et prénom séparés quand INSPIRE donne les deux, sinon le nom complet (`full_name`, « Nom, Prénom »)."""
    last = (as_str(author.get("last_name")) or "").strip()
    first = (as_str(author.get("first_name")) or "").strip()
    if last and first:
        return ContributorName.from_parts(last, first)
    return ContributorName.from_raw(as_str(author.get("full_name")) or last or first)


def _author_orcid(author: Mapping[str, JsonValue]) -> str | None:
    """Lit l'ORCID d'un auteur dans ses identifiants (`ids`, schéma `ORCID`)."""
    for entry in as_sequence(author.get("ids")):
        item = as_mapping(entry)
        if item.get("schema") == "ORCID" and (orcid := ORCID.normalize(as_str(item.get("value")))):
            return orcid
    return None


def _author_addresses(author: Mapping[str, JsonValue]) -> list[AddressRecord]:
    """Renvoie une adresse par institution rattachée à l'auteur, nommée comme dans INSPIRE. Une seule institution reçoit les ROR de l'auteur."""
    names = [
        name.strip()
        for entry in as_sequence(author.get("affiliations"))
        if (name := as_str(as_mapping(entry).get("value"))) and name.strip()
    ]
    rors = parse_ror_ids(
        [
            as_str(item.get("value"))
            for entry in as_sequence(author.get("affiliations_identifiers"))
            if (item := as_mapping(entry)).get("schema") == "ROR"
        ]
    )
    if len(names) == 1:
        return [AddressRecord(text=names[0], ror_ids=rors)]
    return [AddressRecord(text=name) for name in names]


def _author_roles(author: Mapping[str, JsonValue]) -> list[ContributionRole]:
    """Renvoie les rôles d'un auteur, sans doublon ; auteur à défaut de rôle connu."""
    roles = [
        _ROLES[r]
        for entry in as_sequence(author.get("inspire_roles"))
        if (r := as_str(entry)) in _ROLES
    ]
    return list(dict.fromkeys(roles)) or [ContributionRole.AUTHOR]


def build_inspire_author_records(block: AuthorBlock) -> list[AuthorRecord]:
    """Lit les contributions sources des auteurs d'une fiche, dans l'ordre de la liste. Un éditeur ou un directeur de thèse est sans position."""
    records: list[AuthorRecord] = []
    position = 0
    for entry in as_sequence(block.get("authors")):
        author = as_mapping(entry)
        name = _author_name(author)
        if name is None:
            continue
        roles = _author_roles(author)
        is_author = ContributionRole.AUTHOR in roles
        records.append(
            AuthorRecord(
                position=position if is_author else None,
                name=name,
                roles=roles,
                identifiers=contributor_identifiers(orcid=_author_orcid(author)),
                addresses=_author_addresses(author),
            )
        )
        position += is_author
    return records


def inspire_source_record(
    record: Mapping[str, JsonValue], staging_id: int, *, has_series: bool
) -> SourceRecordUpsert:
    """Construit l'enregistrement source d'une fiche, identifié par son numéro."""
    number = record_id(record)
    text = title(record)
    # Garantis par `parse` et par `SourceNormalizer`, qui écarte les documents sans titre.
    assert number is not None
    assert text is not None
    return SourceRecordUpsert(
        source="inspire",
        source_id=number,
        staging_id=staging_id,
        identifiers=record_identifiers(record),
        title=text,
        raw_doc_type=doc_type_token(record),
        container_title=journal_title(record) if not has_series else None,
        biblio=compact_biblio(**biblio_parts(record)),
        abstract=abstract(record),
    )


class InspireNormalizer(SourceNormalizer):
    SOURCE = "inspire"
    DEFAULT_BATCH_SIZE = 50
    FETCH_SUB_BATCH = 10
    """Une fiche de grande collaboration pèse environ 1,5 Mo."""

    def minimal_metadata(self, doc: Document) -> tuple[str | None, int | None]:
        date = publication_date(doc)
        return title(doc), date.year if date else None

    def parse(self, row: StagingRow) -> Document | None:
        """Renvoie la fiche, ou `None` sans numéro de fiche."""
        return row.raw_data if record_id(row.raw_data) else None

    def publication_date(self, doc: Document) -> PublicationDate | None:
        return publication_date(doc)

    def source_record(
        self, row: StagingRow, doc: Document, *, has_series: bool
    ) -> SourceRecordUpsert:
        return inspire_source_record(doc, row.id, has_series=has_series)

    def author_block(self, doc: Document) -> AuthorBlock:
        return {"authors": doc.get("authors")}

    def author_records(self, block: AuthorBlock) -> list[AuthorRecord]:
        return build_inspire_author_records(block)
