# Vue d'ensemble

Ce fichier présente la logique du pipeline de traitement. Pour les modalités d'exécution, voir [Guide d'exploitation](../exploitation/04-pipeline.md).

Le peuplement de la base s'effectue via un *pipeline* composé des étapes suivantes :

## Moissonnage

- [Moissonnage initial](02-extract.md) : récupère les données brutes depuis les API et les stocke en JSONB dans la table de *staging*.
- [Résolution des Registration Agencies](02-extract.md#resolve-ra) : résout la Registration Agency (Crossref ou DataCite) des préfixes DOI, pour que l'import croisé par DOI route chaque DOI vers la bonne API plutôt que de l'interroger contre les deux.
- [Imports croisés](02-extract.md#cross-imports) : deux mécanismes de rattrapage cross-source enchaînés — (1) docs HAL manquants repérés par hal-id ou NNT dans d'autres sources, (2) recherche par DOI des records absents d'une source mais présents dans une autre.
- [Refresh & disparitions](02-extract.md#refresh-stale) : refetch des documents à `last_seen_at` ancien (> 90 j) — rafraîchit les métadonnées vieillissantes et marque (`disappeared_at`) ceux qui ont disparu de leur source.
- [Works OpenAlex tronqués](02-extract.md#refetch-truncated) : re-télécharge les works OpenAlex dont la liste d'auteurs dépasse le plafond de 100 de l'API.

## Normalisation

- [Normalisation](03-normalize.md) : transforme les données brutes (*staging*) en tables structurées *par source* (`source_publications`, `source_authorships`). Crée également les `addresses` et leurs liens `source_authorship_addresses`, ainsi que les entités `publishers` et `journals` lorsque les sources les mentionnent.

## Repérage des affiliations

- [Affiliations](04-affiliations.md) : résout les liens adresses → structures via les formes de noms (`structure_name_forms`), puis renseigne `in_perimeter` sur les [authorships](../glossaire.md#authorship) sources.

## Enrichissement des référentiels publishers et journals

- [Publishers & journals](05-publishers-journals.md) : enrichit les référentiels de revues et d'éditeurs à partir de sources externes — préfixes DOI (sources: Crossref + DataCite), montant d'APC et type des revues (sources: OpenAlex Sources, DOAJ).

## Correction des métadonnées

- [Corrections de métadonnées](06-metadata-correction.md) : prépare les `source_publications` avant leur rattachement, en posant sur leurs colonnes les valeurs corrigées sur lesquelles s'appuiera le matching. Corrections par enregistrement (champs erronés, identifiants à neutraliser) et par grappe de documents partageant un DOI (convergence des versions d'un dépôt sur son DOI concept stable, neutralisation des DOI partagés à tort entre documents distincts).

## Création/rattachement des publications

- [Publications](07-publications.md) : peuple et maintient la table canonique `publications` à partir des `source_publications`. Regroupe celles qui désignent le même document (par identifiants et par métadonnées), crée une publication pour chaque document du périmètre UCA, et fusionne ou scinde les publications existantes selon ce regroupement.

## Relations entre publications

- [Relations](08-relations.md) : peuple `publication_relations`, qui relie des publications **distinctes** apparentées (preprint ↔ version publiée, supplément ↔ article, chapitre ↔ ouvrage, erratum ↔ article corrigé…). Deux signaux : les relations typées déclarées par DataCite et Crossref, et les publications qui partagent une clé d'identité sans avoir fusionné (DOI distincts). Les cibles encore hors corpus rejoignent les imports croisés.

## Création/rattachement des personnes

- [Personnes](09-persons.md) : peuple la table canonique `persons` et ses tables satellites `person_name_forms` et `person_identifiers` (ORCID, idHAL, IdRef) *via* les authorships sources ayant `in_perimeter = true`. Mappe les authorships sources aux `person_id` créées.
- [Authorships](10-authorships.md) : peuple la table canonique `authorships` (liens entre `publications` canoniques et `persons` canoniques) à partir des `person_id` référencés dans les authorships sources.

## Enrichissements

- [Pays](11-enrichissements.md) : détection automatisée des pays des adresses. Sert à interroger les collaborations internationales.
- [Sujets](11-enrichissements.md#subjects) : deux étapes enchaînées — (1) ingestion des sujets/mots-clés des `source_publications` vers les tables canoniques `subjects` et `publication_subjects`, (2) recalcul de `subjects.usage_count` + table `subject_cooccurrences` (paires de sujets co-présents sur une même publication).
- [Statut open access](11-enrichissements.md#oa_status) : statut OA par publication via Unpaywall (souvent plus à jour que les sources).
