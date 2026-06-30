# Vue d'ensemble

*À jour le 2026-06-30.*

Ce fichier présente la logique du pipeline de traitement. Pour les modalités d'exécution, voir [Guide d'exploitation](../exploitation/04-pipeline.md).

Le peuplement de la base s'effectue via un *pipeline* composé des étapes suivantes :

## Moissonnage

- [Moissonnage initial](02-extract.md) : récupère les données brutes depuis les API et les stocke en JSONB dans la table de *staging*.
- [Identification des agences d'enregistrement des DOI](02-extract.md#resolve-ra) : résout l'agence d'enregistrement ([Crossref](../glossaire.md#crossref) ou [DataCite](../glossaire.md#datacite)) des préfixes [DOI](../glossaire.md#doi), pour que l'étape suivante route chaque DOI vers la bonne API plutôt que de l'interroger contre les deux.
- [Imports croisés](02-extract.md#cross-imports) : deux mécanismes de rattrapage cross-source enchaînés — (1) docs HAL manquants repérés par hal-id ou NNT dans d'autres sources, (2) recherche par DOI des documents absents d'une source mais présents dans une autre.
- [Refresh & disparitions](02-extract.md#refresh-stale) : refetch des documents à `last_seen_at` ancien (> 90 j) — rafraîchit les métadonnées vieillissantes et marque (`disappeared_at`) ceux qui ont disparu de leur source.
- [Works OpenAlex tronqués à 100 auteurs](02-extract.md#refetch-truncated) : re-télécharge un par un les works OpenAlex de 100 auteurs, suspects d'avoir été tronqués par le plafond de l'API.

## Normalisation

- [Normalisation](03-normalize.md) : transforme les données brutes (*staging*) en tables structurées *par source* (`source_publications`, `source_authorships`). Extrait les signatures institutionnelles et les centralise dans la table `addresses`. Crée les entités `publishers` et `journals` lorsque les sources les mentionnent.

## Identification des structures

- [Affiliations](04-affiliations.md) : résout les liens adresses → structures via les formes de noms (`structure_name_forms`), puis renseigne `in_perimeter` sur les [authorships](../glossaire.md#authorship) sources.

## Déduplication des publications

- [Publishers & journals](05-publishers-journals.md) : enrichit les référentiels de revues et d'éditeurs à partir de sources externes — préfixes DOI (sources: Crossref + DataCite), montant d'APC et type des revues (sources: OpenAlex Sources, DOAJ). Ces informations sont consommées par la phase de correction des métadonnées.
- [Corrections de métadonnées](06-metadata-correction.md) : prépare les `source_publications` avant leur rattachement, en posant sur leurs colonnes les valeurs corrigées sur lesquelles s'appuiera le matching. Les métadonnées brutes sont conservées, avec l'identifiant de la règle qui les a corrigées. Les métadonnées corrigées sont consommées par la logique de déduplication.
- [Matching des publications](07-publications.md) : peuple et maintient la table canonique `publications` à partir des `source_publications`. Regroupe celles qui désignent le même document (par identifiants et par métadonnées), crée une publication pour chaque document du périmètre UCA, et fusionne ou scinde les publications existantes selon ce regroupement.
- [Relations entre publications](08-relations.md) : peuple `publication_relations`, qui relie des publications distinctes mais apparentées (preprint ↔ version publiée, supplément ↔ article, chapitre ↔ ouvrage, erratum ↔ article corrigé…). (Enjolivement.)

## Rattachement/création des personnes

- [Personnes](09-persons.md) : peuple la table canonique `persons` et ses tables satellites `person_name_forms` et `person_identifiers` (ORCID, idHAL, IdRef) *via* les authorships sources ayant `in_perimeter = true` (renseigné par la phase `affiliations`). Relie les authorships sources aux `person_id` créées.
- [Authorships](10-authorships.md) : peuple la table canonique `authorships` (liens entre `publications` canoniques et `persons` canoniques) à partir des `person_id` référencés dans les authorships sources.

## Compléments: pays, sujets, statut *open access*

- [Pays](11-enrichissements.md) : détection automatisée des pays des adresses. Sert à interroger les collaborations internationales.
- [Sujets](11-enrichissements.md#subjects) : deux étapes enchaînées — (1) ingestion des sujets/mots-clés des `source_publications` vers les tables canoniques `subjects` et `publication_subjects`, (2) recalcul de `subjects.usage_count` + table `subject_cooccurrences` (paires de sujets co-présents sur une même publication).
- [Statut open access](11-enrichissements.md#oa_status) : statut OA par publication via Unpaywall (souvent plus à jour que les sources).
