"""Phase `publishing` : référentiels des éditeurs, des revues et des monographies, en étapes (`STEPS`) et tâches du graphe (`pipeline.graph`).

Contraintes d'ordre :

- Le rattachement des enregistrements sources aux éditeurs suit la résolution des préfixes, qui crée des éditeurs avec leurs formes de nom.
- La fusion des autres noms des éditeurs suit la résolution des préfixes, qui pose leurs titulaires, et le rattachement des enregistrements sources aux éditeurs.
- Les ISSN des séries précèdent leur vérification Sudoc et l'import de la table ISSN-L, qui précèdent le rattachement des enregistrements sources aux revues : le rattachement lit l'ISSN-L et le titre Sudoc de chaque ISSN.
- La recherche des métadonnées des revues dans OpenAlex suit le rattachement, qui donne à chaque revue ses ISSN et ses enregistrements sources. Elle précède le typage en recueil d'actes, qui vise aussi les revues `unknown`.
- Les espaces de noms DOI suivent le rattachement et le typage des revues.
- Le rattachement des enregistrements sources aux monographies suit la fusion des autres noms des éditeurs : l'éditeur départage les volumes de même titre.
- Le rattachement des monographies à leur collection suit le rattachement des enregistrements sources. La nature des monographies lit le type de la collection posé par le rattachement.

`import_issnl_table` importe la table ISSN-L de l'ISSN International Centre, qui fait autorité sur `serial_issns.issnl`, quand le dernier import date de plus de `issnl_table_refresh_after_days` jours. `enrich_serials_from_doaj` importe le dump CSV du DOAJ, qui donne la fiche DOAJ des revues (`doaj_payload`), quand le dernier import date de plus de `doaj_refresh_after_days` jours. L'enrichissement des éditeurs (pays, ROR, type) se lance à la demande, par `interfaces/cli/maintenance/enrich_publishers.py`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from functools import partial

from domain.config import ConfigKey
from infrastructure.repositories.publisher_merge import merge_publisher_into
from pipeline.graph import Step, Task, TaskRun, in_transaction
from pipeline.http.polite_pool import default_user_agent
from pipeline.ingestion.api_params import (
    API_BASE_URLS,
    MAX_CONCURRENT,
)
from pipeline.ingestion.complements.doaj import downloaded_doaj_dump
from pipeline.ingestion.complements.issn_centre import downloaded_issnl_table
from pipeline.ingestion.complements.sudoc import fetch_ppns, fetch_serial_record
from pipeline.ingestion.crossref.prefixes import fetch_crossref_prefix
from pipeline.ingestion.datacite.prefixes import fetch_datacite_prefix
from pipeline.ingestion.openalex.sources import fetch_source_lists, fetch_sources
from pipeline.runtime.config import cap, delay
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publishing.doi_prefixes import DoiPrefixStore
from pipeline.transformation.publishing.monographs import (
    attach_monographs,
    link_monographs_to_collections,
    type_proceedings_volumes,
)
from pipeline.transformation.publishing.publishers import (
    attach_publishers,
    merge_duplicate_publishers,
    resolve_publishers,
)
from pipeline.transformation.publishing.publishers.store import PublisherStore
from pipeline.transformation.publishing.serials import (
    attach_serials,
    check_issns_in_sudoc,
    check_serials_in_openalex,
    enrich_serials_from_doaj,
    import_issnl_table,
    learn_serial_doi_namespaces,
    type_journal_serials,
    type_proceedings_serials,
)

_IDENTIFIED: dict[str, Callable[[PhaseMetrics], int]] = {
    "resolve_crossref_publishers": lambda m: m.extras.get("publisher_matched", 0),
    "resolve_datacite_publishers": lambda m: m.extras.get("publisher_matched", 0),
    "attach_publishers": lambda m: m.updated,
    "merge_duplicate_publishers": lambda m: m.extras.get("publishers_merged", 0),
    "sync_issns": lambda m: m.new,
    "check_issns_in_sudoc": lambda m: m.extras.get("sudoc_found", 0),
    "import_issnl_table": lambda m: m.extras.get("matched", 0),
    "attach_serials": lambda m: m.updated,
    "check_serials_in_openalex": lambda m: m.extras.get("openalex_found", 0),
    "type_proceedings_serials": lambda m: m.extras.get("serials_typed_proceedings", 0),
    "type_journal_serials": lambda m: m.extras.get("serials_typed_journal", 0),
    "learn_serial_doi_namespaces": lambda m: m.extras.get("serial_doi_namespaces", 0),
    "attach_monographs": lambda m: m.updated,
    "link_monographs_to_collections": lambda m: m.extras.get("monographs_linked", 0),
    "type_proceedings_volumes": lambda m: m.extras.get("monographs_to_proceedings", 0),
}
"""Tâches de la table d'observabilité, dans l'ordre d'exécution, avec ce qui compte comme identifié pour chacune."""


def assemble(by_task: Mapping[str, PhaseMetrics]) -> PhaseMetrics:
    """Renvoie les métriques de la phase : celles des tâches, dans l'ordre de leur exécution, et la table d'observabilité."""
    metrics = PhaseMetrics()
    # Les compteurs et signaux des sous-étapes remontent à la phase : une source coupée la fait passer en avertissement.
    for sub in by_task.values():
        metrics.merge(sub)

    metrics.details["table"] = {
        "rows": [
            {
                "key": name,
                "traités": by_task[name].total,
                "identifiés": identified(by_task[name]),
                "créés": by_task[name].extras.get("publisher_created", 0),
            }
            for name, identified in _IDENTIFIED.items()
        ]
    }
    # DOAJ : ligne à part (sous-étape conditionnelle, métrique propre).
    metrics.details["summary"] = {
        "doaj_matched": by_task["enrich_serials_from_doaj"].extras.get("matched", 0)
    }
    return metrics


def _resolve_publishers(run: Callable[..., PhaseMetrics]) -> TaskRun:
    """Renvoie l'exécution d'une résolution des éditeurs par préfixe DOI, sur les stores des préfixes et des éditeurs."""

    def execute(ctx: PhaseContext) -> PhaseMetrics:
        with ctx.open_tx() as conn:
            return run(
                conn,
                ctx.logger,
                prefix_store=DoiPrefixStore(conn),
                publisher_store=PublisherStore(conn),
            )

    return execute


def _run_merge_duplicate_publishers(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:

        def merge(target_id: int, source_id: int) -> None:
            merge_publisher_into(conn, target_id, source_id)
            conn.commit()

        return merge_duplicate_publishers.run_merge_duplicate_publishers(
            conn, ctx.logger, merge=merge
        )


def _run_check_serials_in_openalex(ctx: PhaseContext) -> PhaseMetrics:
    sources_api = API_BASE_URLS["openalex_sources"]
    source_lists_api = API_BASE_URLS["openalex_source_lists"]
    with ctx.open_tx() as conn:
        return check_serials_in_openalex.run_check_serials_in_openalex(
            conn,
            ctx.logger,
            fetch_sources=lambda key, values: fetch_sources(key, values, sources_api=sources_api),
            fetch_source_lists=lambda: fetch_source_lists(source_lists_api=source_lists_api),
            recheck_after_days=delay(conn, ConfigKey.SERIAL_OPENALEX_RECHECK_AFTER_DAYS),
        )


def _run_check_issns_in_sudoc(
    ctx: PhaseContext,
) -> PhaseMetrics:
    base_url = API_BASE_URLS["sudoc"]
    with ctx.open_tx() as conn:
        # `asyncio.run` transmet aux coroutines la ContextVar du circuit-breaker.
        return asyncio.run(
            check_issns_in_sudoc.run_check_issns_in_sudoc(
                conn,
                ctx.logger,
                fetch_ppns=lambda client, issns: fetch_ppns(client, issns, base_url=base_url),
                fetch_record=lambda client, ppn: fetch_serial_record(
                    client, ppn, base_url=base_url
                ),
                max_concurrent=MAX_CONCURRENT["sudoc"],
                max_per_run=cap(conn, ConfigKey.SUDOC_MAX_PER_RUN),
            )
        )


def _run_import_issnl_table(ctx: PhaseContext) -> PhaseMetrics:
    user_agent = default_user_agent()
    with ctx.open_tx() as conn:
        return import_issnl_table.run_import_issnl_table(
            conn,
            ctx.logger,
            refresh_after_days=delay(conn, ConfigKey.ISSNL_TABLE_REFRESH_AFTER_DAYS),
            download_table=lambda: downloaded_issnl_table(user_agent=user_agent, logger=ctx.logger),
        )


def _run_enrich_serials_from_doaj(ctx: PhaseContext) -> PhaseMetrics:
    user_agent = default_user_agent()
    with ctx.open_tx() as conn:
        return enrich_serials_from_doaj.run_enrich_serials_from_doaj(
            conn,
            ctx.logger,
            refresh_after_days=delay(conn, ConfigKey.DOAJ_REFRESH_AFTER_DAYS),
            download_dump=lambda: downloaded_doaj_dump(user_agent=user_agent, logger=ctx.logger),
        )


_RESOLVE_CROSSREF_PUBLISHERS = Task(
    "resolve_crossref_publishers",
    reads=(
        "doi_prefixes.id",
        "doi_prefixes.ra",
        "doi_prefixes.publisher_id",
        "doi_prefixes.publisher_name_normalized",
        "doi_prefixes.crossref_checked_at",
        "source_record_identifiers",
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
    # L'agence et l'éditeur posés par `resolve_datacite_publishers` retirent un préfixe de la sélection.
    previous_run=(
        "source_record_identifiers",
        "publishers",
        "publisher_name_forms",
        "doi_prefixes",
    ),
    network="crossref",
    run=_resolve_publishers(
        partial(
            resolve_publishers.run_resolve_crossref_publishers,
            fetch_prefix_fn=fetch_crossref_prefix,
        )
    ),
    label=resolve_publishers.LABELS["Crossref"],
)


_RESOLVE_DATACITE_PUBLISHERS = Task(
    "resolve_datacite_publishers",
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
    run=_resolve_publishers(
        partial(
            resolve_publishers.run_resolve_datacite_publishers,
            fetch_prefix_fn=fetch_datacite_prefix,
        )
    ),
    label=resolve_publishers.LABELS["DataCite"],
)


_ATTACH_PUBLISHERS = Task(
    "attach_publishers",
    reads=(
        "source_records.source",
        "source_records.doc_type",
        "source_records.corrections",
        "source_records.biblio",
        "source_records.publisher_id",
        "publishers.openalex_id",
        "publisher_name_forms",
    ),
    writes=(
        "publishers.id",
        "publishers.openalex_id",
        "publisher_name_forms",
        "source_records.publisher_id",
        "source_record_keys_queue",
    ),
    # Éditeurs et formes de nom des runs précédents ; types corrigés par `metadata_correction`, lus sous leur valeur d'avant correction.
    previous_run=(
        "publishers",
        "publisher_name_forms",
        "source_records.publisher_id",
        "source_records.corrections",
        "source_records.doc_type",
    ),
    run=in_transaction(attach_publishers.run_attach_publishers),
    label=attach_publishers.LABEL,
)


_MERGE_DUPLICATE_PUBLISHERS = Task(
    "merge_duplicate_publishers",
    reads=(
        "source_records.publisher_id",
        "source_records.publication_id",
        "publications.doi_prefix",
        "doi_prefixes.publisher_id",
        "publishers.id",
        "publishers.name",
    ),
    writes=(
        "publishers.id",
        "source_records.publisher_id",
        "publications.publisher_id",
        "serials.publisher_id",
        "monographs.publisher_id",
        "apc_payments.publisher_id",
        "publisher_name_forms",
        "merge_redirects",
    ),
    # Un autre nom ne détient aucun préfixe DOI : la fusion laisse `doi_prefixes` en l'état.
    previous_run=("source_records", "publications", "publishers"),
    run=_run_merge_duplicate_publishers,
    label=merge_duplicate_publishers.LABEL,
)


_SYNC_ISSNS = Task(
    "sync_issns",
    reads=("source_records.biblio", "serial_issns"),
    writes=("serial_issns",),
    # Lignes vérifiées par `check_issns_in_sudoc`, revues posées par `attach_serials`, revues supprimées par `finalize.delete_empty_serials`.
    previous_run=("serial_issns",),
    run=in_transaction(attach_serials.run_sync_issns),
    label=attach_serials.SYNC_LABEL,
)


_CHECK_ISSNS_IN_SUDOC = Task(
    "check_issns_in_sudoc",
    reads=(
        "serial_issns",
        "serials.id",
        "serials.title",
        "serials.manual_fields",
        "config",
    ),
    writes=(
        "serial_issns",
        "issn_links",
        "serials.id",
        "serials.title",
        "serials.title_normalized",
    ),
    previous_run=("serial_issns", "serials"),
    network="sudoc",
    run=_run_check_issns_in_sudoc,
    label=check_issns_in_sudoc.LABEL,
    threshold=3,
)


_IMPORT_ISSNL_TABLE = Task(
    "import_issnl_table",
    reads=("serial_issns", "config"),
    writes=("serial_issns.issnl", "serial_issns.issnl_checked_at"),
    # Date du dernier import, posée par la tâche elle-même.
    previous_run=("serial_issns",),
    network="issn",
    run=_run_import_issnl_table,
    label=import_issnl_table.LABEL,
)


_ATTACH_SERIALS = Task(
    "attach_serials",
    reads=(
        "source_records.source",
        "source_records.biblio",
        "source_records.serial_id",
        "source_records.publisher_id",
        "source_records.corrections",
        "serial_issns",
        # ISSN qui annule chaque ISSN annulé.
        "issn_links",
        "serials",
        "serial_title_decisions",
        "monographs.serial_id",
        # Nombre de publications et éditeur des revues qui en absorbent une autre.
        "publications.serial_id",
        "publications.publisher_id",
        "publications.publication_year",
        "publications.in_perimeter",
    ),
    writes=(
        "source_records.serial_id",
        "source_records.corrections",
        "source_record_keys_queue",
        "serial_issns",
        "serials",
        "publications.serial_id",
        "apc_payments.serial_id",
        "monographs.serial_id",
        "merge_redirects",
    ),
    # Revues corrigées par `metadata_correction`, collections posées par `link_monographs_to_collections`, publications recalculées par la phase `publications`, décisions de titre supprimées avec leur revue par `finalize.delete_empty_serials`.
    previous_run=(
        "source_records.serial_id",
        "source_records.corrections",
        "serial_issns",
        "serials",
        "monographs.serial_id",
        "publications",
        "serial_title_decisions",
    ),
    run=in_transaction(attach_serials.run_attach_serials),
    label=attach_serials.ATTACH_LABEL,
)


_CHECK_SERIALS_IN_OPENALEX = Task(
    "check_serials_in_openalex",
    reads=(
        "serials.id",
        "serials.openalex_id",
        "serials.openalex_checked_at",
        "serials.publication_count",
        "serials.serial_type",
        "serials.manual_fields",
        "serial_issns",
        "source_records.source",
        "source_records.biblio",
        "source_records.serial_id",
        "serial_lists",
        "config",
    ),
    writes=(
        "serials.openalex_id",
        "serials.openalex_checked_at",
        "serials.serial_type",
        "serial_list_entries",
        "serial_lists",
    ),
    # Nombre de publications recalculé par `finalize`, date de recherche posée par la tâche elle-même, revues corrigées par `metadata_correction`, ISSN libérés par `finalize.delete_empty_serials`.
    previous_run=("serials", "source_records.serial_id", "serial_issns"),
    network="openalex",
    run=_run_check_serials_in_openalex,
    label=check_serials_in_openalex.LABEL,
    # Trois lots consécutifs en 429 signalent l'épuisement du quota OpenAlex du jour. Le reste attend le run suivant.
    threshold=3,
)


_TYPE_PROCEEDINGS_SERIALS = Task(
    "type_proceedings_serials",
    reads=(
        "serials.id",
        "serials.title",
        "serials.serial_type",
        "serials.manual_fields",
        "serial_issns",
        "source_records.source",
        "source_records.raw_doc_type",
        "source_records.serial_id",
    ),
    writes=("serials.serial_type",),
    previous_run=("serials", "serial_issns", "source_records.serial_id"),
    run=in_transaction(type_proceedings_serials.run_type_proceedings_serials),
    label=type_proceedings_serials.LABEL,
)


_TYPE_JOURNAL_SERIALS = Task(
    "type_journal_serials",
    reads=(
        "serials.id",
        "serials.title",
        "serials.serial_type",
        "serials.manual_fields",
        "serial_issns",
        "source_records.source",
        "source_records.raw_doc_type",
        "source_records.serial_id",
    ),
    writes=("serials.serial_type",),
    previous_run=("serials", "serial_issns", "source_records.serial_id"),
    run=in_transaction(type_journal_serials.run_type_journal_serials),
    label=type_journal_serials.LABEL,
)


_LEARN_SERIAL_DOI_NAMESPACES = Task(
    "learn_serial_doi_namespaces",
    reads=(
        "source_record_identifiers",
        "source_records.serial_id",
        "source_records.corrections",
        "serials.serial_type",
    ),
    writes=("serial_doi_namespaces",),
    # Statuts posés par la correction de `metadata_correction`.
    previous_run=("source_records", "serials", "source_record_identifiers.removed_by"),
    run=in_transaction(learn_serial_doi_namespaces.run_learn_serial_doi_namespaces),
    label=learn_serial_doi_namespaces.LABEL,
)


_ENRICH_SERIALS_FROM_DOAJ = Task(
    "enrich_serials_from_doaj",
    reads=(
        "serial_issns",
        "serial_list_entries",
        "serials.doaj_imported_at",
        "serials.serial_type",
        "serials.oa_model",
        "serials.doaj_payload",
        "serials.manual_fields",
        "config",
    ),
    writes=(
        "serials.doaj_payload",
        "serials.doaj_imported_at",
        "serials.serial_type",
        "serials.oa_model",
    ),
    previous_run=("serial_issns", "serials"),
    network="doaj",
    run=_run_enrich_serials_from_doaj,
    label=enrich_serials_from_doaj.LABEL,
)


_ATTACH_MONOGRAPHS = Task(
    "attach_monographs",
    reads=(
        "source_records.biblio",
        "source_records.monograph_id",
        "source_records.publisher_id",
        "monographs",
    ),
    writes=(
        "monographs",
        "source_records.monograph_id",
        "publications.monograph_id",
        "source_record_keys_queue",
        "merge_redirects",
    ),
    # Monographies créées ou fusionnées aux runs précédents, reprises par les volumes.
    previous_run=("monographs", "source_records.monograph_id"),
    run=in_transaction(attach_monographs.run_attach_monographs),
    label=attach_monographs.LABEL,
)


_LINK_MONOGRAPHS_TO_COLLECTIONS = Task(
    "link_monographs_to_collections",
    reads=(
        "monographs",
        "source_records.monograph_id",
        "source_records.serial_id",
        "serial_issns",
        "serials.title_normalized",
        "serials.publisher_id",
        "serials.manual_fields",
    ),
    writes=(
        "serials.id",
        "serials.title",
        "serials.title_normalized",
        "serials.serial_type",
        "monographs.serial_id",
    ),
    previous_run=("monographs", "source_records.serial_id", "serial_issns", "serials"),
    run=in_transaction(link_monographs_to_collections.run_link_monographs_to_collections),
    label=link_monographs_to_collections.LABEL,
)


_TYPE_PROCEEDINGS_VOLUMES = Task(
    "type_proceedings_volumes",
    reads=(
        "monographs.id",
        "monographs.serial_id",
        "serials.serial_type",
        "source_records.source",
        "source_records.raw_doc_type",
        "source_records.source_extras",
        "source_records.monograph_id",
    ),
    writes=("monographs.proceedings",),
    previous_run=("monographs", "serials"),
    run=in_transaction(type_proceedings_volumes.run_type_proceedings_volumes),
    label=type_proceedings_volumes.LABEL,
)


STEPS = (
    Step(
        "doi_prefixes",
        "Préfixes DOI",
        "préfixes DOI → éditeur titulaire de chaque préfixe, agence du préfixe inconnu de doi.org",
        (_RESOLVE_CROSSREF_PUBLISHERS, _RESOLVE_DATACITE_PUBLISHERS),
    ),
    Step(
        "publishers",
        "Éditeurs",
        "noms d'éditeur des enregistrements sources → éditeur de chaque enregistrement source, sans doublon",
        (_ATTACH_PUBLISHERS, _MERGE_DUPLICATE_PUBLISHERS),
    ),
    Step(
        "serials",
        "Publications en série",
        "ISSN, titres et identifiants OpenAlex des enregistrements sources → revue de chaque enregistrement source, typée et qualifiée",
        (
            Step(
                "issns",
                "ISSN",
                "ISSN des enregistrements sources → ISSN-L, titre Sudoc et liens de chaque ISSN",
                (_SYNC_ISSNS, _CHECK_ISSNS_IN_SUDOC, _IMPORT_ISSNL_TABLE),
            ),
            _ATTACH_SERIALS,
            Step(
                "qualification",
                "Qualification des revues",
                "revues → identifiant OpenAlex, listes de revues, type, fiche DOAJ",
                (
                    _CHECK_SERIALS_IN_OPENALEX,
                    _TYPE_PROCEEDINGS_SERIALS,
                    _TYPE_JOURNAL_SERIALS,
                    _ENRICH_SERIALS_FROM_DOAJ,
                ),
            ),
            _LEARN_SERIAL_DOI_NAMESPACES,
        ),
    ),
    Step(
        "monographs",
        "Monographies",
        "ISBN et titres des enregistrements sources → monographie de chaque enregistrement source, rattachée à sa collection, typée",
        (_ATTACH_MONOGRAPHS, _LINK_MONOGRAPHS_TO_COLLECTIONS, _TYPE_PROCEEDINGS_VOLUMES),
    ),
)
