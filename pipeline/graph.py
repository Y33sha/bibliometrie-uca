"""Graphe de dépendances du pipeline : les nœuds, ce qu'ils lisent et écrivent, dans l'ordre d'exécution actuel. Chaque nœud appartient à une phase, et l'ordre des phases est celui de leurs nœuds.

Une donnée se désigne par sa table (`"journals"`) ou par une colonne (`"journals.journal_type"`) ; `"journals.id"` désigne l'existence des lignes, que créent et suppriment les écrivains. Une table et l'une de ses colonnes se recouvrent.

Un nœud dépend des nœuds placés avant lui qui écrivent ce qu'il lit. Une lecture déclarée `previous_run` lit aussi ce qu'un nœud placé après lui, ou lui-même, a écrit au run précédent. Les tests vérifient que l'ordre d'exécution ne fait lire à aucun nœud une donnée écrite après lui, sauf lecture du run précédent déclarée.

La maintenance d'un nœud (`VACUUM`, `ANALYZE`) suit ses écritures et ne crée aucune dépendance. Des nœuds consécutifs du même `lot` s'exécutent en parallèle : leurs écritures communes ne dépendent pas de leur ordre, et aucun ne dépend d'un autre du lot.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from domain.sources.registry import (
    ALL_SOURCES,
    DOI_SEARCHABLE_SOURCES,
    HARVESTED_SOURCES,
    SOURCE_PRIORITY,
    Source,
)


@dataclass(frozen=True, slots=True)
class Node:
    name: str
    # Phase qui exécute le nœud : groupe d'affichage et de sélection.
    group: str
    reads: frozenset[str] = frozenset()
    writes: frozenset[str] = frozenset()
    # Lectures de données écrites au run précédent, par un nœud plus loin dans l'ordre ou par le nœud lui-même.
    previous_run: frozenset[str] = frozenset()
    # API interrogée, si le nœud sort sur le réseau.
    network: str | None = None
    # Maintenance physique des tables, dans l'ordre : `VACUUM staging`, `ANALYZE authorships`.
    maintenance: tuple[str, ...] = ()
    # Lot de nœuds consécutifs exécutés en parallèle.
    lot: str | None = None


@dataclass(frozen=True, slots=True)
class _GroupIo:
    """Lectures et écritures communes à tous les nœuds d'une phase."""

    reads: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()
    previous_run: tuple[str, ...] = ()


_GROUP_IO: dict[str, _GroupIo] = {
    # Identifiants des publications du périmètre, cherchés dans les autres sources ; échecs retenus dans `failed_lookups`.
    "fetch_missing": _GroupIo(
        reads=(
            "config",
            "staging",
            "failed_lookups",
            "source_publications.source",
            "source_publications.external_ids",
            "source_publications.publication_id",
            "publications.in_perimeter",
        ),
        writes=("staging", "failed_lookups"),
        previous_run=(
            "staging",
            "failed_lookups",
            "source_publications",
            "publications.in_perimeter",
        ),
    ),
}


def _node(
    name: str,
    group: str,
    *,
    reads: Iterable[str] = (),
    writes: Iterable[str] = (),
    previous_run: Iterable[str] = (),
    network: str | None = None,
    maintenance: tuple[str, ...] = (),
    lot: str | None = None,
) -> Node:
    """Nœud de `group`, avec les lectures et écritures communes à la phase (`_GROUP_IO`)."""
    shared = _GROUP_IO.get(group, _GroupIo())
    return Node(
        name,
        group,
        frozenset((*shared.reads, *reads)),
        frozenset((*shared.writes, *writes)),
        frozenset((*shared.previous_run, *previous_run)),
        network,
        maintenance,
        lot,
    )


def overlaps(a: str, b: str) -> bool:
    """Deux données se recouvrent : même table, et même colonne si les deux en désignent une."""
    table_a, _, column_a = a.partition(".")
    table_b, _, column_b = b.partition(".")
    return table_a == table_b and (not column_a or not column_b or column_a == column_b)


def _overlaps_any(item: str, items: Iterable[str]) -> bool:
    return any(overlaps(item, other) for other in items)


def _affected_by(read: str, write: str) -> bool:
    """L'écriture `write` change ce que lit `read`. Créer ou supprimer des lignes (`id`) change toutes les lectures de la table."""
    return overlaps(read, write) or (
        write.partition(".")[2] == "id" and read.partition(".")[0] == write.partition(".")[0]
    )


def _writes_read(reader: Node, writer: Node) -> list[str]:
    return [r for r in reader.reads if any(_affected_by(r, w) for w in writer.writes)]


def dependencies(nodes: Sequence[Node]) -> dict[str, set[str]]:
    """Pour chaque nœud, les nœuds placés avant lui, hors de son lot, qui écrivent ce qu'il lit."""
    return {
        reader.name: {
            writer.name
            for writer in nodes[:i]
            if (reader.lot is None or writer.lot != reader.lot) and _writes_read(reader, writer)
        }
        for i, reader in enumerate(nodes)
    }


def order_violations(nodes: Sequence[Node]) -> list[tuple[str, str, str]]:
    """Triplets (lecteur, donnée, écrivain) où l'écrivain, placé après le lecteur, écrit une donnée que le lecteur lit sans la déclarer lue au run précédent."""
    return sorted(
        (reader.name, item, writer.name)
        for i, reader in enumerate(nodes)
        for writer in nodes[i + 1 :]
        for item in _writes_read(reader, writer)
        if not _overlaps_any(item, reader.previous_run)
    )


# Référentiels que la normalisation trouve ou crée, et que `publishers_journals` fusionne et supprime.
_CONTAINERS = (
    "publishers",
    "publisher_name_forms",
    "journals",
    "journal_issns",
    "journal_name_forms",
    "monographs",
)


# Sources que la phase `extract_by_person` interroge.
PERSON_SEARCHED_SOURCES: tuple[Source, ...] = (Source.DATACITE, Source.CROSSREF)


def _containers(source: Source) -> tuple[str, ...]:
    """Référentiels de publication que lit et écrit la normalisation de `source` : aucun pour theses.fr."""
    return () if source == Source.THESES else _CONTAINERS


NODES: tuple[Node, ...] = (
    _node(
        "perimeter_structures",
        "run",
        reads=("perimeters", "structure_tutelles", "structures"),
        writes=("perimeter_structures",),
    ),
    # Acquisition : les canaux écrivent la dernière observation d'un document dans `staging`, dans un ordre indifférent. Leurs lectures de `staging` dédoublonnent et valent quel que soit l'ordre.
    *(
        _node(
            f"extract.{source}",
            "extract",
            reads=(
                "config",
                "structures",
                "perimeters",
                "perimeter_structures",
                "staging",
                "pipeline_phase_executions",
            ),
            writes=("staging",),
            previous_run=("staging", "pipeline_phase_executions"),
            network=source,
            lot="extract",
        )
        for source in HARVESTED_SOURCES
    ),
    # Interrogation par identifiant de personne : identifiants des personnes RH, posés par la phase `persons` au run précédent.
    *(
        _node(
            f"extract_by_person.{source}",
            "extract_by_person",
            reads=("config", "persons_rh", "person_identifiers", "staging"),
            writes=("staging",),
            previous_run=("staging", "person_identifiers"),
            network=source,
            lot="extract_by_person",
        )
        for source in PERSON_SEARCHED_SOURCES
    ),
    _node("fetch_missing.hal_by_id", "fetch_missing", network="hal"),
    _node(
        "fetch_missing.hal_by_nnt",
        "fetch_missing",
        reads=("publications.doc_type",),
        previous_run=("publications.doc_type",),
        network="hal",
    ),
    *(
        _node(
            f"fetch_missing.doi.{source}",
            "fetch_missing",
            # DOI candidats de la vue `candidate_dois`, et agence d'enregistrement pour Crossref et DataCite.
            reads=(
                "source_publications.doi",
                "publication_relations",
                *(("doi_prefixes.ra",) if source in (Source.CROSSREF, Source.DATACITE) else ()),
            ),
            previous_run=("doi_prefixes", "publication_relations"),
            network=source,
            lot="fetch_missing.doi",
        )
        for source in DOI_SEARCHABLE_SOURCES
    ),
    *(
        _node(
            f"fetch_stale.{source}",
            "fetch_stale",
            reads=("config", "staging", "source_publications.pub_year"),
            writes=("staging",),
            previous_run=("staging", "source_publications"),
            network=source,
        )
        for source in ALL_SOURCES
    ),
    _node(
        "fetch_truncated.refetch_openalex",
        "fetch_truncated",
        reads=("staging",),
        writes=("staging",),
        previous_run=("staging",),
        network="openalex",
    ),
    *(
        _node(
            f"normalize.{source}",
            "normalize",
            reads=(
                "staging",
                "source_publications.id",
                "source_publications.authors_hash",
                "source_authorships.id",
                "source_authorships.author_position",
                "source_authorships.identity_id",
                "source_authorships.content_hash",
                "author_identifying_keys",
                "addresses.id",
                "addresses.countries",
                "addresses.suggested_countries",
                *_containers(source),
            ),
            writes=(
                "staging.processed",
                "staging.raw_data",
                "source_publications",
                "source_authorships",
                "source_authorship_addresses",
                "source_authorship_rors",
                "author_identifying_keys",
                "addresses.id",
                "addresses.countries",
                "addresses.suggested_countries",
                *_containers(source),
            ),
            # Ses propres lignes de `staging`, notices et signatures, et les référentiels que trouvent ou créent toutes les sources et que `publishers_journals` fusionne et supprime.
            previous_run=(
                "staging",
                "source_publications",
                "source_authorships",
                "author_identifying_keys",
                "addresses",
                *_containers(source),
            ),
        )
        for source in SOURCE_PRIORITY
    ),
    _node(
        "normalize.prune_disappeared",
        "normalize",
        reads=(
            "staging.disappeared_at",
            "source_publications.id",
            "source_publications.staging_id",
            "source_publications.publication_id",
        ),
        # La suppression d'une notice emporte ses signatures, leurs adresses et ROR, et les décisions qui les visent.
        writes=(
            "source_publications.id",
            "source_publications.keys_dirty",
            "source_authorships.id",
            "source_authorship_addresses",
            "source_authorship_rors",
            "confirmed_authorships",
            "rejected_authorships",
        ),
        previous_run=("source_publications",),
    ),
    _node(
        "normalize.cleanup_orphan_identities",
        "normalize",
        reads=("source_authorships.identity_id", "author_identifying_keys.id"),
        writes=("author_identifying_keys.id",),
        previous_run=("source_authorships",),
        # La normalisation vide `staging.raw_data`. `VACUUM FULL` en mode full.
        maintenance=("VACUUM staging",),
    ),
    _node(
        "affiliations.refresh_ror",
        "affiliations",
        reads=("ror_dump_imports",),
        writes=("ror_organizations", "ror_relations", "ror_dump_imports"),
        previous_run=("ror_dump_imports",),
        network="zenodo",
    ),
    _node(
        "affiliations.resolve_addresses",
        "affiliations",
        reads=(
            "structure_name_forms",
            "structures",
            "addresses.id",
            "addresses.normalized_text",
            "address_structures",
        ),
        writes=("address_structures.id", "address_structures.matched_form_id"),
        previous_run=("addresses",),
    ),
    _node(
        "affiliations.populate",
        "affiliations",
        reads=(
            "address_structures",
            "perimeter_structures",
            "config",
            "source_authorship_addresses",
            "source_authorships.source_publication_id",
            "source_publications.publication_id",
            # Identité des personnes RH : `rh_identity_signatures`.
            "persons_rh",
            "person_identifiers",
            "rejected_authorships",
            "author_identifying_keys",
            "source_authorships.identity_id",
            "source_authorships.neutralized_identifiers",
            "source_authorships.source",
            "source_publications.pub_year",
        ),
        writes=(
            "source_authorship_structures",
            "source_authorships.in_perimeter",
            "source_publications.keys_dirty",
        ),
        previous_run=(
            "source_publications.publication_id",
            "person_identifiers",
            "source_authorships.neutralized_identifiers",
        ),
    ),
    _node(
        "resolve_ra.resolve_prefixes",
        "resolve_ra",
        reads=(
            "doi_prefixes.id",
            "source_publications.doi",
            "source_publications.external_ids",
            "publication_relations",
        ),
        writes=("doi_prefixes.id", "doi_prefixes.ra"),
        previous_run=("source_publications", "publication_relations"),
        network="doi.org",
    ),
    _node(
        "publishers_journals.resolve_crossref_publishers",
        "publishers_journals",
        reads=(
            "doi_prefixes.id",
            "doi_prefixes.ra",
            "doi_prefixes.publisher_id",
            "doi_prefixes.publisher_name_normalized",
            "doi_prefixes.crossref_checked_at",
            "source_publications.doi",
            "publishers.id",
            "publisher_name_forms",
        ),
        writes=(
            "doi_prefixes.ra",
            "doi_prefixes.publisher_id",
            "doi_prefixes.publisher_name_raw",
            "doi_prefixes.publisher_name_normalized",
            "doi_prefixes.crossref_member_id",
            "doi_prefixes.crossref_checked_at",
            "publishers.id",
            "publisher_name_forms",
        ),
        # L'agence et l'éditeur qu'a posés `resolve_datacite_publishers` sortent un préfixe de la sélection.
        previous_run=(
            "source_publications.doi",
            "publishers",
            "publisher_name_forms",
            "doi_prefixes",
        ),
        network="crossref",
    ),
    _node(
        "publishers_journals.resolve_datacite_publishers",
        "publishers_journals",
        reads=(
            "doi_prefixes.id",
            "doi_prefixes.ra",
            "doi_prefixes.publisher_id",
            "doi_prefixes.publisher_name_normalized",
            "doi_prefixes.crossref_checked_at",
            "doi_prefixes.datacite_checked_at",
            "publishers.id",
            "publisher_name_forms",
        ),
        writes=(
            "doi_prefixes.ra",
            "doi_prefixes.publisher_id",
            "doi_prefixes.publisher_name_raw",
            "doi_prefixes.publisher_name_normalized",
            "doi_prefixes.client_name_raw",
            "doi_prefixes.client_name_normalized",
            "doi_prefixes.datacite_client_symbol",
            "doi_prefixes.datacite_checked_at",
            "publishers.id",
            "publisher_name_forms",
        ),
        previous_run=("publishers", "publisher_name_forms"),
        network="datacite",
    ),
    _node(
        "publishers_journals.enrich_journals_from_openalex",
        "publishers_journals",
        reads=(
            "journals.id",
            "journals.openalex_id",
            "journals.journal_type",
            "journals.manual_fields",
        ),
        writes=("journals.apc_amount", "journals.apc_currency", "journals.journal_type"),
        previous_run=("journals",),
        network="openalex",
    ),
    _node(
        "publishers_journals.check_journals_in_sudoc",
        "publishers_journals",
        reads=(
            "journals.id",
            "journals.title",
            "journals.journal_type",
            "journals.manual_fields",
            "journal_issns",
            "source_publications.biblio",
            "source_publications.journal_id",
        ),
        writes=(
            "journal_issns",
            "journals.title",
            "journals.title_normalized",
            "journal_name_forms",
        ),
        previous_run=("journals", "journal_issns", "source_publications.journal_id"),
        network="sudoc",
    ),
    _node(
        "publishers_journals.merge_duplicate_journals",
        "publishers_journals",
        reads=(
            "journal_issns",
            "journals.id",
            "journals.title",
            "journals.title_normalized",
            "journals.pub_count",
            "journals.journal_type",
            "journals.oa_model",
            "journals.apc_amount",
            "journals.apc_currency",
            "journals.manual_fields",
            "source_publications.journal_id",
            "source_publications.pub_year",
            "source_publications.doi",
            "source_publications.publication_id",
        ),
        writes=(
            "journals",
            "journal_issns",
            "journal_name_forms",
            "journal_doi_namespaces",
            "monographs.journal_id",
            "apc_payments.journal_id",
            "source_publications.journal_id",
            "source_publications.doc_type",
            "source_publications.oa_status",
            "source_publications.language",
            "source_publications.external_ids",
            "source_publications.raw_metadata",
            "publications",
            "publications_detail",
            "publishers.pub_count",
        ),
        previous_run=(
            "journals",
            "journal_issns",
            "source_publications.publication_id",
            "source_publications.journal_id",
            "source_publications.doi",
        ),
    ),
    _node(
        "publishers_journals.type_proceedings_journals",
        "publishers_journals",
        reads=(
            "journals.id",
            "journals.title",
            "journals.journal_type",
            "journals.manual_fields",
            "journal_issns",
            "source_publications.raw_metadata",
            "source_publications.doc_type",
            "source_publications.journal_id",
        ),
        writes=("journals.journal_type",),
        previous_run=(
            "journals",
            "journal_issns",
            # Type brut de la source, `coalesce(raw_metadata->'doc_type'->>'raw', doc_type)` : la correction ne le change pas.
            "source_publications.raw_metadata",
            "source_publications.doc_type",
            "source_publications.journal_id",
        ),
    ),
    _node(
        "publishers_journals.learn_journal_doi_namespaces",
        "publishers_journals",
        reads=(
            "source_publications.doi",
            "source_publications.journal_id",
            "source_publications.raw_metadata",
            "journals.journal_type",
        ),
        writes=("journal_doi_namespaces",),
        previous_run=("source_publications", "journals"),
    ),
    _node(
        "publishers_journals.enrich_journals_from_doaj",
        "publishers_journals",
        reads=("journal_issns", "journals.doaj_imported_at", "config"),
        writes=("journals.is_in_doaj", "journals.doaj_payload", "journals.doaj_imported_at"),
        previous_run=("journal_issns", "journals"),
        network="doaj",
    ),
    _node(
        "publishers_journals.merge_duplicate_monographs",
        "publishers_journals",
        reads=("monographs.id", "monographs.title_normalized"),
        writes=("monographs.id", "source_publications.monograph_id", "publications.monograph_id"),
        previous_run=("monographs",),
    ),
    _node(
        "publishers_journals.link_monographs_to_collections",
        "publishers_journals",
        reads=(
            "monographs",
            "source_publications.monograph_id",
            "source_publications.journal_id",
            "journal_issns",
        ),
        writes=(
            "journals.id",
            "journals.journal_type",
            "journal_name_forms",
            "monographs.journal_id",
        ),
        previous_run=("monographs", "source_publications.journal_id", "journal_issns"),
    ),
    _node(
        "publishers_journals.type_proceedings_volumes",
        "publishers_journals",
        reads=(
            "monographs.id",
            "monographs.journal_id",
            "journals.journal_type",
            "source_publications.raw_metadata",
            "source_publications.doc_type",
        ),
        writes=("monographs.proceedings",),
        previous_run=(
            "monographs",
            "journals",
            # Type brut de la source, `coalesce(raw_metadata->'doc_type'->>'raw', doc_type)` : la correction ne le change pas.
            "source_publications.raw_metadata",
            "source_publications.doc_type",
        ),
    ),
    _node(
        "metadata_correction.journal_by_doi",
        "metadata_correction",
        reads=(
            "journal_doi_namespaces",
            "source_publications.doi",
            "source_publications.journal_id",
            "source_publications.raw_metadata",
            "source_publications.doc_type",
        ),
        writes=(
            "source_publications.journal_id",
            "source_publications.raw_metadata",
            "source_publications.keys_dirty",
        ),
        previous_run=("source_publications",),
    ),
    _node(
        "metadata_correction.unary",
        "metadata_correction",
        reads=(
            *(
                f"source_publications.{column}"
                for column in (
                    "id",
                    "source",
                    "source_id",
                    "title",
                    "doc_type",
                    "doi",
                    "journal_id",
                    "monograph_id",
                    "oa_status",
                    "language",
                    "urls",
                    "external_ids",
                    "raw_metadata",
                    "embargo_until",
                    "meta",
                )
            ),
            "journals.journal_type",
            "journals.oa_model",
            "monographs.proceedings",
            "doi_prefixes.publisher_id",
            "publishers.publisher_type",
            "language_forms",
        ),
        writes=(
            "source_publications.doc_type",
            "source_publications.oa_status",
            "source_publications.language",
            "source_publications.external_ids",
            "source_publications.raw_metadata",
            "source_publications.keys_dirty",
        ),
        # Les référentiels vides, supprimés plus loin, ne sont référencés par aucune notice : la correction ne les atteint pas.
        previous_run=(
            "source_publications",
            "journals.journal_type",
            "journals.oa_model",
            "monographs.proceedings",
            "publishers.publisher_type",
        ),
    ),
    _node(
        "metadata_correction.cluster",
        "metadata_correction",
        reads=tuple(
            f"source_publications.{column}"
            for column in (
                "id",
                "source",
                "doc_type",
                "doi",
                "title_normalized",
                "raw_metadata",
                "meta",
            )
        ),
        writes=(
            "source_publications.doi",
            "source_publications.raw_metadata",
            "source_publications.keys_dirty",
        ),
        previous_run=("source_publications",),
    ),
    _node(
        "publications.reconcile",
        "publications",
        reads=(
            "source_publications",
            "source_authorships.in_perimeter",
            "publications",
            "apc_payments",
            "journals.journal_type",
            "monographs.journal_id",
        ),
        writes=(
            "publications",
            "publications_detail",
            "source_publications.publication_id",
            "source_publications.keys_dirty",
            "apc_payments.publication_id",
        ),
        # Statut confirmé par Unpaywall ; publications que `authorships.purge_orphan_publications` supprime ; revues et monographies vides supprimées par `authorships.delete_empty_containers`.
        previous_run=(
            "source_publications.countries",
            "publications.id",
            "publications.oa_status",
            "publications.unpaywall_checked_at",
            "journals",
            "monographs",
        ),
    ),
    _node(
        "publications.delete_without_sources",
        "publications",
        reads=("publications.id", "source_publications.publication_id"),
        writes=("publications.id",),
        # Lignes que `authorships.purge_orphan_publications` supprime plus loin dans le même run.
        previous_run=("publications.id",),
    ),
    _node(
        "persons.resolve",
        "persons",
        reads=(
            "confirmed_authorships",
            "author_identifying_keys",
            "source_authorships.person_id",
            "source_authorships.resolution_mode",
            "source_authorships.neutralized_identifiers",
            "source_authorships.identity_id",
            "source_authorships.in_perimeter",
            "source_authorships.source_publication_id",
            "source_publications.publication_id",
            "person_identifiers",
            "person_name_forms",
            "persons",
            "rejected_authorships",
        ),
        writes=(
            "source_authorships.person_id",
            "source_authorships.resolution_mode",
            "source_authorships.neutralized_identifiers",
            "persons",
            "person_identifiers",
            "person_name_forms",
        ),
        # Formes de nom peuplées, signatures détachées et personnes supprimées par `populate_person_name_forms` et `purge`.
        previous_run=(
            "person_name_forms",
            "persons",
            "person_identifiers",
            "source_authorships.person_id",
            "source_authorships.resolution_mode",
        ),
    ),
    _node(
        "persons.populate_person_name_forms",
        "persons",
        reads=(
            "persons",
            "source_authorships.person_id",
            "source_authorships.identity_id",
            "author_identifying_keys",
            "person_name_forms",
        ),
        writes=("person_name_forms",),
        # Signatures détachées et personnes supprimées par `purge`.
        previous_run=("persons", "person_name_forms", "source_authorships.person_id"),
    ),
    _node(
        "persons.purge",
        "persons",
        reads=(
            "source_authorships.person_id",
            "source_authorships.resolution_mode",
            "source_authorships.identity_id",
            "source_authorships.source_publication_id",
            "source_authorships.neutralized_identifiers",
            "source_publications.publication_id",
            "author_identifying_keys",
            "person_name_forms",
            "person_identifiers",
            "persons",
            "persons_rh",
            "confirmed_authorships",
            "rejected_authorships",
            "distinct_persons",
        ),
        # La suppression d'une personne emporte ses formes de nom.
        writes=(
            "source_authorships.person_id",
            "source_authorships.resolution_mode",
            "person_identifiers.id",
            "persons.id",
            "person_name_forms.id",
        ),
        # `normalize` et `persons` réécrivent en masse `source_authorships.person_id`.
        maintenance=("ANALYZE source_authorships",),
    ),
    _node(
        "authorships.build",
        "authorships",
        reads=(
            "source_authorships.person_id",
            "source_authorships.source_publication_id",
            "source_publications.publication_id",
            "publications.id",
            "rejected_authorships",
            "confirmed_authorships",
            "authorships.id",
        ),
        writes=("authorships.id",),
        # Lignes que `authorships.purge_orphan_publications` supprime plus loin dans le même run.
        previous_run=("publications.id",),
        # Le planificateur estime la propagation des attributs sur les liens qui viennent d'être créés.
        maintenance=("ANALYZE authorships",),
    ),
    _node(
        "authorships.propagate",
        "authorships",
        reads=(
            "source_authorships.person_id",
            "source_authorships.source_publication_id",
            "source_authorships.author_position",
            "source_authorships.is_corresponding",
            "source_authorships.roles",
            "source_authorships.in_perimeter",
            "source_publications.publication_id",
            "authorships",
        ),
        writes=(
            "authorships.author_position",
            "authorships.is_corresponding",
            "authorships.in_perimeter",
            "authorships.roles",
        ),
    ),
    _node(
        "authorships.publications_in_perimeter",
        "authorships",
        reads=("authorships", "persons.exclusion", "publications.id"),
        writes=("publications.in_perimeter",),
        # Lignes que `authorships.purge_orphan_publications` supprime plus loin dans le même run.
        previous_run=("publications.id",),
    ),
    _node(
        "authorships.structures",
        "authorships",
        reads=(
            "authorships",
            "source_authorships.person_id",
            "source_authorships.source_publication_id",
            "source_publications.publication_id",
            "source_authorship_structures",
        ),
        writes=("authorship_structures", "publication_structures"),
    ),
    _node(
        "authorships.purge_orphan_publications",
        "authorships",
        reads=("publications.id", "authorships"),
        writes=("publications.id",),
    ),
    _node(
        "authorships.delete_empty_containers",
        "authorships",
        reads=(
            "monographs.id",
            "monographs.journal_id",
            "journals.id",
            "publishers.id",
            "source_publications.journal_id",
            "source_publications.monograph_id",
            "publications.journal_id",
            "publications.monograph_id",
            "apc_payments",
            "doi_prefixes.publisher_id",
            "journal_name_forms",
        ),
        writes=("monographs.id", "journals.id", "publishers.id", "journal_issns"),
    ),
    _node(
        "authorships.pub_counts",
        "authorships",
        reads=(
            "addresses.id",
            "source_authorship_addresses",
            "source_authorships.source_publication_id",
            "source_publications.publication_id",
            "source_publications.journal_id",
            "journals.id",
            "journals.publisher_id",
            "publishers.id",
            "publications.id",
            "publications.in_perimeter",
            "publications.journal_id",
        ),
        writes=("addresses.pub_count", "journals.pub_count", "publishers.pub_count"),
        previous_run=("addresses",),
    ),
    _node(
        "relations.rebuild",
        "relations",
        reads=(
            *(
                f"source_publications.{column}"
                for column in (
                    "meta",
                    "raw_metadata",
                    "doi",
                    "external_ids",
                    "doc_type",
                    "publication_id",
                )
            ),
            "publications.id",
            "publications.doc_type",
            "publications.doi",
            "publications.title_normalized",
            "publications.pub_year",
            "publication_relations",
        ),
        writes=("publication_relations",),
    ),
    _node(
        "subjects.ingest",
        "subjects",
        reads=(
            "publications.id",
            "publications.subjects_ingested_at",
            "source_publications.topics",
            "subjects",
            "publication_subjects",
        ),
        writes=("publication_subjects", "subjects.id", "publications.subjects_ingested_at"),
        previous_run=("publications.subjects_ingested_at", "subjects"),
    ),
    _node(
        "subjects.usage",
        "subjects",
        reads=(
            "publication_subjects",
            "subjects.id",
        ),
        writes=("subjects.usage_count", "subject_cooccurrences"),
        previous_run=("subjects",),
    ),
    _node(
        "countries.detect",
        "countries",
        reads=(
            "place_name_forms",
            "addresses.id",
            "addresses.normalized_text",
            "addresses.countries",
        ),
        writes=("addresses.countries", "addresses.countries_dirty"),
    ),
    _node(
        "countries.suggest",
        "countries",
        reads=(
            "addresses.id",
            "addresses.normalized_text",
            "addresses.countries",
            "addresses.suggested_countries",
        ),
        writes=("addresses.suggested_countries",),
        previous_run=("addresses",),
    ),
    _node(
        "countries.refresh_publication_countries",
        "countries",
        reads=(
            "source_authorships.countries_dirty",
            "source_authorships.source_publication_id",
            "source_authorship_addresses",
            "addresses.countries",
            "addresses.countries_dirty",
            "source_publications.publication_id",
            "source_publications.countries",
            "publications.id",
        ),
        writes=(
            "source_publications.countries",
            "publications.countries",
            "source_authorships.countries_dirty",
            "addresses.countries_dirty",
        ),
    ),
    _node(
        "oa_status.verify_unpaywall",
        "oa_status",
        reads=(
            "publications.id",
            "publications.doi",
            "publications.oa_status",
            "publications.unpaywall_checked_at",
            "source_publications.publication_id",
            "source_publications.source",
            "source_publications.oa_status",
            "config",
        ),
        writes=("publications.oa_status", "publications.unpaywall_checked_at"),
        network="unpaywall",
    ),
)


# ── Phases ────────────────────────────────────────────────────

_RUN_GROUP = "run"
"""Groupe des nœuds que l'orchestrateur exécute avant toute phase."""

PHASE_ORDER: tuple[str, ...] = tuple(
    dict.fromkeys(node.group for node in NODES if node.group != _RUN_GROUP)
)
"""Ordre d'exécution des phases : celui de leurs nœuds dans `NODES`."""

PHASE_LIBELLES: dict[str, str] = {
    "extract": "Moissonnage par affiliation",
    "extract_by_person": "Moissonnage par personne",
    "resolve_ra": "Résolution des agences d'enregistrement des DOI",
    "fetch_missing": "Recherche dans chaque source des documents trouvés dans les autres",
    "fetch_stale": "Recherche des documents non revus depuis {delai}",
    "fetch_truncated": "Re-téléchargement des documents OpenAlex tronqués à 100 auteurs",
    "normalize": "Normalisation des données brutes",
    "affiliations": "Résolution des affiliations par signature",
    "publishers_journals": "Enrichissement des référentiels d'éditeurs et revues",
    "metadata_correction": "Correction des métadonnées de publication",
    "publications": "Dédoublonnage des publications",
    "persons": "Résolution de l'identité des personnes",
    "authorships": "Rafraîchissement des liens entre publications, personnes et structures",
    "relations": "Relations entre publications apparentées",
    "subjects": "Sujets des publications",
    "countries": "Pays associés aux signatures",
    "oa_status": "Statut open access des publications",
}
"""Ce que chaque phase produit, en une ligne lisible sans connaître le schéma.

Les champs entre accolades reçoivent une valeur de configuration au lancement de la phase.
"""

EXTRA_PHASES: frozenset[str] = frozenset({"relations", "subjects", "countries", "oa_status"})
"""Enrichissements, hors résolution d'entités : `--no-extras` les omet.

Aucune ne dépend d'une autre. Des phases placées avant elles lisent leurs sorties au run suivant : `resolve_ra` et `fetch_missing` lisent les relations, `normalize` et `publications` les pays, `publications` le statut open access.
"""

if not EXTRA_PHASES <= set(PHASE_ORDER):
    raise ValueError("EXTRA_PHASES nomme une phase absente du graphe")

if set(PHASE_LIBELLES) != set(PHASE_ORDER):
    raise ValueError("PHASE_LIBELLES et le graphe ne nomment pas les mêmes phases")
