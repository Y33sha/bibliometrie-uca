# Vue d'ensemble

*À jour le 2026-09-06.*

Ce fichier présente la logique du pipeline de traitement. Pour les modalités d'exécution, voir [Guide d'exploitation](../exploitation/03-pipeline.md).

## Moissonnage

- [Moissonnage](02-extract.md#moissonnage-extract) : récupère les données brutes depuis les API et les stocke en JSONB dans la table de *staging*.
- [Identification des agences d'enregistrement des DOI](02-extract.md#agences-denregistrement-doi-resolve_ra) : résout l'agence d'enregistrement ([Crossref](../glossaire.md#crossref) ou [DataCite](../glossaire.md#datacite)) des préfixes [DOI](../glossaire.md#doi).
- [Documents absents d'une source](02-extract.md#documents-absents-dune-source-fetch_missing) : cherche dans chaque source les documents que le moissonnage initial n'y a pas trouvés.
- [Documents périmés et disparus](02-extract.md#documents-périmés-et-disparus-fetch_stale) : réinterroge les documents vus pour la dernière fois il y a plus de 90 jours, rafraîchit leurs métadonnées et marque (`disappeared_at`) ceux qui ont disparu.
- [Listes d'auteurs tronquées](02-extract.md#listes-dauteurs-tronquées-fetch_truncated) : retélécharge un par un les documents OpenAlex de 100 auteurs, que le plafond de l'API a tronqués.

## Normalisation

- [Normalisation](03-normalize.md) : transforme les données brutes (*staging*) en tables structurées (`source_publications`, `source_authorships`). Extrait les signatures institutionnelles et les centralise dans la table `addresses`. Peuple les tables `publishers` et `journals`.

## Résolution des structures

- [Affiliations](04-affiliations.md) : résout les liens adresses → structures via les formes de noms (`structure_name_forms`), puis renseigne `in_perimeter` sur les [authorships](../glossaire.md#authorship) sources.

## Résolution des publications

- [Publishers & journals](05-publishers-journals.md) : enrichit les référentiels de revues et d'éditeurs à partir de sources externes — préfixes DOI (sources: Crossref + DataCite), catégories de revues (sources: OpenAlex Sources, DOAJ).
- [Corrections de métadonnées](06-metadata-correction.md) : prépare les `source_publications` avant leur rattachement, en posant sur leurs colonnes les valeurs corrigées sur lesquelles s'appuiera la résolution. Les métadonnées brutes sont conservées, avec l'identifiant de la règle qui les a corrigées.
- [Publications](07-publications.md) : peuple et maintient le référentiel `publications` à partir des `source_publications`. Regroupe celles qui désignent le même document, crée une publication pour chaque document du périmètre, et fusionne ou scinde les publications existantes selon ce regroupement.

## Résolution des personnes

- [Personnes](08-persons.md) : rattache chaque authorship source à une personne, et peuple la table `persons` avec ses tables satellites `person_name_forms` et `person_identifiers` (ORCID, idHAL, IdRef).

## Consolidation des relations publications-personnes-structures

- [Authorships](09-authorships.md) : peuple la table `authorships` (table de liaison entre les référentiels `publications` et `persons`) à partir des authorships sources.

## Enrichissements

- [Relations entre publications](10-enrichissements.md#relations-entre-publications-relations) : peuple `publication_relations`, qui relie des publications apparentées (preprint ↔ version publiée, supplément ↔ article, chapitre ↔ ouvrage, erratum ↔ article corrigé…).
- [Sujets](10-enrichissements.md#sujets-subjects) : ingestion des sujets des `source_publications` vers les référentiels `subjects` et `publication_subjects`, puis recalcul de `subjects.usage_count` et de la table `subject_cooccurrences` (paires de sujets co-présents sur une même publication).
- [Pays](10-enrichissements.md#pays-des-adresses-countries) : détection automatisée des pays des adresses. Sert à interroger les collaborations internationales.
- [Statut open access](10-enrichissements.md#statut-open-access-oa_status) : interroge Unpaywall pour obtenir le statut OA à jour des publications.
