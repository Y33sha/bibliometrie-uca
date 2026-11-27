"""Description d'une ligne de chaque tâche du pipeline, affichée au clic sur la tâche."""

from __future__ import annotations

SOURCES = {
    "hal": "HAL",
    "openalex": "OpenAlex",
    "wos": "WoS",
    "scanr": "ScanR",
    "ops": "OPS",
    "theses": "theses.fr",
    "datacite": "DataCite",
    "inspire": "INSPIRE-HEP",
    "crossref": "Crossref",
}

SHORT: dict[str, str] = {
    "perimeter_structures": "Liste des structures de chaque périmètre.",
    "fetch_missing.hal_by_id": "Documents absents de HAL, cherchés par le hal-id vu dans OpenAlex ou ScanR.",
    "fetch_missing.hal_by_nnt": "Thèses de theses.fr absentes de HAL, cherchées dans HAL par NNT.",
    "fetch_missing.scanr_by_hal_id": "Documents absents de ScanR, cherchés par le hal-id vu dans HAL ou OpenAlex.",
    "fetch_missing.theses_by_nnt": "Thèses absentes de theses.fr, cherchées par le NNT vu dans une autre source.",
    "fetch_missing.ops_by_number": "Familles de brevets absentes d'OPS, cherchées par numéro.",
    "fetch_truncated.refetch_openalex": "Listes d'auteurs OpenAlex tronquées, complétées.",
    "normalize.withhold_openalex_authors": "Retire les auteurs d'un enregistrement OpenAlex présent aussi dans INSPIRE-HEP.",
    "normalize.prune_disappeared": "Supprime les enregistrements sources disparus de leur source.",
    "normalize.cleanup_orphan_contributor_information": "Supprime les informations du contributeur sans contribution source.",
    "normalize.cleanup_orphan_addresses": "Supprime les adresses sans contribution source ni décision manuelle.",
    "normalize.arbitrate_identifiers": "Neutralise un identifiant de personne écrit sous un autre nom que son nom majoritaire.",
    "structures.refresh_ror": "Importe la dernière version du dump ROR.",
    "structures.refresh_hal_structures": "Charge les structures HAL citées et absentes du référentiel, avec leurs parents.",
    "dois.resolve_prefixes": "Agence de chaque préfixe DOI : Crossref, DataCite ou inconnue.",
    "dois.resolve_dois": "Existence et URL de chaque DOI chez doi.org.",
    "publishing.resolve_crossref_publishers": "Éditeur titulaire de chaque préfixe Crossref.",
    "publishing.resolve_datacite_publishers": "Organisation et entrepôt de chaque préfixe DataCite.",
    "publishing.attach_publishers": "Rattache chaque enregistrement source à l'éditeur qu'il nomme.",
    "publishing.merge_duplicate_publishers": "Fusionne les noms d'un même éditeur.",
    "publishing.sync_issns": "Recense les ISSN valides des enregistrements sources.",
    "publishing.check_issns_in_sudoc": "Notice Sudoc de chaque ISSN : titre, statut, titres liés.",
    "publishing.import_issnl_table": "Importe la table des ISSN-L de l'ISSN International Centre.",
    "publishing.attach_serials": "Rattache chaque enregistrement source à sa revue : ISSN-L, sinon identifiant OpenAlex, sinon titre.",
    "publishing.check_serials_in_openalex": "Fiche OpenAlex de chaque revue : identifiant, type, open access, listes.",
    "publishing.type_proceedings_serials": "Type en recueil d'actes les revues faites surtout d'articles de congrès.",
    "publishing.type_journal_serials": "Type en revue les séries de type inconnu faites surtout d'articles.",
    "publishing.enrich_serials_from_doaj": "Fiche DOAJ de chaque revue, rattachée par ISSN.",
    "publishing.model_serials": "Modèle open access de chaque revue : diamant, open access intégral, abonnement.",
    "publishing.attach_monographs": "Rattache chaque volume à sa monographie.",
    "publishing.link_monographs_to_collections": "Rattache chaque monographie à sa collection.",
    "publishing.type_proceedings_volumes": "Distingue les volumes d'actes des livres.",
    "publishing.learn_serial_doi_namespaces": "Espace de noms DOI de chaque revue, par exemple 10.1016/j.physletb.",
    "publishing.serial_by_doi": "Donne sa revue à un enregistrement source sans revue, d'après son DOI.",
    "affiliations.classify_addresses": "Classe le texte des adresses : adresse brute, libellé HAL ou nom seul.",
    "affiliations.detect_concatenated_addresses": "Repère les adresses qui réunissent plusieurs affiliations.",
    "affiliations.resolve_addresses": "Cherche les noms de structures dans le texte des adresses.",
    "affiliations.resolve_thesis_partners": "Cherche les noms de structures dans les laboratoires partenaires des thèses.",
    "affiliations.decide_source_contribution_perimeter": "Décide l'entrée de chaque contribution source dans le périmètre.",
    "countries.detect_by_country_name": "Pays proposés par les noms de pays des adresses.",
    "countries.detect_by_place_name": "Pays proposés par les noms d'institutions et de villes des adresses.",
    "countries.resolve_countries": "Retient les pays de chaque adresse parmi les pays proposés.",
    "countries.refresh_source_record_countries": "Reporte les pays des adresses sur les contributions et les enregistrements sources.",
    "metadata_correction.correct_source_records": "Corrige le type de document et les identifiants de chaque enregistrement source.",
    "metadata_correction.doi_targets": "Relie le DOI d'une forme secondaire, comme une version Zenodo, au DOI de l'œuvre.",
    "metadata_correction.remove_identifiers": "Retire les DOI partagés par des œuvres distinctes, et les DOI inconnus de doi.org.",
    "metadata_correction.decide_matchability": "Écarte de la réconciliation certains enregistrements sources : paratexte, doublon retiré…",
    "publications.reconcile": "Rattache chaque enregistrement source à sa publication : création, fusion ou scission.",
    "publications.consolidate_publications": "Calcule les métadonnées de chaque publication depuis ses enregistrements sources.",
    "relations.rebuild_publication_relations": "Relations entre publications : versions, preprints, clés partagées.",
    "relations.link_notices": "Relations des publications avec leurs errata et avis.",
    "relations.flag_retracted_publications": "Marque les publications rétractées.",
    "subjects.derive_publication_subjects": "Lie chaque publication aux sujets de ses enregistrements sources et à leurs ancêtres.",
    "author_grouping.align_source_contributions": "Aligne les auteurs d'une publication d'une source à l'autre.",
    "author_grouping.recompute_contribution_attributes": "Rôles, indices de périmètre et positions de chaque contribution.",
    "persons.resolve_contributions": "Rattache chaque contribution à une personne, et crée les personnes inconnues.",
    "persons.populate_person_name_forms": "Régénère les formes de nom des personnes.",
    "persons.purge_persons": "Supprime les personnes sans contribution du périmètre.",
    "suspect_attributions.detect_suspect_attributions": "Signale les publications d'une personne probablement signées par un homonyme.",
    "finalize.purge_publications": "Supprime les publications sans enregistrement source, ou sans personne ni indice lié au document.",
    "finalize.publications_in_perimeter": "Décide le périmètre des publications.",
    "finalize.refresh_structure_views": "Relie les contributions et les publications à leurs structures.",
    "finalize.serial_publishers": "Donne à chaque revue l'éditeur de ses publications récentes.",
    "finalize.delete_empty_monographs": "Supprime les monographies vides.",
    "finalize.delete_empty_serials": "Supprime les revues vides.",
    "finalize.delete_empty_publishers": "Supprime les éditeurs vides.",
    "finalize.publication_counts": "Recompte les publications des adresses, revues et éditeurs.",
    "finalize.count_subject_usage": "Recompte l'usage et les co-occurrences des sujets.",
    "open_access.verify_unpaywall": "Statut open access du DOI de chaque publication chez Unpaywall.",
    "open_access.recompute_oa_status": "Statut open access de chaque publication.",
}

for key, label in SOURCES.items():
    SHORT[f"harvest.{key}"] = f"Documents {label} qui mentionnent une structure du périmètre."
    SHORT[f"harvest_by_person.{key}"] = (
        f"Documents {label} des personnes RH, par leurs identifiants."
    )
    SHORT[f"fetch_missing.doi.{key}"] = (
        f"Documents absents de {label}, cherchés par le DOI vu dans une autre source."
    )
    SHORT[f"fetch_stale.{key}"] = (
        f"Documents {label} non revus depuis un délai, cherchés de nouveau."
    )
    SHORT[f"normalize.{key}"] = (
        f"Documents bruts {label} : enregistrements sources, contributions sources, adresses."
    )
