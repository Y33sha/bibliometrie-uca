# Enregistrements sources

*À jour le 2026-10-30.*

Un enregistrement source est la description d'un document par une source : HAL, OpenAlex, Web of Science, ScanR, theses.fr, Crossref ou DataCite. Une contribution source est une personne nommée par la source dans un enregistrement source, avec son rôle. Ces tables conservent les données de chaque source, avant tout regroupement. Toutes les sources partagent les mêmes tables, et la colonne `source` les distingue.

Seul le pipeline écrit ces tables. Une métadonnée fausse se corrige par une règle de [correction](../pipeline/06-metadata-correction.md), qui garde la valeur d'origine.

## Tables

Schéma PostgreSQL `sources`.

**Moissonnage**

| Table | Contenu | Contrainte |
|---|---|---|
| `staging` | Document moissonné : identifiant dans la source, payload brut, empreinte (`raw_hash`), date de disparition de la source (`disappeared_at`). Le payload est vidé après la normalisation | Un document par source et identifiant |
| `failed_lookups` | Identifiant (DOI, identifiant HAL, NNT) cherché en vain dans une source ou auprès de doi.org, avec la date de l'échec | |

**DOI**

| Table | Contenu | Contrainte |
|---|---|---|
| `dois` | Statut d'accès donné par Unpaywall, URL de résolution chez doi.org, chacun avec la date de l'interrogation | Une ligne par DOI de publication |

**Enregistrements sources**

| Table | Contenu | Contrainte |
|---|---|---|
| `source_records` | Métadonnées typées : titre, type de document, date de publication avec sa précision (année, mois ou jour), revue, éditeur, langue. Champs propres à certaines sources : résumé, mots-clés, thématiques, données bibliographiques, collections HAL, rétractation. `raw_doc_type` et `raw_language` : valeurs dans le vocabulaire de la source. `corrections` : valeurs d'origine des métadonnées corrigées. `is_matchable` : faux pour un enregistrement source écarté de la réconciliation. `publication_id` : publication de rattachement | Un enregistrement source par source et identifiant |
| `source_record_identifiers` | Identifiants d'un enregistrement source, DOI compris : type, valeur, rôle (primaire, dérivé, secondaire ou lié). `removed_by` : règle de correction qui retire l'identifiant | Un identifiant par type et valeur, au plus un identifiant dérivé |
| `source_record_locations` | Copies du document : URL de la page et du PDF, identifiant OAI-PMH, version, licence, open access, [plateforme](07-publishing.md). Les pages qui décrivent le document sans en donner le texte (DOAJ, DOAB, PubMed) sont écartées. L'URL d'une copie HAL est l'adresse de son dépôt, `https://hal.science/<identifiant sans version>` (portail DUMAS pour un mémoire DUMAS), quel que soit le portail donné par la source | Une copie par URL |
| `embargoes` | Embargo déclaré par un enregistrement source : date de fin du fichier déposé dans HAL, ou embargo sans date d'une thèse de theses.fr. Sous embargo actif, le fichier déposé est fermé | Un embargo par enregistrement source |
| `doi_targets` | Cible du DOI d'une forme secondaire de la même œuvre (version, variante), qui tient lieu du DOI pour la réconciliation | Une cible par DOI |

**Contributions sources**

| Table | Contenu | Contrainte |
|---|---|---|
| `source_contributions` | Position, rôles, auteur correspondant, nom brut. `collective` : collaboration, consortium ou groupe d'étude. `duplicate_of` : doublon d'un autre auteur de la liste. `neutralized_identifiers` : identifiants ignorés par la résolution des personnes pour cette contribution source, avec leur motif. `perimeter_evidence`, `in_perimeter` : indices de périmètre. `countries` : pays | Une contribution source par position dans un enregistrement source |
| `contributor_information` | Nom normalisé et identifiants, partagés par les contributions sources qui ont les mêmes | Une ligne par combinaison de nom et d'identifiants |
| `source_contribution_addresses` | [Adresses](06-structures.md) de la contribution source | |
| `source_contribution_rors` | ROR attribués par la source, rattachés à l'adresse de leur affiliation quand elle a un texte | |
| `source_contribution_hal_structures` | Structures HAL attribuées par la source | |

**Vues**

| Vue | Contenu |
|---|---|
| `source_contribution_structures` | Vue matérialisée : structures du périmètre de chaque contribution source, avec l'indice ([données dérivées](09-donnees-derivees.md)) |
| `known_dois` | DOI actifs des enregistrements sources, cibles des relations, DOI DataCite déduits des identifiants arXiv |
| `candidate_dois` | DOI connus des publications du périmètre, lus par le rattrapage par DOI et la résolution des agences d'enregistrement |

## Écriture

- Les phases de [moissonnage](../pipeline/02-harvest.md) écrivent `staging` et `failed_lookups`.
- La phase [`normalize`](../pipeline/03-normalize.md) crée et met à jour les enregistrements sources et leurs contributions sources à partir de `staging`.
- La phase [`metadata_correction`](../pipeline/06-metadata-correction.md) corrige les métadonnées typées des enregistrements sources et calcule `doi_targets`.
- La phase [`affiliations`](../pipeline/04-affiliations.md) écrit les indices de périmètre des contributions sources.
- La phase [`publications`](../pipeline/07-publications.md) rattache chaque enregistrement source à sa publication.
- La phase [`author_grouping`](../pipeline/08-author-grouping.md) marque les doublons d'auteur.
- Les phases `normalize` et [`persons`](../pipeline/09-persons.md) neutralisent des identifiants.
- Les [enrichissements](../pipeline/11-enrichissements.md) écrivent les pays et `dois`.
