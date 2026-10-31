# Publications

*À jour le 2026-10-28.*

Une publication est la référence unifiée d'un document. Elle réunit les enregistrements sources qui décrivent ce document, quelle que soit leur source. Les jeux de données, les logiciels et les thèses sont aussi des publications. Le pipeline calcule chaque publication à partir de ses enregistrements sources.

Une publication a au moins un enregistrement source, un type de document retenu (les évaluations d'articles, les thèses d'exercice, les mémoires d'étudiants et les objets physiques sont exclus) et une contribution rattachée à une personne. Le pipeline supprime les autres. Les enregistrements sources écartés de la réconciliation (`is_matchable`) restent hors des publications.

## Tables

Schéma PostgreSQL `publications`.

| Table | Contenu | Contrainte |
|---|---|---|
| `publications` | Métadonnées consolidées : titre, type de document, date de publication avec sa précision, DOI, statut d'accès, licences, langue, pays, publication en série, monographie, éditeur. `publication_year` : année de la date de publication (colonne générée). `sources` : sources qui décrivent la publication. `publisher_id` : éditeur à la date de publication. `best_copy_url` : lien vers le texte intégral. `in_perimeter` : vrai pour au moins un indice de périmètre | Un DOI par publication, sans distinction de casse |
| `publications_detail` | Résumé, mots-clés, thématiques et données bibliographiques | Une ligne par publication |
| `publication_relations` | Lien orienté d'une publication vers une publication apparentée ou vers un DOI, avec le type de relation et sa source | La cible est une publication ou un DOI |
| `manual_merges`, `manual_merge_source_records` | Fusions de publications décidées par l'administration, avec leurs enregistrements sources : la réconciliation les réunit dans une même publication | |

Les frais de publication (`apc_payments`) sont décrits avec l'[édition](07-publishing.md).

## Sujets

Un sujet est un terme d'un vocabulaire contrôlé : domaine HAL, discipline de thèse, vedette RAMEAU, topic OpenAlex, catégorie du Web of Science. Les mots-clés libres restent sur l'enregistrement source.

| Table | Contenu | Contrainte |
|---|---|---|
| `subjects` | Libellé, langue, nombre de publications (`usage_count`) | Un sujet par libellé, sans distinction de casse |
| `publication_subjects` | Lien entre une publication et un sujet, avec la source qui le fournit | Un lien par publication, sujet et source |
| `subject_cooccurrences` | Vue matérialisée : paires de sujets présents ensemble sur au moins deux publications | |

`publication_subjects.rejected` exclut un lien des décomptes et le conserve aux recalculs.

## Écriture

Une métadonnée fausse se corrige par une règle de [correction](../pipeline/06-metadata-correction.md) sur l'enregistrement source.

**Administration** (`application/services/publication_merge.py`) : fusion manuelle de deux publications (`manual_merges`), respectée par la réconciliation.

**Pipeline :**

- La phase [`publications`](../pipeline/07-publications.md) regroupe les enregistrements sources en publications, puis recalcule les métadonnées de chaque publication touchée. Une publication réunie à une autre est supprimée : son identifiant redirige vers la publication conservée.
- La phase [`finalize`](../pipeline/10-finalize.md) reporte le périmètre sur les publications et supprime les publications sans contribution rattachée.
- Les [enrichissements](../pipeline/11-enrichissements.md) écrivent les relations, les sujets, les pays et le statut d'accès.
