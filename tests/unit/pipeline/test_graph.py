"""Le graphe de dépendances du pipeline (`pipeline.graph`) est cohérent avec l'ordre d'exécution."""

import re
from pathlib import Path

from domain.sources.registry import (
    DOI_SEARCHABLE_SOURCES,
    HARVESTED_SOURCES,
    SOURCE_PRIORITY,
    Source,
)
from pipeline.graph import Task, dependencies, order_violations
from pipeline.phases import ALL_TASKS, PHASES
from pipeline.runtime.observability.metrics import PhaseMetrics

_TASKS = {phase.name: phase.tasks for phase in PHASES}


def _names(phase: str) -> list[str]:
    return [task.name for task in _TASKS[phase]]


def test_noms_uniques():
    names = [n.name for n in ALL_TASKS]
    assert len(names) == len(set(names))


def test_une_tache_d_extraction_par_source_moissonnee():
    assert _names("harvest") == list(HARVESTED_SOURCES)


def test_une_tache_de_relecture_par_source():
    """Crossref aussi : `fetch_stale` relit toutes les sources par identifiant natif."""
    assert _names("fetch_stale") == list(Source)


def test_une_tache_de_recherche_par_doi_par_source_interrogeable():
    """HAL aussi : `fetch_missing` l'interroge par DOI, en plus des canaux hal-id et NNT."""
    doi_tasks = [name for name in _names("fetch_missing") if name.startswith("doi.")]
    assert doi_tasks == [f"doi.{s}" for s in DOI_SEARCHABLE_SOURCES]


def test_normalisation_dans_l_ordre_de_priorite_des_sources():
    normalize_tasks = [name for name in _names("normalize") if name in set(SOURCE_PRIORITY)]
    assert normalize_tasks == [s.value for s in SOURCE_PRIORITY]
    assert set(SOURCE_PRIORITY) == set(Source)


def test_aucune_tache_ne_lit_une_donnee_ecrite_apres_elle():
    """Toute lecture d'une donnée écrite par une tâche placée après est déclarée lue au run précédent."""
    assert order_violations(ALL_TASKS) == []


_SCHEMA = Path(__file__).resolve().parents[3] / "infrastructure" / "db" / "schema.sql"


def _schema() -> tuple[dict[str, set[str]], set[str]]:
    """Renvoie les colonnes de chaque table du snapshot du schéma, et les noms des vues."""
    columns: dict[str, set[str]] = {}
    views: set[str] = set()
    current: set[str] | None = None
    for line in _SCHEMA.read_text().splitlines():
        if table := re.match(r"CREATE TABLE \w+\.(\w+) \($", line):
            current = columns.setdefault(table.group(1), set())
        elif view := re.match(r"CREATE (?:MATERIALIZED )?VIEW \w+\.(\w+) AS", line):
            views.add(view.group(1))
        elif current is not None:
            if line.startswith(")"):
                current = None
            elif not line.lstrip().startswith("CONSTRAINT"):
                current.add(line.split()[0].strip('"'))
    return columns, views


def test_chaque_donnee_declaree_existe_dans_le_schema():
    """Une table, une vue ou une colonne déclarée lue ou écrite existe dans `infrastructure/db/schema.sql`. `<table>.id` désigne l'existence des lignes, même sans colonne `id`."""
    columns, views = _schema()
    unknown = sorted(
        (task.name, item)
        for task in ALL_TASKS
        for item in {*task.reads, *task.writes, *task.previous_run}
        if not (
            item in views
            or item in columns
            or (
                (table_column := item.partition("."))[0] in columns
                and table_column[2] in {*columns[table_column[0]], "id"}
            )
        )
    )
    assert unknown == []


def _task(name: str, **declarations: tuple[str, ...]) -> Task:
    return Task(name, run=lambda _ctx: PhaseMetrics(), **declarations)


def test_lecture_non_declaree_detectee():
    writer = _task("b", writes=("t.c",))
    reader = _task("a", reads=("t",))
    assert order_violations([reader, writer]) == [("a", "t", "b")]
    declared = _task("a", reads=("t",), previous_run=("t.c",))
    assert order_violations([declared, writer]) == []


def test_creation_de_lignes_change_toute_lecture_de_la_table():
    writer = _task("b", writes=("t.id",))
    reader = _task("a", reads=("t.c",))
    assert order_violations([reader, writer]) == [("a", "t.c", "b")]
    column_writer = _task("b", writes=("t.c",))
    id_reader = _task("a", reads=("t.id",))
    assert order_violations([id_reader, column_writer]) == []


def test_le_rattachement_des_revues_suit_la_verification_sudoc():
    """Le rattachement lit l'ISSN-L de chaque ISSN, écrit par la vérification Sudoc."""
    deps = dependencies(ALL_TASKS)["publishing.attach_serials"]
    assert {"publishing.sync_issns", "publishing.check_issns_in_sudoc"} <= deps


def test_le_typage_openalex_suit_le_rattachement_des_revues():
    """Le typage OpenAlex lit l'identifiant OpenAlex des revues, écrit par le rattachement."""
    assert (
        "publishing.attach_serials"
        in dependencies(ALL_TASKS)["publishing.enrich_serials_from_openalex"]
    )


def test_le_nettoyage_des_informations_du_contributeur_suit_la_suppression_des_enregistrements_sources_disparus():
    """La suppression d'un enregistrement source supprime ses contributions sources et rend orphelines des informations du contributeur."""
    deps = dependencies(ALL_TASKS)["normalize.cleanup_orphan_contributor_information"]
    assert "normalize.prune_disappeared" in deps


def test_le_nettoyage_des_adresses_suit_la_normalisation_et_la_suppression_des_enregistrements_sources_disparus():
    """Réécrire ou supprimer des contributions sources rend des adresses orphelines."""
    deps = dependencies(ALL_TASKS)["normalize.cleanup_orphan_addresses"]
    assert {"normalize.hal", "normalize.prune_disappeared"} <= deps


def test_la_resolution_des_adresses_suit_leur_nettoyage():
    deps = dependencies(ALL_TASKS)["affiliations.resolve_addresses"]
    assert "normalize.cleanup_orphan_addresses" in deps


def test_les_decomptes_de_sujets_ne_dependent_pas_des_publications():
    """Les décomptes lisent seulement `publication_subjects` : le périmètre des publications ne les concerne pas."""
    deps = dependencies(ALL_TASKS)["subjects.usage"]
    assert "finalize.publications_in_perimeter" not in deps


def test_les_vues_des_structures_suivent_la_purge_des_publications():
    """La purge supprime les contributions des publications purgées : les vues portent sur les contributions restantes."""
    assert "finalize.purge_publications" in dependencies(ALL_TASKS)["finalize.structures"]


def test_les_referentiels_vides_se_suppriment_monographies_puis_revues_puis_editeurs():
    """Une monographie retient sa collection, une revue son éditeur."""
    deps = dependencies(ALL_TASKS)
    assert "finalize.delete_empty_monographs" in deps["finalize.delete_empty_serials"]
    assert "finalize.delete_empty_serials" in deps["finalize.delete_empty_publishers"]


def test_la_normalisation_de_theses_ne_touche_pas_aux_referentiels_de_publication():
    theses = next(n for n in ALL_TASKS if n.name == "normalize.theses")
    assert not any(
        item.startswith(("serials", "publishers", "monographs")) for item in theses.writes
    )


def test_chaque_canal_de_fetch_missing_declare_ses_propres_lectures():
    """Les lectures communes viennent du groupe ; seuls les canaux Crossref et DataCite lisent l'agence des préfixes."""
    reads = {task.name: task.reads for task in _TASKS["fetch_missing"]}
    assert all("failed_lookups" in r for r in reads.values())
    lisent_l_agence = {name for name, r in reads.items() if "doi_prefixes.ra" in r}
    assert lisent_l_agence == {"doi.crossref", "doi.datacite"}


def test_un_lot_est_d_un_seul_tenant_et_sans_dependance_interne():
    deps = dependencies(ALL_TASKS)
    lots: dict[str, list[int]] = {}
    for index, task in enumerate(ALL_TASKS):
        if task.parallel_group is not None:
            lots.setdefault(task.parallel_group, []).append(index)
    assert lots
    for indices in lots.values():
        assert indices == list(range(indices[0], indices[-1] + 1))
        noms = {ALL_TASKS[i].name for i in indices}
        assert all(not (deps[ALL_TASKS[i].name] & noms) for i in indices)
