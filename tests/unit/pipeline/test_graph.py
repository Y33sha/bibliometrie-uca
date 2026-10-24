"""Le graphe de dépendances du pipeline (`pipeline.graph`) est cohérent avec l'ordre d'exécution."""

from domain.sources.registry import (
    ALL_SOURCES,
    DOI_SEARCHABLE_SOURCES,
    HARVESTED_SOURCES,
    SOURCE_PRIORITY,
)
from pipeline.graph import PHASE_ORDER, TASKS, Task, dependencies, order_violations
from pipeline.ingestion.common.normalize import _normalize_builders


def test_noms_uniques():
    names = [n.name for n in TASKS]
    assert len(names) == len(set(names))


def test_les_taches_d_une_phase_se_suivent():
    """Le périmètre matérialisé d'abord, puis les tâches de chaque phase d'un seul tenant : l'ordre des phases se lit sur leurs tâches."""
    order = ["run", *PHASE_ORDER]
    phases = [n.phase for n in TASKS]
    assert phases[0] == "run"
    assert phases == sorted(phases, key=order.index)


def test_une_tache_d_extraction_par_source_moissonnee():
    extract_tasks = [n.name for n in TASKS if n.phase == "harvest"]
    assert extract_tasks == [f"harvest.{s}" for s in HARVESTED_SOURCES]


def test_une_tache_de_relecture_par_source():
    """Crossref aussi : `fetch_stale` relit toutes les sources par identifiant natif."""
    stale_tasks = [n.name for n in TASKS if n.phase == "fetch_stale"]
    assert stale_tasks == [f"fetch_stale.{s}" for s in ALL_SOURCES]


def test_une_tache_de_recherche_par_doi_par_source_interrogeable():
    """HAL aussi : `fetch_missing` l'interroge par DOI, en plus des canaux hal-id et NNT."""
    doi_tasks = [n.name for n in TASKS if n.name.startswith("fetch_missing.doi.")]
    assert doi_tasks == [f"fetch_missing.doi.{s}" for s in DOI_SEARCHABLE_SOURCES]


def test_normalisation_dans_l_ordre_de_priorite_des_sources():
    normalize_tasks = [
        n.name.removeprefix("normalize.")
        for n in TASKS
        if n.phase == "normalize" and n.name.removeprefix("normalize.") in set(SOURCE_PRIORITY)
    ]
    assert normalize_tasks == [s.value for s in SOURCE_PRIORITY]
    assert set(_normalize_builders(archive=False)) == {s.value for s in SOURCE_PRIORITY}


def test_aucune_tache_ne_lit_une_donnee_ecrite_apres_elle():
    """Toute lecture d'une donnée qu'une tâche placée après écrit est déclarée lue au run précédent."""
    assert order_violations(TASKS) == []


def test_lecture_non_declaree_detectee():
    writer = Task("b", "g", writes=frozenset({"t.c"}))
    reader = Task("a", "g", reads=frozenset({"t"}))
    assert order_violations([reader, writer]) == [("a", "t", "b")]
    declared = Task("a", "g", reads=frozenset({"t"}), previous_run=frozenset({"t.c"}))
    assert order_violations([declared, writer]) == []


def test_creation_de_lignes_change_toute_lecture_de_la_table():
    writer = Task("b", "g", writes=frozenset({"t.id"}))
    reader = Task("a", "g", reads=frozenset({"t.c"}))
    assert order_violations([reader, writer]) == [("a", "t.c", "b")]
    column_writer = Task("b", "g", writes=frozenset({"t.c"}))
    id_reader = Task("a", "g", reads=frozenset({"t.id"}))
    assert order_violations([id_reader, column_writer]) == []


def test_la_fusion_des_revues_suit_le_typage_openalex():
    """La fusion lit le type, l'APC et le modèle open access des revues, que l'enrichissement OpenAlex écrit."""
    deps = dependencies(TASKS)["publishers_journals.merge_duplicate_journals"]
    assert "publishers_journals.enrich_journals_from_openalex" in deps


def test_le_nettoyage_des_informations_du_contributeur_suit_la_suppression_des_enregistrements_sources_disparus():
    """Supprimer un enregistrement source emporte ses contributions sources, et donc des informations du contributeur deviennent orphelines."""
    deps = dependencies(TASKS)["normalize.cleanup_orphan_contributor_information"]
    assert "normalize.prune_disappeared" in deps


def test_le_nettoyage_des_adresses_suit_la_normalisation_et_la_suppression_des_enregistrements_sources_disparus():
    """Réécrire ou supprimer des contributions sources rend des adresses orphelines."""
    deps = dependencies(TASKS)["normalize.cleanup_orphan_addresses"]
    assert {"normalize.hal", "normalize.prune_disappeared"} <= deps


def test_la_resolution_des_adresses_suit_leur_nettoyage():
    deps = dependencies(TASKS)["affiliations.resolve_addresses"]
    assert "normalize.cleanup_orphan_addresses" in deps


def test_les_decomptes_de_sujets_ne_dependent_pas_des_publications():
    """Les décomptes lisent seulement `publication_subjects` : le périmètre des publications ne les concerne pas."""
    deps = dependencies(TASKS)["subjects.usage"]
    assert "finalize.publications_in_perimeter" not in deps


def test_la_normalisation_de_theses_ne_touche_pas_aux_referentiels_de_publication():
    theses = next(n for n in TASKS if n.name == "normalize.theses")
    assert not any(
        item.startswith(("journals", "publishers", "monographs")) for item in theses.writes
    )


def test_chaque_canal_de_fetch_missing_declare_ses_propres_lectures():
    """Les lectures communes viennent du groupe ; seuls les canaux Crossref et DataCite lisent l'agence des préfixes."""
    reads = {n.name: n.reads for n in TASKS if n.phase == "fetch_missing"}
    assert all("failed_lookups" in r for r in reads.values())
    lisent_l_agence = {name for name, r in reads.items() if "doi_prefixes.ra" in r}
    assert lisent_l_agence == {"fetch_missing.doi.crossref", "fetch_missing.doi.datacite"}


def test_un_lot_est_d_un_seul_tenant_et_sans_dependance_interne():
    deps = dependencies(TASKS)
    lots: dict[str, list[int]] = {}
    for index, task in enumerate(TASKS):
        if task.parallel_group is not None:
            lots.setdefault(task.parallel_group, []).append(index)
    assert lots
    for indices in lots.values():
        assert indices == list(range(indices[0], indices[-1] + 1))
        noms = {TASKS[i].name for i in indices}
        assert all(not (deps[TASKS[i].name] & noms) for i in indices)
