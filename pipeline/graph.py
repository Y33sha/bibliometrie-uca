"""Graphe de dépendances du pipeline : les tâches, ce qu'elles lisent et écrivent, dans l'ordre d'exécution actuel. Chaque tâche appartient à une phase, et l'ordre des phases est celui de leurs tâches.

Une donnée se désigne par sa table (`"journals"`) ou par une colonne (`"journals.journal_type"`) ; `"journals.id"` désigne l'existence des lignes, que créent et suppriment les écrivains. Une table et l'une de ses colonnes se recouvrent.

Une tâche dépend des tâches placées avant elle qui écrivent ce qu'elle lit. Une lecture déclarée `previous_run` lit aussi ce qu'une tâche placée après elle, ou elle-même, a écrit au run précédent. Les tests vérifient que l'ordre d'exécution ne fait lire à aucune tâche une donnée écrite après elle, sauf lecture du run précédent déclarée.

La maintenance d'une tâche (`VACUUM`, `ANALYZE`) suit ses écritures et ne crée aucune dépendance. Des tâches consécutives du même `parallel_group` s'exécutent en parallèle : leurs écritures communes ne dépendent pas de leur ordre, et aucune ne dépend d'une autre tâche du groupe.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from domain.sources.registry import (
    ALL_SOURCES,
    DOI_SEARCHABLE_SOURCES,
    HARVESTED_SOURCES,
    PERSON_SEARCHED_SOURCES,
    PROFILES,
    SOURCE_PRIORITY,
    Source,
)


@dataclass(frozen=True, slots=True)
class Task:
    name: str
    # Phase qui exécute la tâche : regroupement d'affichage et de sélection.
    phase: str
    reads: frozenset[str] = frozenset()
    writes: frozenset[str] = frozenset()
    # Lectures de données écrites au run précédent, par une tâche plus loin dans l'ordre ou par la tâche elle-même.
    previous_run: frozenset[str] = frozenset()
    # API interrogée, si la tâche sort sur le réseau.
    network: str | None = None
    # Maintenance physique des tables, dans l'ordre : `VACUUM staging`, `ANALYZE contributions`.
    maintenance: tuple[str, ...] = ()
    # Groupe de tâches consécutives exécutées en parallèle.
    parallel_group: str | None = None


@dataclass(frozen=True, slots=True)
class _PhaseIo:
    """Lectures et écritures communes à toutes les tâches d'une phase."""

    reads: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()
    previous_run: tuple[str, ...] = ()


_PHASE_IO: dict[str, _PhaseIo] = {
    # Identifiants des publications du périmètre, cherchés dans les autres sources ; échecs retenus dans `failed_lookups`.
    "fetch_missing": _PhaseIo(
        reads=(
            "config",
            "staging",
            "failed_lookups",
            "source_records.source",
            "source_records.external_ids",
            "source_records.publication_id",
            "publications.in_perimeter",
        ),
        writes=("staging", "failed_lookups"),
        previous_run=(
            "staging",
            "failed_lookups",
            "source_records",
            "publications.in_perimeter",
        ),
    ),
}


def _task(
    name: str,
    phase: str,
    *,
    reads: Iterable[str] = (),
    writes: Iterable[str] = (),
    previous_run: Iterable[str] = (),
    network: str | None = None,
    maintenance: tuple[str, ...] = (),
    parallel_group: str | None = None,
) -> Task:
    """Tâche de `phase`, avec les lectures et écritures communes à la phase (`_PHASE_IO`)."""
    shared = _PHASE_IO.get(phase, _PhaseIo())
    return Task(
        name,
        phase,
        frozenset((*shared.reads, *reads)),
        frozenset((*shared.writes, *writes)),
        frozenset((*shared.previous_run, *previous_run)),
        network,
        maintenance,
        parallel_group,
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


def _writes_read(reader: Task, writer: Task) -> list[str]:
    return [r for r in reader.reads if any(_affected_by(r, w) for w in writer.writes)]


def dependencies(tasks: Sequence[Task]) -> dict[str, set[str]]:
    """Pour chaque tâche, les tâches placées avant elle, hors de son groupe parallèle, qui écrivent ce qu'elle lit."""
    return {
        reader.name: {
            writer.name
            for writer in tasks[:i]
            if (reader.parallel_group is None or writer.parallel_group != reader.parallel_group)
            and _writes_read(reader, writer)
        }
        for i, reader in enumerate(tasks)
    }


def order_violations(tasks: Sequence[Task]) -> list[tuple[str, str, str]]:
    """Triplets (lecteur, donnée, écrivain) où l'écrivain, placé après le lecteur, écrit une donnée que le lecteur lit sans la déclarer lue au run précédent."""
    return sorted(
        (reader.name, item, writer.name)
        for i, reader in enumerate(tasks)
        for writer in tasks[i + 1 :]
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


def _containers(source: Source) -> tuple[str, ...]:
    """Référentiels de publication que lit et écrit la normalisation de `source` : aucun pour theses.fr."""
    return () if source == Source.THESES else _CONTAINERS


TASKS: tuple[Task, ...] = (
    _task(
        "perimeter_structures",
        "run",
        reads=("perimeters", "structure_parents", "structures"),
        writes=("perimeter_structures",),
    ),
    # Acquisition : les canaux écrivent la dernière observation d'un document dans `staging`, dans un ordre indifférent. Leurs lectures de `staging` dédoublonnent et valent quel que soit l'ordre.
    *(
        _task(
            f"harvest.{source}",
            "harvest",
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
            parallel_group="harvest",
        )
        for source in HARVESTED_SOURCES
    ),
    # Interrogation par identifiant de personne : identifiants des personnes RH, posés par la phase `persons` au run précédent.
    *(
        _task(
            f"harvest_by_person.{source}",
            "harvest_by_person",
            reads=("config", "hr_records", "person_identifiers", "staging"),
            writes=("staging",),
            previous_run=("staging", "person_identifiers"),
            network=source,
            parallel_group="harvest_by_person",
        )
        for source in PERSON_SEARCHED_SOURCES
    ),
    _task("fetch_missing.hal_by_id", "fetch_missing", network="hal"),
    _task(
        "fetch_missing.hal_by_nnt",
        "fetch_missing",
        reads=("publications.doc_type",),
        previous_run=("publications.doc_type",),
        network="hal",
    ),
    _task("fetch_missing.theses_by_nnt", "fetch_missing", network="theses"),
    *(
        _task(
            f"fetch_missing.doi.{source}",
            "fetch_missing",
            # DOI candidats de la vue `candidate_dois`, et agence d'enregistrement pour Crossref et DataCite.
            reads=(
                "source_records.doi",
                "publication_relations",
                *(("doi_prefixes.ra",) if PROFILES[source].registration_agency else ()),
            ),
            previous_run=("doi_prefixes", "publication_relations"),
            network=source,
            parallel_group="fetch_missing.doi",
        )
        for source in DOI_SEARCHABLE_SOURCES
    ),
    *(
        _task(
            f"fetch_stale.{source}",
            "fetch_stale",
            reads=("config", "staging", "source_records.publication_year"),
            writes=("staging",),
            previous_run=("staging", "source_records"),
            network=source,
        )
        for source in ALL_SOURCES
    ),
    _task(
        "fetch_truncated.refetch_openalex",
        "fetch_truncated",
        reads=("staging",),
        writes=("staging",),
        previous_run=("staging",),
        network="openalex",
    ),
    *(
        _task(
            f"normalize.{source}",
            "normalize",
            reads=(
                "staging",
                "source_records.id",
                "source_records.authors_hash",
                "source_records.publication_id",
                "source_contributions.id",
                "source_contributions.author_position",
                "source_contributions.roles",
                "source_contributions.contributor_information_id",
                "source_contributions.content_hash",
                "contributor_information",
                "addresses.id",
                "countries",
                # Groupes des contributions sources dont les rôles ou le statut de correspondant changent.
                "source_contribution_group_members",
                *_containers(source),
            ),
            writes=(
                "staging.processed",
                "staging.raw_data",
                "source_records",
                "source_contributions",
                "source_contribution_addresses",
                "source_contribution_rors",
                "source_contribution_hal_structures",
                "contributor_information",
                "addresses.id",
                "address_candidates_queue",
                "address_country_candidates",
                "publication_contributions_queue",
                "source_contribution_countries_queue",
                "source_record_keys_queue",
                "source_contribution_group_attributes_queue",
                *_containers(source),
            ),
            # Ses propres lignes de `staging`, enregistrements sources et contributions sources, les référentiels que trouvent ou créent toutes les sources et que `publishers_journals` fusionne et supprime, et les groupes écrits par `author_grouping`.
            previous_run=(
                "staging",
                "source_records",
                "source_contributions",
                "contributor_information",
                "addresses",
                "source_contribution_group_members",
                *_containers(source),
            ),
        )
        for source in SOURCE_PRIORITY
    ),
    _task(
        "normalize.prune_disappeared",
        "normalize",
        reads=(
            "staging.disappeared_at",
            "source_records.id",
            "source_records.staging_id",
            "source_records.publication_id",
        ),
        # La suppression d'un enregistrement source emporte ses contributions sources, leurs adresses, ROR et structures HAL, et les décisions qui les visent.
        writes=(
            "source_records.id",
            "source_record_keys_queue",
            "publication_contributions_queue",
            "source_contributions.id",
            "source_contribution_addresses",
            "source_contribution_rors",
            "source_contribution_hal_structures",
            "confirmed_source_contributions",
            "rejected_contributions",
        ),
        previous_run=("source_records",),
    ),
    _task(
        "normalize.cleanup_orphan_contributor_information",
        "normalize",
        reads=("source_contributions.contributor_information_id", "contributor_information.id"),
        writes=("contributor_information.id",),
        previous_run=("source_contributions",),
    ),
    _task(
        "normalize.cleanup_orphan_addresses",
        "normalize",
        reads=("source_contribution_addresses", "addresses.id"),
        # La suppression d'une adresse emporte ses liens aux structures.
        writes=("addresses.id", "address_structures"),
        # La normalisation vide `staging.raw_data`. `VACUUM FULL` en mode full.
        maintenance=("VACUUM staging",),
    ),
    _task(
        "affiliations.refresh_ror",
        "affiliations",
        reads=("ror_dump_imports", "source_contribution_rors"),
        writes=(
            "ror_organizations",
            "ror_relations",
            "ror_dump_imports",
            # Dépendants d'une organisation qui change de pays.
            "source_contribution_countries_queue",
            "address_country_candidates",
            "address_candidates_queue",
        ),
        previous_run=("ror_dump_imports",),
        network="zenodo",
    ),
    _task(
        "affiliations.refresh_hal_structures",
        "affiliations",
        reads=("source_contribution_hal_structures",),
        writes=(
            "hal_structures",
            "hal_structure_relations",
            "hal_structure_aliases",
            # Contributions sources d'une structure qui change de pays.
            "source_contribution_countries_queue",
        ),
        previous_run=("hal_structures", "hal_structure_aliases"),
        network="hal",
    ),
    _task(
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
    _task(
        "affiliations.resolve_thesis_partners",
        "affiliations",
        reads=(
            "structure_name_forms",
            "structures",
            "source_records.source_extras",
            "idref_structures",
        ),
        writes=("idref_structures",),
        previous_run=("idref_structures",),
    ),
    _task(
        "affiliations.populate",
        "affiliations",
        reads=(
            "address_structures",
            "perimeter_structures",
            "config",
            "source_contribution_addresses",
            # Branches ROR, structure HAL et thèse de `source_contribution_structures`.
            "source_contribution_rors",
            "source_contribution_hal_structures",
            "hal_structures",
            "hal_structure_relations",
            "hal_structure_aliases",
            "structures.ror_id",
            "structures.api_ids",
            "source_records.source_extras",
            "source_contributions.roles",
            "idref_structures",
            "source_contributions.source_record_id",
            "source_records.publication_id",
            # Identifiants des personnes qui ont une fiche RH : `hr_record_source_contributions`.
            "hr_records",
            "person_identifiers",
            "rejected_contributions",
            "contributor_information",
            "source_contributions.contributor_information_id",
            "source_contributions.neutralized_identifiers",
            "source_contributions.source",
            "source_records.publication_year",
            # Groupes des contributions sources dont les indices changent, marqués pour la recomposition de leurs attributs.
            "source_contribution_group_members",
        ),
        writes=(
            "source_contribution_structures",
            "source_contributions.in_perimeter",
            "source_record_keys_queue",
            "source_contribution_group_attributes_queue",
        ),
        previous_run=(
            "source_records.publication_id",
            "person_identifiers",
            "source_contributions.neutralized_identifiers",
            "source_contribution_group_members",
        ),
    ),
    _task(
        "resolve_ra.resolve_prefixes",
        "resolve_ra",
        reads=(
            "doi_prefixes.id",
            "source_records.doi",
            "source_records.external_ids",
            "publication_relations",
        ),
        writes=("doi_prefixes.id", "doi_prefixes.ra"),
        previous_run=("source_records", "publication_relations"),
        network="doi.org",
    ),
    _task(
        "publishers_journals.resolve_crossref_publishers",
        "publishers_journals",
        reads=(
            "doi_prefixes.id",
            "doi_prefixes.ra",
            "doi_prefixes.publisher_id",
            "doi_prefixes.publisher_name_normalized",
            "doi_prefixes.crossref_checked_at",
            "source_records.doi",
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
            "source_records.doi",
            "publishers",
            "publisher_name_forms",
            "doi_prefixes",
        ),
        network="crossref",
    ),
    _task(
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
    _task(
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
    _task(
        "publishers_journals.check_journals_in_sudoc",
        "publishers_journals",
        reads=(
            "journals.id",
            "journals.title",
            "journals.journal_type",
            "journals.manual_fields",
            "journal_issns",
            "source_records.biblio",
            "source_records.journal_id",
        ),
        writes=(
            "journal_issns",
            "journals.title",
            "journals.title_normalized",
            "journal_name_forms",
        ),
        previous_run=("journals", "journal_issns", "source_records.journal_id"),
        network="sudoc",
    ),
    _task(
        "publishers_journals.merge_duplicate_journals",
        "publishers_journals",
        reads=(
            "journal_issns",
            "journals.id",
            "journals.title",
            "journals.title_normalized",
            "journals.publication_count",
            "journals.journal_type",
            "journals.oa_model",
            "journals.apc_amount",
            "journals.apc_currency",
            "journals.manual_fields",
            "source_records.journal_id",
            "source_records.publication_year",
            "source_records.doi",
            "source_records.publication_id",
            # Verdicts d'Unpaywall, lus par le recalcul des publications des revues fusionnées.
            "unpaywall",
        ),
        writes=(
            "journals",
            "journal_issns",
            "journal_name_forms",
            "journal_doi_namespaces",
            "monographs.journal_id",
            "apc_payments.journal_id",
            "source_records.journal_id",
            "source_records.doc_type",
            "source_records.oa_status",
            "source_records.language",
            "source_records.external_ids",
            "source_records.corrections",
            "publications",
            "publications_detail",
            "publishers.publication_count",
        ),
        previous_run=(
            "journals",
            "journal_issns",
            "source_records.publication_id",
            "source_records.journal_id",
            "source_records.doi",
            "unpaywall",
        ),
    ),
    _task(
        "publishers_journals.type_proceedings_journals",
        "publishers_journals",
        reads=(
            "journals.id",
            "journals.title",
            "journals.journal_type",
            "journals.manual_fields",
            "journal_issns",
            "source_records.corrections",
            "source_records.doc_type",
            "source_records.journal_id",
        ),
        writes=("journals.journal_type",),
        previous_run=(
            "journals",
            "journal_issns",
            # Type brut de la source (`raw_column`) : la correction ne le change pas.
            "source_records.corrections",
            "source_records.doc_type",
            "source_records.journal_id",
        ),
    ),
    _task(
        "publishers_journals.learn_journal_doi_namespaces",
        "publishers_journals",
        reads=(
            "source_records.doi",
            "source_records.journal_id",
            "source_records.corrections",
            "journals.journal_type",
        ),
        writes=("journal_doi_namespaces",),
        previous_run=("source_records", "journals"),
    ),
    _task(
        "publishers_journals.enrich_journals_from_doaj",
        "publishers_journals",
        reads=("journal_issns", "journals.doaj_imported_at", "config"),
        writes=("journals.is_in_doaj", "journals.doaj_payload", "journals.doaj_imported_at"),
        previous_run=("journal_issns", "journals"),
        network="doaj",
    ),
    _task(
        "publishers_journals.merge_duplicate_monographs",
        "publishers_journals",
        reads=("monographs.id", "monographs.title_normalized"),
        writes=("monographs.id", "source_records.monograph_id", "publications.monograph_id"),
        previous_run=("monographs",),
    ),
    _task(
        "publishers_journals.link_monographs_to_collections",
        "publishers_journals",
        reads=(
            "monographs",
            "source_records.monograph_id",
            "source_records.journal_id",
            "journal_issns",
        ),
        writes=(
            "journals.id",
            "journals.journal_type",
            "journal_name_forms",
            "monographs.journal_id",
        ),
        previous_run=("monographs", "source_records.journal_id", "journal_issns"),
    ),
    _task(
        "publishers_journals.type_proceedings_volumes",
        "publishers_journals",
        reads=(
            "monographs.id",
            "monographs.journal_id",
            "journals.journal_type",
            "source_records.corrections",
            "source_records.doc_type",
        ),
        writes=("monographs.proceedings",),
        previous_run=(
            "monographs",
            "journals",
            # Type brut de la source (`raw_column`) : la correction ne le change pas.
            "source_records.corrections",
            "source_records.doc_type",
        ),
    ),
    _task(
        "metadata_correction.journal_by_doi",
        "metadata_correction",
        reads=(
            "journal_doi_namespaces",
            "source_records.doi",
            "source_records.journal_id",
            "source_records.corrections",
            "source_records.doc_type",
        ),
        writes=(
            "source_records.journal_id",
            "source_records.corrections",
            "source_record_keys_queue",
        ),
        previous_run=("source_records",),
    ),
    _task(
        "metadata_correction.unary",
        "metadata_correction",
        reads=(
            *(
                f"source_records.{column}"
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
                    "corrections",
                    "embargo_until",
                    "source_extras",
                )
            ),
            "journals.journal_type",
            "journals.oa_model",
            "journals.is_in_doaj",
            "journals.doaj_payload",
            "monographs.proceedings",
            "doi_prefixes.publisher_id",
            "publishers.publisher_type",
            "language_forms",
            "source_contributions.source_record_id",
        ),
        writes=(
            "source_records.doc_type",
            "source_records.oa_status",
            "source_records.language",
            "source_records.external_ids",
            "source_records.corrections",
            "source_record_keys_queue",
        ),
        # Les référentiels vides, supprimés plus loin, ne sont référencés par aucun enregistrement source : la correction ne les atteint pas.
        previous_run=(
            "source_records",
            "journals.journal_type",
            "journals.oa_model",
            "journals.is_in_doaj",
            "journals.doaj_payload",
            "monographs.proceedings",
            "publishers.publisher_type",
        ),
    ),
    _task(
        "metadata_correction.cluster",
        "metadata_correction",
        reads=tuple(
            f"source_records.{column}"
            for column in (
                "id",
                "source",
                "doc_type",
                "doi",
                "title_normalized",
                "corrections",
                "source_extras",
                "external_ids",
                "source_id",
                "publication_id",
            )
        )
        # DOI que doi.org ne connaît pas.
        + ("failed_lookups",)
        # Noms des auteurs d'un dépôt HAL et de l'enregistrement source Crossref de son DOI.
        + (
            "source_contributions.source_record_id",
            "source_contributions.contributor_information_id",
            "source_contributions.collective",
            "contributor_information",
        ),
        writes=(
            "source_records.doi",
            "source_records.external_ids",
            "source_records.corrections",
            "source_record_keys_queue",
            "publication_contributions_queue",
        ),
        previous_run=("source_records",),
    ),
    _task(
        "publications.reconcile",
        "publications",
        reads=(
            "source_records",
            "source_record_keys_queue",
            "source_contributions.in_perimeter",
            "publications",
            "apc_payments",
            "journals.journal_type",
            "monographs.journal_id",
            "unpaywall",
        ),
        writes=(
            "publications",
            "publications_detail",
            "source_records.publication_id",
            "source_record_keys_queue",
            "apc_payments.publication_id",
            "publication_contributions_queue",
        ),
        # Verdicts d'Unpaywall ; publications que `contributions.purge_publications` supprime ; revues et monographies vides supprimées par `contributions.delete_empty_containers`.
        previous_run=(
            "source_records.countries",
            "publications.id",
            "publications.oa_status",
            "unpaywall",
            "journals",
            "monographs",
        ),
    ),
    _task(
        "author_grouping.build",
        "author_grouping",
        reads=(
            "publications.id",
            "publication_contributions_queue",
            "source_records.publication_id",
            "source_records.source_id",
            "source_records.corrections",
            "source_contributions.id",
            "source_contributions.source_record_id",
            "source_contributions.author_position",
            "source_contributions.collective",
            "source_contributions.contributor_information_id",
            "source_contributions.neutralized_identifiers",
            "contributor_information",
            # Prénom de la personne à laquelle un humain a rattaché l'identifiant d'une contribution source.
            "person_identifiers",
            "persons",
            "source_contribution_groups",
            "source_contribution_group_members",
        ),
        writes=(
            "source_contribution_groups.id",
            "source_contribution_groups.reference_position",
            # Un groupe dont les membres changent perd sa personne.
            "source_contribution_groups.person_id",
            "source_contribution_groups.resolution_mode",
            "source_contribution_group_members.id",
            "source_contributions.duplicate_of",
            "publication_contributions_queue",
            "source_contribution_group_attributes_queue",
            "publication_author_alignment",
        ),
        # Publications que `contributions.purge_publications` supprime plus loin dans le même run ; marquages que la tâche retire elle-même ; personnes, identifiants, neutralisations et personnes des groupes qu'écrit la phase `persons`.
        previous_run=(
            "publications.id",
            "publication_contributions_queue",
            "person_identifiers",
            "persons",
            "source_contributions.neutralized_identifiers",
            "source_contribution_groups.person_id",
            "source_contribution_groups.resolution_mode",
        ),
    ),
    _task(
        "author_grouping.attributes",
        "author_grouping",
        reads=(
            "source_contribution_group_attributes_queue",
            "source_contribution_group_members",
            "source_contributions.is_corresponding",
            "source_contributions.perimeter_evidence",
            "source_contributions.roles",
            "source_contribution_groups.id",
            "source_contribution_groups.is_corresponding",
            "source_contribution_groups.perimeter_evidence",
            "source_contribution_groups.roles",
        ),
        writes=(
            "source_contribution_groups.is_corresponding",
            "source_contribution_groups.perimeter_evidence",
            "source_contribution_groups.roles",
            "source_contribution_group_attributes_queue",
        ),
    ),
    _task(
        "persons.resolve",
        "persons",
        reads=(
            "confirmed_source_contributions",
            "contributor_information",
            "source_contributions.person_id",
            "source_contributions.resolution_mode",
            "source_contributions.neutralized_identifiers",
            "source_contributions.contributor_information_id",
            "source_contributions.in_perimeter",
            "source_contributions.source_record_id",
            "source_records.publication_id",
            "source_contribution_group_members",
            "person_identifiers",
            "person_name_forms",
            "persons",
            "rejected_contributions",
        ),
        writes=(
            "source_contributions.person_id",
            "source_contributions.resolution_mode",
            "source_contributions.neutralized_identifiers",
            # Publications dont une contribution source change de neutralisation : leurs groupes sont à recalculer.
            "publication_contributions_queue",
            "persons",
            "person_identifiers",
            "person_name_forms",
        ),
        # Formes de nom peuplées, contributions sources détachées et personnes supprimées par `populate_person_name_forms` et `purge`.
        previous_run=(
            "person_name_forms",
            "persons",
            "person_identifiers",
            "source_contributions.person_id",
            "source_contributions.resolution_mode",
        ),
    ),
    _task(
        "persons.populate_person_name_forms",
        "persons",
        reads=(
            "persons",
            "source_contributions.person_id",
            "source_contributions.contributor_information_id",
            "contributor_information",
            "person_name_forms",
        ),
        writes=("person_name_forms",),
        # Contributions sources détachées et personnes supprimées par `purge`.
        previous_run=("persons", "person_name_forms", "source_contributions.person_id"),
    ),
    _task(
        "persons.purge",
        "persons",
        reads=(
            "source_contributions.person_id",
            "source_contributions.resolution_mode",
            "source_contributions.contributor_information_id",
            "source_contributions.source_record_id",
            "source_contributions.neutralized_identifiers",
            "source_records.publication_id",
            "contributor_information",
            "person_name_forms",
            "person_identifiers",
            "persons",
            "hr_records",
            "confirmed_source_contributions",
            "rejected_contributions",
            "distinct_persons",
        ),
        # La suppression d'une personne emporte ses formes de nom et vide ses groupes.
        writes=(
            "source_contributions.person_id",
            "source_contributions.resolution_mode",
            "source_contribution_groups.person_id",
            "source_contribution_groups.resolution_mode",
            "person_identifiers.id",
            "persons.id",
            "person_name_forms.id",
        ),
        # `normalize` et `persons` réécrivent en masse `source_contributions.person_id`.
        maintenance=("ANALYZE source_contributions",),
    ),
    _task(
        "persons.resolve_groups",
        "persons",
        reads=(
            "source_contribution_groups.id",
            "source_contribution_groups.publication_id",
            "source_contribution_groups.person_id",
            "source_contribution_group_members",
            "source_contributions.in_perimeter",
            "source_contributions.contributor_information_id",
            "source_contributions.neutralized_identifiers",
            "source_contributions.roles",
            "source_records.publication_id",
            "contributor_information",
            "confirmed_source_contributions",
            "rejected_contributions",
            "person_identifiers",
            "person_name_forms",
            "persons",
        ),
        writes=(
            "source_contribution_groups.person_id",
            "source_contribution_groups.resolution_mode",
        ),
    ),
    _task(
        "contributions.build",
        "contributions",
        reads=(
            "source_contributions.person_id",
            "source_contributions.source_record_id",
            "source_records.publication_id",
            "publications.id",
            "rejected_contributions",
            "confirmed_source_contributions",
            "contributions.id",
        ),
        writes=("contributions.id",),
        # Lignes que `contributions.purge_publications` supprime plus loin dans le même run.
        previous_run=("publications.id",),
        # Le planificateur estime la propagation des attributs sur les liens qui viennent d'être créés.
        maintenance=("ANALYZE contributions",),
    ),
    _task(
        "contributions.propagate",
        "contributions",
        reads=(
            "source_contributions.person_id",
            "source_contributions.source_record_id",
            "source_contributions.author_position",
            "source_contributions.is_corresponding",
            "source_contributions.roles",
            "source_contributions.in_perimeter",
            "source_records.publication_id",
            "contributions",
        ),
        writes=(
            "contributions.author_position",
            "contributions.is_corresponding",
            "contributions.in_perimeter",
            "contributions.roles",
        ),
    ),
    _task(
        "contributions.publications_in_perimeter",
        "contributions",
        reads=(
            "source_contribution_groups.person_id",
            "source_contribution_groups.perimeter_evidence",
            "source_contribution_groups.roles",
            "persons.exclusion",
            "publications.id",
        ),
        writes=("publications.in_perimeter",),
        # Lignes que `contributions.purge_publications` supprime plus loin dans le même run.
        previous_run=("publications.id",),
    ),
    _task(
        "contributions.structures",
        "contributions",
        reads=(
            "contributions",
            "source_contributions.person_id",
            "source_contributions.source_record_id",
            "source_records.publication_id",
            "source_contribution_structures",
            "source_contribution_groups.person_id",
            "source_contribution_groups.roles",
            "source_contribution_group_members",
            "persons.exclusion",
        ),
        writes=("group_structures", "publication_structures"),
    ),
    _task(
        "contributions.purge_publications",
        "contributions",
        reads=("publications.id", "source_records.publication_id", "contributions"),
        writes=("publications.id",),
    ),
    _task(
        "contributions.delete_empty_containers",
        "contributions",
        reads=(
            "monographs.id",
            "monographs.journal_id",
            "journals.id",
            "publishers.id",
            "source_records.journal_id",
            "source_records.monograph_id",
            "publications.journal_id",
            "publications.monograph_id",
            "apc_payments",
            "doi_prefixes.publisher_id",
            "journal_name_forms",
        ),
        writes=("monographs.id", "journals.id", "publishers.id", "journal_issns"),
    ),
    _task(
        "contributions.publication_counts",
        "contributions",
        reads=(
            "addresses.id",
            "source_contribution_addresses",
            "source_contributions.source_record_id",
            "source_records.publication_id",
            "source_records.journal_id",
            "journals.id",
            "journals.publisher_id",
            "publishers.id",
            "publications.id",
            "publications.in_perimeter",
            "publications.journal_id",
        ),
        writes=(
            "addresses.publication_count",
            "journals.publication_count",
            "publishers.publication_count",
        ),
        previous_run=("addresses",),
    ),
    _task(
        "relations.rebuild",
        "relations",
        reads=(
            *(
                f"source_records.{column}"
                for column in (
                    "source_extras",
                    "corrections",
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
            "publications.publication_year",
            "publication_relations",
        ),
        writes=("publication_relations",),
        # Lecture de la table avant sa reconstruction, pour compter les arêtes ajoutées et disparues.
        previous_run=("publication_relations",),
    ),
    _task(
        "subjects.ingest",
        "subjects",
        reads=(
            "publications.id",
            "publications.subjects_ingested_at",
            "source_records.topics",
            "subjects",
            "publication_subjects",
        ),
        writes=("publication_subjects", "subjects.id", "publications.subjects_ingested_at"),
        previous_run=("publications.subjects_ingested_at", "subjects"),
    ),
    _task(
        "subjects.usage",
        "subjects",
        reads=(
            "publication_subjects",
            "subjects.id",
        ),
        writes=("subjects.usage_count", "subject_cooccurrences"),
        previous_run=("subjects",),
    ),
    _task(
        "countries.ror",
        "countries",
        reads=("source_contribution_rors", "ror_organizations", "countries", "addresses.id"),
        writes=("address_country_candidates", "address_candidates_queue"),
    ),
    _task(
        "countries.detect",
        "countries",
        reads=(
            "place_name_forms",
            "countries",
            "addresses.id",
            "addresses.normalized_text",
            "address_candidates_queue",
        ),
        writes=("address_country_candidates",),
        # Adresses marquées depuis la dernière résolution, que `countries.resolve` retire de la file.
        previous_run=("address_candidates_queue",),
    ),
    _task(
        "countries.resolve",
        "countries",
        reads=(
            "address_country_candidates",
            "addresses.id",
            "addresses.countries",
            "address_candidates_queue",
        ),
        writes=(
            "addresses.countries",
            "address_countries_queue",
            "address_candidates_queue",
        ),
    ),
    _task(
        "countries.refresh_publication_countries",
        "countries",
        reads=(
            "source_contribution_countries_queue",
            "source_contributions.source_record_id",
            "source_contributions.countries",
            "source_contribution_addresses",
            "source_contribution_rors",
            "source_contribution_hal_structures",
            "ror_organizations",
            "hal_structures",
            "hal_structure_aliases",
            "addresses.countries",
            "address_countries_queue",
            "source_records.publication_id",
            "source_records.countries",
            "publications.id",
        ),
        writes=(
            "source_contributions.countries",
            "source_records.countries",
            "publications.countries",
            "source_contribution_countries_queue",
            "address_countries_queue",
        ),
    ),
    _task(
        "oa_status.verify_unpaywall",
        "oa_status",
        reads=(
            "publications.id",
            "publications.doi",
            "publications.oa_status",
            "unpaywall",
            "source_records.publication_id",
            "source_records.source",
            "source_records.oa_status",
            "config",
        ),
        writes=("publications.oa_status", "unpaywall"),
        network="unpaywall",
    ),
)


# ── Phases ────────────────────────────────────────────────────

_RUN_PHASE = "run"
"""Groupe des tâches que l'orchestrateur exécute avant toute phase."""

PHASE_ORDER: tuple[str, ...] = tuple(
    dict.fromkeys(task.phase for task in TASKS if task.phase != _RUN_PHASE)
)
"""Ordre d'exécution des phases : celui de leurs tâches dans `TASKS`."""

PHASE_LABELS: dict[str, str] = {
    "harvest": "Moissonnage par affiliation",
    "harvest_by_person": "Moissonnage par personne",
    "resolve_ra": "Résolution des agences d'enregistrement des DOI",
    "fetch_missing": "Recherche dans chaque source des documents trouvés dans les autres",
    "fetch_stale": "Recherche des documents non revus depuis {delai}",
    "fetch_truncated": "Re-téléchargement des documents OpenAlex tronqués à 100 auteurs",
    "normalize": "Normalisation des données brutes",
    "affiliations": "Résolution des affiliations par contribution source",
    "publishers_journals": "Enrichissement des référentiels d'éditeurs et revues",
    "metadata_correction": "Correction des métadonnées de publication",
    "publications": "Dédoublonnage des publications",
    "author_grouping": "Alignement des auteurs des enregistrements sources d'une même publication",
    "persons": "Résolution des personnes",
    "contributions": "Rafraîchissement des liens entre publications, personnes et structures",
    "relations": "Relations entre publications apparentées",
    "subjects": "Sujets des publications",
    "countries": "Pays associés aux contributions sources",
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

if set(PHASE_LABELS) != set(PHASE_ORDER):
    raise ValueError("PHASE_LIBELLES et le graphe ne nomment pas les mêmes phases")
