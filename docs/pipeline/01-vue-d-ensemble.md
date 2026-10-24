# Vue d'ensemble

*À jour le 2026-10-13.*

Ce fichier présente la logique du pipeline de traitement. Pour les modalités d'exécution, voir [Guide d'exploitation](../exploitation/03-pipeline.md).

| Notion | Code | Ce que c'est |
|---|---|---|
| moissonnage | *harvest* : phases `harvest` et `harvest_by_person`, protocole `Harvester` | La collecte des sources. |
| phase | `Phase` | Une unité du run dans les journaux et l'administration. |
| tâche | `Task` | Une étape du graphe du run (`pipeline/graph.py`), avec ses lectures et ses écritures. |
| store | `*Store` | L'accès SQL à une entité dans le pipeline. |

## Moissonnage

- [Moissonnage par affiliation](02-harvest.md#moissonnage-par-affiliation-harvest) : récupère les données brutes depuis les API et les stocke en JSONB dans la table de *staging*.
- [Moissonnage par personne](02-harvest.md#moissonnage-par-personne-harvest_by_person) : interroge chaque source sur les identifiants (ORCID, idHAL, IdRef) des personnes RH.
- [Documents absents d'une source](02-harvest.md#documents-absents-dune-source-fetch_missing) : cherche dans chaque source les documents que le moissonnage initial n'y a pas trouvés.
- [Documents périmés et disparus](02-harvest.md#documents-périmés-et-disparus-fetch_stale) : réinterroge les documents non revus depuis un délai réglable (90 jours par défaut), rafraîchit leurs métadonnées et marque (`disappeared_at`) ceux qui ont disparu.
- [Listes d'auteurs tronquées](02-harvest.md#listes-dauteurs-tronquées-fetch_truncated) : retélécharge un par un les documents OpenAlex de 100 auteurs, que le plafond de l'API a tronqués.

## Normalisation

- [Normalisation](03-normalize.md) : transforme les données brutes (*staging*) en tables structurées (`source_records`, `source_contributions`). Extrait les signatures institutionnelles et les centralise dans la table `addresses`. Peuple les tables `publishers` et `journals`.

## Résolution des structures

- [Affiliations](04-affiliations.md) : résout les liens adresses → structures via les formes de noms (`structure_name_forms`), puis renseigne `in_perimeter` sur les [contributions](../glossaire.md#contribution) sources. Une contribution source entre dans le périmètre par les structures qu'elle atteint : adresse, ROR, structure HAL, établissement de soutenance ou laboratoire partenaire d'une thèse. Elle y entre aussi par les identifiants d'une personne qui a une fiche RH.

## Résolution des publications

- [Identification des agences d'enregistrement des DOI](05-publishers-journals.md#agences-denregistrement-doi-resolve_ra) : résout l'agence d'enregistrement ([Crossref](../glossaire.md#crossref) ou [DataCite](../glossaire.md#datacite)) des préfixes [DOI](../glossaire.md#doi).
- [Publishers & journals](05-publishers-journals.md) : enrichit les référentiels de revues et d'éditeurs à partir de sources externes — préfixes DOI (sources: Crossref + DataCite), catégories de revues (sources: OpenAlex Sources, DOAJ).
- [Corrections de métadonnées](06-metadata-correction.md) : prépare les `source_records` avant leur rattachement, en posant sur leurs colonnes les valeurs corrigées sur lesquelles s'appuiera la résolution. Les métadonnées brutes sont conservées, avec l'identifiant de la règle qui les a corrigées.
- [Publications](07-publications.md) : peuple et maintient le référentiel `publications` à partir des `source_records`. Regroupe celles qui désignent le même document, crée une publication pour chaque document du périmètre, et fusionne ou scinde les publications existantes selon ce regroupement.

## Résolution des personnes

- [Alignement des auteurs](08-author-grouping.md) : réunit en une contribution les contributions sources d'un même auteur dans une publication.
- [Personnes](09-persons.md) : rattache chaque contribution à une personne, et peuple la table `persons` avec ses tables satellites `person_name_forms` et `person_identifiers` (ORCID, idHAL, IdRef).

## Données dérivées des contributions

- [Finalisation](10-finalize.md) : met à jour, après la résolution des personnes, le périmètre des publications, les vues des structures, la purge des publications et des référentiels vides, et les compteurs de publications.

## Enrichissements

- [Relations entre publications](11-enrichissements.md#relations-entre-publications-relations) : peuple `publication_relations`, qui relie des publications apparentées (preprint ↔ version publiée, supplément ↔ article, chapitre ↔ ouvrage, erratum ↔ article corrigé…).
- [Sujets](11-enrichissements.md#sujets-subjects) : ingestion des sujets des `source_records` vers les référentiels `subjects` et `publication_subjects`, puis recalcul de `subjects.usage_count` et de la table `subject_cooccurrences` (paires de sujets co-présents sur une même publication).
- [Pays](11-enrichissements.md#pays-des-adresses-countries) : détection automatisée des pays des adresses. Sert à interroger les collaborations internationales.
- [Statut open access](11-enrichissements.md#statut-open-access-oa_status) : interroge Unpaywall pour obtenir le statut OA à jour des publications.
