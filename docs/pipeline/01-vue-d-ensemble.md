# Vue d'ensemble

*Document à jour au 2026-05-26.*

Ce fichier présente la logique du pipeline de traitement. Pour les modalités d'exécution, voir [Guide d'exploitation](../exploitation/04-pipeline.md).

Le peuplement de la base s'effectue via un *pipeline* composé des étapes suivantes :

## Moissonnage

- [Moissonnage initial](02-extract.md) : récupère les données brutes depuis les API et les stocke en JSONB dans la table de *staging*.
- [Imports croisés](02-extract.md#cross-imports) : deux mécanismes de rattrapage cross-source enchaînés — (1) docs HAL manquants repérés par hal-id ou NNT dans d'autres sources, (2) recherche par DOI des records absents d'une source mais présents dans une autre.

## Normalisation

- [Normalisation](03-normalize.md) : transforme les données brutes (*staging*) en tables structurées *par source* (`source_publications`, `source_authorships`). Crée également les `addresses` et leurs liens `source_authorship_addresses`, ainsi que les entités `publishers` et `journals` lorsque les sources les mentionnent.

## Enrichissement des référentiels publishers et journals

- [Publishers & journals](04-publishers-journals.md) : enrichit les référentiels créés en normalisation à partir de sources externes — DOI prefixes (Crossref + DataCite), APC et type des revues (OpenAlex Sources, DOAJ API), pays et ROR des éditeurs (OpenAlex Publishers, fallback Crossref Members), typage des éditeurs (ROR).

## Repérage des affiliations

- [Affiliations](05-affiliations.md) : résout les adresses → structures via les formes de noms (`structure_name_forms`), puis renseigne `in_perimeter` et `structure_ids` sur les [authorships](../glossaire.md#authorship) sources.

## Création/rattachement des publications

- [Publications](06-publications.md) : peuple la table canonique `publications` à partir des publications sources *via* les authorships sources ayant `in_perimeter = true`. Dédoublonne.

## Création/rattachement des personnes

- [Personnes](07-persons.md) : peuple la table canonique `persons` et ses tables satellites `person_name_forms` et `person_identifiers` (ORCID, idHAL, IdRef) *via* les authorships sources ayant `in_perimeter = true`. Mappe les authorships sources aux `person_id` créées.
- [Authorships](08-authorships.md) : peuple la table canonique `authorships` (liens entre `publications` canoniques et `persons` canoniques) à partir des `person_id` référencés dans les authorships sources.

## Enrichissements

- [Pays](09-enrichissements.md) : détection automatisée des pays des adresses. Utile pour interroger les collaborations internationales.
- [Sujets](09-enrichissements.md#subjects) : deux étapes enchaînées — (1) ingestion des sujets/mots-clés des `source_publications` vers les tables canoniques `subjects` et `publication_subjects`, (2) recalcul de `subjects.usage_count` + table `subject_cooccurrences` (paires de sujets co-présents sur une même publication).
- [Statut open access](09-enrichissements.md#oa_status) : statut OA par publication via Unpaywall (plus à jour que les sources).
