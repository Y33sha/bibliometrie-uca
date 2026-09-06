# Vue d'ensemble

*À jour le 2026-06-30.*

Ce fichier présente la logique du pipeline de traitement. Pour les modalités d'exécution, voir [Guide d'exploitation](../exploitation/04-pipeline.md).

## Moissonnage

- [Moissonnage par lots](02-extract.md#moissonnage-par-lots-extract) : récupère les données brutes depuis les API et les stocke en JSONB dans la table de *staging*.
- [Identification des agences d'enregistrement des DOI](02-extract.md#agences-denregistrement-doi-resolve_ra) : résout l'agence d'enregistrement ([Crossref](../glossaire.md#crossref) ou [DataCite](../glossaire.md#datacite)) des préfixes [DOI](../glossaire.md#doi), pour que l'étape suivante route chaque DOI vers la bonne API plutôt que de l'interroger contre les deux.
- [Documents absents d'une source](02-extract.md#documents-absents-dune-source-fetch_missing) : demande à chaque source les documents que les autres sources ont et qu'elle n'a pas — par hal-id ou NNT pour HAL, par DOI pour les six sources interrogeables ainsi.
- [Documents périmés et disparus](02-extract.md#documents-périmés-et-disparus-fetch_stale) : réinterroge les documents vus pour la dernière fois il y a plus de 90 jours, rafraîchit leurs métadonnées et marque (`disappeared_at`) ceux que leur source ne rend plus.
- [Listes d'auteurs tronquées](02-extract.md#listes-dauteurs-tronquées-fetch_truncated) : retélécharge un par un les documents OpenAlex de cent auteurs, que le plafond de l'API a pu tronquer.

## Normalisation

- [Normalisation](03-normalize.md) : transforme les données brutes (*staging*) en tables structurées *par source* (`source_publications`, `source_authorships`). Extrait les signatures institutionnelles et les centralise dans la table `addresses`. Crée les entités `publishers` et `journals` lorsque les sources les mentionnent.

## Résolution des structures

- [Affiliations](04-affiliations.md) : résout les liens adresses → structures via les formes de noms (`structure_name_forms`), puis renseigne `in_perimeter` sur les [authorships](../glossaire.md#authorship) sources.

## Résolution des publications

- [Publishers & journals](05-publishers-journals.md) : enrichit les référentiels de revues et d'éditeurs à partir de sources externes — préfixes DOI (sources: Crossref + DataCite), catégories de revues (sources: OpenAlex Sources, DOAJ). Ces informations sont consommées par la phase de correction des métadonnées.
- [Corrections de métadonnées](06-metadata-correction.md) : prépare les `source_publications` avant leur rattachement, en posant sur leurs colonnes les valeurs corrigées sur lesquelles s'appuiera la résolution. Les métadonnées brutes sont conservées, avec l'identifiant de la règle qui les a corrigées.
- [Publications](07-publications.md) : peuple et maintient le référentiel `publications` à partir des `source_publications`. Regroupe celles qui désignent le même document, par identifiants ou par métadonnées, crée une publication pour chaque document du périmètre, et fusionne ou scinde les publications existantes selon ce regroupement.

## Résolution des personnes

- [Personnes](08-persons.md) : peuple la table `persons` et ses tables satellites `person_name_forms` et `person_identifiers` (ORCID, idHAL, IdRef) *via* les authorships sources ayant `in_perimeter = true` (renseigné par la phase `affiliations`). Relie les authorships sources aux `person_id` créées.

## Consolidation des relations publications-personnes-structures

- [Authorships](09-authorships.md) : peuple la table `authorships` (liens entre les référentiels `publications` et `persons`) à partir des authorships sources.

## Enrichissements

Ces quatre phases n'entrent pas dans la résolution d'entités : rien en amont ne les lit, et `--no-extras` les omet.

- [Relations entre publications](10-relations.md) : peuple `publication_relations`, qui relie des publications distinctes mais apparentées (preprint ↔ version publiée, supplément ↔ article, chapitre ↔ ouvrage, erratum ↔ article corrigé…).
- [Sujets](11-enrichissements.md#sujets) : deux étapes enchaînées — (1) ingestion des sujets/mots-clés des `source_publications` vers les référentiels `subjects` et `publication_subjects`, (2) recalcul de `subjects.usage_count` + table `subject_cooccurrences` (paires de sujets co-présents sur une même publication).
- [Pays](11-enrichissements.md) : détection automatisée des pays des adresses. Sert à interroger les collaborations internationales.
- [Statut open access](11-enrichissements.md#statut-open-access) : statut OA par publication via Unpaywall (souvent plus à jour que les sources).
