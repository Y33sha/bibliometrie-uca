"""Graphe de dépendances du pipeline : les nœuds, ce qu'ils lisent et écrivent, dans l'ordre d'exécution actuel.

Une donnée se désigne par sa table (`"journals"`) ou par une colonne (`"journals.journal_type"`) ; `"journals.id"` désigne l'existence des lignes, que créent et suppriment les écrivains. Une table et l'une de ses colonnes se recouvrent.

Un nœud dépend des nœuds placés avant lui qui écrivent ce qu'il lit. Une lecture déclarée `previous_run` lit aussi ce qu'un nœud placé après lui, ou lui-même, a écrit au run précédent. Les tests vérifient que l'ordre d'exécution ne fait lire à aucun nœud une donnée écrite après lui, sauf lecture du run précédent déclarée.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass


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


def _node(
    name: str,
    group: str,
    *,
    reads: Iterable[str] = (),
    writes: Iterable[str] = (),
    previous_run: Iterable[str] = (),
    network: str | None = None,
) -> Node:
    return Node(
        name,
        group,
        frozenset(reads),
        frozenset(writes),
        frozenset(previous_run),
        network,
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
    """Pour chaque nœud, les nœuds placés avant lui qui écrivent ce qu'il lit."""
    return {
        reader.name: {writer.name for writer in nodes[:i] if _writes_read(reader, writer)}
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


# Acquisition : les canaux écrivent la dernière observation d'un document dans `staging`, dans un ordre indifférent. Leurs lectures de `staging` dédoublonnent et valent quel que soit l'ordre.
_SOURCES = ("hal", "openalex", "scanr", "theses", "datacite", "wos")
_DOI_CHANNELS = ("crossref", "datacite", "openalex", "scanr", "wos")
# Ordre de normalisation : la source qui fait le plus autorité d'abord.
_NORMALIZE_ORDER = ("theses", "crossref", "datacite", "scanr", "hal", "openalex", "wos")
# Référentiels que la normalisation trouve ou crée, et que `publishers_journals` fusionne et supprime.
_CONTAINERS = (
    "publishers",
    "publisher_name_forms",
    "journals",
    "journal_issns",
    "journal_name_forms",
    "monographs",
)

NODES: tuple[Node, ...] = (
    _node(
        "perimeter_structures",
        "run",
        reads=("perimeters", "structure_tutelles", "structures"),
        writes=("perimeter_structures",),
    ),
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
        )
        for source in _SOURCES
    ),
    _node(
        "resolve_ra.resolve_prefixes",
        "resolve_ra",
        reads=(
            "doi_prefixes.id",
            "source_publications.doi",
            "source_publications.external_ids",
            "source_publications.publication_id",
            "publications.in_perimeter",
            "publication_relations",
        ),
        writes=("doi_prefixes.id", "doi_prefixes.ra"),
        previous_run=(
            "doi_prefixes.id",
            "source_publications",
            "publications",
            "publication_relations",
        ),
        network="doi.org",
    ),
    *(
        _node(
            f"fetch_missing.{channel}",
            "fetch_missing",
            reads=(
                "config",
                "staging",
                "failed_lookups",
                "source_publications",
                "publications.in_perimeter",
                "publications.doc_type",
                "doi_prefixes.ra",
                "publication_relations",
            ),
            writes=("staging", "failed_lookups"),
            previous_run=(
                "staging",
                "failed_lookups",
                "source_publications",
                "publications",
                "doi_prefixes",
                "publication_relations",
            ),
            network=network,
        )
        for channel, network in (
            ("hal_by_id", "hal"),
            ("hal_by_nnt", "hal"),
            *((f"doi.{source}", source) for source in _DOI_CHANNELS),
        )
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
        for source in _SOURCES
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
                "source_publications",
                "source_authorships",
                "author_identifying_keys",
                "addresses",
                "language_forms",
                *_CONTAINERS,
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
                *_CONTAINERS,
            ),
            # Ses propres lignes de `staging`, notices et signatures, et les référentiels que trouvent ou créent toutes les sources et que `publishers_journals` fusionne et supprime.
            previous_run=(
                "staging",
                "source_publications",
                "source_authorships",
                "author_identifying_keys",
                "addresses",
                *_CONTAINERS,
            ),
        )
        for source in _NORMALIZE_ORDER
    ),
    _node(
        "normalize.prune_disappeared",
        "normalize",
        reads=("staging.disappeared_at", "source_publications.id"),
        writes=("source_publications.id", "source_publications.keys_dirty"),
        previous_run=("source_publications",),
    ),
    _node(
        "normalize.cleanup_orphan_identities",
        "normalize",
        reads=("source_authorships.identity_id", "author_identifying_keys.id"),
        writes=("author_identifying_keys.id",),
        previous_run=("source_authorships",),
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
        ),
        writes=(
            "source_authorship_structures",
            "source_authorships.in_perimeter",
            "source_publications.keys_dirty",
        ),
        previous_run=("source_publications.publication_id",),
    ),
    _node(
        "publishers_journals.resolve_publishers",
        "publishers_journals",
        reads=(
            "doi_prefixes.id",
            "doi_prefixes.publisher_checked_at",
            "source_publications.doi",
            "publishers.id",
            "publisher_name_forms",
        ),
        writes=(
            "doi_prefixes.publisher_id",
            "doi_prefixes.publisher_checked_at",
            "doi_prefixes.ra",
            "publishers.id",
            "publisher_name_forms",
        ),
        previous_run=("source_publications.doi", "publishers", "publisher_name_forms"),
        network="crossref, datacite",
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
            "journals.title_normalized",
            "journals.pub_count",
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
            "source_publications.raw_metadata",
            "source_publications.doc_type",
        ),
    ),
    _node(
        "publishers_journals.delete_empty_containers",
        "publishers_journals",
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
        previous_run=(
            "publications",
            "source_publications.journal_id",
            "apc_payments",
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
            "source_publications",
            "journals.journal_type",
            "journals.oa_model",
            "monographs.proceedings",
            "doi_prefixes",
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
        previous_run=("source_publications",),
    ),
    _node(
        "metadata_correction.cluster",
        "metadata_correction",
        reads=("source_publications",),
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
        ),
        writes=(
            "publications",
            "publications_detail",
            "source_publications.publication_id",
            "source_publications.keys_dirty",
            "apc_payments.publication_id",
        ),
        previous_run=("source_publications.countries", "publications"),
    ),
    _node(
        "publications.delete_without_sources",
        "publications",
        reads=("publications.id", "source_publications.publication_id"),
        writes=("publications.id",),
        previous_run=("publications",),
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
            "persons_rh",
            "rejected_authorships",
            "distinct_persons",
        ),
        writes=(
            "source_authorships.person_id",
            "source_authorships.resolution_mode",
            "source_authorships.neutralized_identifiers",
            "persons",
            "person_identifiers",
            "person_name_forms",
        ),
        previous_run=("person_name_forms",),
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
    ),
    _node(
        "authorships.build",
        "authorships",
        reads=(
            "source_authorships.person_id",
            "source_authorships.source_publication_id",
            "source_authorships.author_position",
            "source_authorships.is_corresponding",
            "source_authorships.roles",
            "source_authorships.in_perimeter",
            "source_publications.publication_id",
            "publications.id",
            "rejected_authorships",
            "confirmed_authorships",
            "authorships",
        ),
        writes=("authorships",),
        previous_run=("publications",),
    ),
    _node(
        "authorships.publications_in_perimeter",
        "authorships",
        reads=("authorships", "persons.exclusion", "publications.id"),
        writes=("publications.in_perimeter",),
        previous_run=("publications",),
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
        previous_run=("publications",),
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
        previous_run=("publications", "addresses"),
    ),
    _node(
        "relations.rebuild",
        "relations",
        reads=(
            "source_publications",
            "publications.id",
            "publications.doc_type",
            "publications.doi",
            "publications.title_normalized",
            "publications.pub_year",
            "publication_relations",
        ),
        writes=("publication_relations",),
        previous_run=("source_publications", "publications"),
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
        previous_run=("publications", "subjects"),
    ),
    _node(
        "subjects.usage",
        "subjects",
        reads=(
            "publication_subjects",
            "subjects.id",
            "publications.id",
            "publications.in_perimeter",
        ),
        writes=("subjects.usage_count", "subject_cooccurrences"),
        previous_run=("publications", "subjects"),
    ),
    _node(
        "countries.detect",
        "countries",
        reads=(
            "place_name_forms",
            "countries",
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
        previous_run=("publications",),
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
            "source_publications.external_ids",
            "config",
        ),
        writes=("publications.oa_status", "publications.unpaywall_checked_at"),
    ),
)
