# Vue d'ensemble

*Document à jour au 2026-05-13.*

Ce fichier présente la logique du pipeline de traitement. Pour les modalités d'exécution, voir [Guide d'exploitation](../exploitation#pipeline).

Le peuplement de la base s'effectue via un *pipeline* composé des étapes suivantes :

## Moissonnage

- [Moissonnage](extract) : récupère les données brutes depuis les API et les stocke en JSONB dans la table de *staging*.
- [Cross-imports](cross-imports) : deux mécanismes de rattrapage cross-source enchaînés — (1) docs HAL manquants repérés par hal-id ou NNT dans d'autres sources, (2) recherche par DOI des records absents d'une source mais présents dans une autre.

## Normalisation

- [Normalisation](normalize) : transforme les données brutes (*staging*) en tables structurées *par source* (`source_publications`, `source_authorships`). Crée également les `addresses` et leurs liens `source_authorship_addresses`.

## Repérage des affiliations

- [Affiliations](affiliations) : résout les adresses → structures via les formes de noms (`structure_name_forms`), puis renseigne `in_perimeter` et `structure_ids` sur les [authorships](../glossaire#authorship) sources.

## Création/rattachement des publications

- [Publications](publications) : peuple la table canonique `publications` à partir des publications sources *via* les authorships sources ayant `in_perimeter = true`. Dédoublonne.

## Création/rattachement des personnes

- [Personnes](persons) : peuple la table canonique `persons` et ses tables satellites `person_name_forms` et `person_identifiers` (ORCID, idHAL, IdRef) *via* les authorships sources ayant `in_perimeter = true`. Mappe les authorships sources aux `person_id` créées.
- [Authorships](authorships) : peuple la table canonique `authorships` (liens entre `publications` canoniques et `persons` canoniques) à partir des `person_id` référencés dans les authorships sources.

## Enrichissements divers

- [Pays](countries) : détection automatisée des pays des adresses. Utile pour interroger les collaborations internationales.
- [Sujets](subjects) : deux étapes enchaînées — (1) ingestion des sujets/mots-clés des `source_publications` vers les tables canoniques `subjects` et `publication_subjects`, (2) recalcul de `subjects.usage_count` + table `subject_cooccurrences` (paires de sujets co-présents sur une même publication).
- [Statut open access et APC](enrich) : statut OA via Unpaywall (plus à jour que les sources) ; montant APC par revue via OpenAlex Sources.
