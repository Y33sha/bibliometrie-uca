# Enregistrements sources

*À jour le 2026-10-28.*

Un enregistrement source est la description d'un document par une source : HAL, OpenAlex, Web of Science, ScanR, theses.fr, Crossref ou DataCite. Une contribution source est un auteur tel que la source le donne dans un enregistrement source. Ces tables conservent ce que dit chaque source, avant tout regroupement. Toutes les sources partagent les mêmes tables, et la colonne `source` les distingue.

Seul le pipeline écrit ces tables. Une métadonnée fausse se corrige par une règle de [correction](../pipeline/06-metadata-correction.md), qui garde la valeur d'origine.

## Tables

Schéma PostgreSQL `sources`.

**Moissonnage**

| Table | Contenu | Contrainte |
|---|---|---|
| `staging` | Document moissonné : identifiant dans la source, payload brut, empreinte (`raw_hash`), date de disparition de la source (`disappeared_at`). Le payload est vidé après la normalisation | Un document par source et identifiant |
| `failed_lookups` | Identifiant (DOI, identifiant HAL, NNT) cherché en vain dans une source ou auprès de doi.org, avec la date de l'échec | |
| `unpaywall` | Statut d'accès que donne Unpaywall pour un DOI, avec la date de l'interrogation | Un statut par DOI |

**Enregistrements sources**

| Table | Contenu | Contrainte |
|---|---|---|
| `source_records` | Métadonnées typées : titre, type de document, année, DOI, identifiants externes, revue, éditeur, statut d'accès, langue. Champs propres à certaines sources : résumé, mots-clés, thématiques, données bibliographiques, collections HAL, embargo, rétractation. `raw_doc_type` et `raw_language` : valeurs dans le vocabulaire de la source. `corrections` : valeurs d'origine des métadonnées corrigées. `is_matchable` : faux pour un enregistrement source écarté de la réconciliation. `publication_id` : publication de rattachement | Un enregistrement source par source et identifiant |
| `source_record_locations` | Copies du document : URL de la page et du PDF, identifiant OAI-PMH, version, licence, open access, [plateforme](07-publishing.md) | Une copie par URL |

**Contributions sources**

| Table | Contenu | Contrainte |
|---|---|---|
| `source_contributions` | Position, rôles, auteur correspondant, nom brut. `collective` : collaboration, consortium ou groupe d'étude. `duplicate_of` : doublon d'un autre auteur de la liste. `neutralized_identifiers` : identifiants que la résolution des personnes ignore pour cette contribution source, avec leur motif. `perimeter_evidence`, `in_perimeter` : indices de périmètre. `countries` : pays | Une contribution source par position dans un enregistrement source |
| `contributor_information` | Nom normalisé et identifiants, partagés par les contributions sources qui ont les mêmes | Une ligne par combinaison de nom et d'identifiants |
| `source_contribution_addresses` | [Adresses](06-structures.md) de la contribution source | |
| `source_contribution_rors` | ROR attribués par la source, rattachés à l'adresse de leur affiliation quand elle a un texte | |
| `source_contribution_hal_structures` | Structures HAL attribuées par la source | |

**Vues**

| Vue | Contenu |
|---|---|
| `source_contribution_structures` | Vue matérialisée : structures du périmètre de chaque contribution source, avec l'indice ([données dérivées](09-donnees-derivees.md)) |
| `known_dois` | DOI des enregistrements sources, DOI liés, cibles des relations, DOI DataCite déduits des identifiants arXiv |
| `candidate_dois` | DOI connus des publications du périmètre, lus par le rattrapage par DOI et la résolution des agences d'enregistrement |

## Écriture

- Les phases de [moissonnage](../pipeline/02-harvest.md) écrivent `staging` et `failed_lookups`.
- La phase [`normalize`](../pipeline/03-normalize.md) crée et met à jour les enregistrements sources et leurs contributions sources à partir de `staging`.
- La phase [`metadata_correction`](../pipeline/06-metadata-correction.md) corrige les métadonnées typées des enregistrements sources.
- La phase [`affiliations`](../pipeline/04-affiliations.md) écrit les indices de périmètre des contributions sources.
- La phase [`publications`](../pipeline/07-publications.md) rattache chaque enregistrement source à sa publication.
- La phase [`author_grouping`](../pipeline/08-author-grouping.md) marque les doublons d'auteur.
- Les phases `normalize` et [`persons`](../pipeline/09-persons.md) neutralisent des identifiants.
- Les [enrichissements](../pipeline/11-enrichissements.md) écrivent les pays et `unpaywall`.
