# Journals — cycle de vie

*À jour le 2026-09-04.*

Un `journal` est un support de publication : revue, conférence, dépôt ou autre. Près de deux revues sur cinq n'ont aucun ISSN, et autant arrivent des sources sous plusieurs titres — d'où `journal_name_forms`, qui collecte ces formes pour reconnaître une revue déjà enregistrée. `domain/journals/journal.py` en décrit la structure sans logique : le rapprochement, la fusion et l'enrichissement vivent dans les services et leurs adaptateurs SQL.

## Tables

| Table | Rôle | Colonnes notables |
|---|---|---|
| `journals` | La revue | `title` / `title_normalized`, `issn` / `eissn` / `issnl`, `publisher_id`, `openalex_id` (unique), `journal_type`, `oa_model`, `is_in_doaj`, `apc_amount` / `apc_currency`, `doaj_payload`, `pub_count` |
| `journal_name_forms` | Formes de nom permettant de reconnaître une revue par son titre | `journal_id`, `form_normalized`, `publisher_id`, unicité `(form_normalized, publisher_id)` |

Trois tables extérieures référencent une revue, avec des politiques de suppression différentes : `journal_name_forms` disparaît avec elle, `apc_payments.journal_id` repasse à nul, tandis que `publications.journal_id` et `source_publications.journal_id` n'autorisent aucune suppression tant qu'ils pointent dessus.

## Écriture par le pipeline

**Création et rapprochement (`normalize`).** Les six normaliseurs appellent `find_or_create_journal` (`application/services/journals/core.py`), qui essaie successivement l'`openalex_id`, puis les ISSN sous leurs trois formes (`find_journal_by_issn_any`), puis le titre (`find_journal_by_name_form`, qui préfère les revues portant un eISSN), et crée la revue en dernier recours avec sa forme de nom. `enrich_journal` complète au passage les champs vides, sans jamais écraser une valeur existante. La publication reçoit son `journal_id` par `extract_pub_metadata`. `normalize_openalex` déduit en outre l'`oa_model` du caractère ouvert de la source.

**Rattachement tardif par préfixe de DOI (`metadata_correction`).** `journal_by_doi.py` renseigne `source_publications.journal_id` lorsqu'un préfixe de DOI désigne une revue sans ambiguïté. La décision elle-même est prise dans `domain/source_publications/metadata_correction/journal_by_doi.py`.

**Enrichissement du référentiel (`publishers_journals`).** L'orchestrateur enchaîne, selon ce que la configuration autorise, la résolution des éditeurs, l'enrichissement depuis OpenAlex — frais de publication et type de revue pour celles restées indéterminées — puis l'import du référentiel DOAJ, qui renseigne `doaj_payload` et `is_in_doaj`. Les écritures passent par `PgJournalGatewayQueries` (`infrastructure/pipeline/journals.py`), qui porte aussi les requêtes de sélection de chaque sous-étape.

## Écriture par l'API — curation

Routeur `interfaces/api/routers/journals.py`, commandes dans `application/services/journals/commands.py`, adaptateur `PgJournalRepository`.

**Éditer une revue** (`PUT /api/journals/{id}`). Le dépôt re-dérive `title_normalized` à l'enregistrement. Si le type de revue change, `requalify_publications_for_journal` rejoue immédiatement le type de document de toutes ses publications et consigne un événement `journal.type_requalified`.

**Fusionner deux revues** (`POST /api/journals/{id}/merge`). `merge_journal_into` repointe successivement `publications`, `source_publications`, `apc_payments` et `journal_name_forms`, puis recale les compteurs de publications. Chaque table est traitée explicitement parce qu'aucune suppression en cascade ne peut faire le travail : la base refuse de supprimer une revue tant qu'une publication la référence.

**Prévisualiser un changement de type** (`GET /api/journals/{id}/type-change-impact`). Le chemin d'écriture réel est exécuté puis annulé, ce qui donne l'impact exact sans rien modifier.

## Lecture par le pipeline

**Compteur de publications.** `infrastructure/pipeline/authorships/pub_counts.py` recalcule `journals.pub_count`, puis celui des éditeurs. La phase `authorships` le recalcule en totalité, une fois le périmètre posé ; une fusion administrative ne recalcule que les revues concernées.

**Type de revue.** `refresh_from_sources` lit `get_journal_type` pour rejouer les règles de type de document qui en dépendent.

## Lecture par l'API

Port `application/ports/read_models/journals_queries.py`, adaptateur `PgJournalQueries`.

| Point d'entrée | Ce qu'il sert |
|---|---|
| `GET /api/journals`, `/facets` | Liste filtrable et facettes ; le filtre « avec publications » s'appuie sur le compteur `pub_count` |
| `GET /api/journals/{id}`, `/{id}/dashboard` | Détail de la revue ; le tableau de bord signale les publications hors du cadre annoncé par la revue (`domain/journals/expected.py`) et recompte l'appartenance au périmètre en direct |
| `GET /api/journals/types`, `/oa-models` | Libellés des vocabulaires de type de revue et de modèle d'accès ouvert, définis dans `domain/journals/journal.py` |

## Points d'attention

**La fusion écrit dans des tables d'autres agrégats.** `merge_journal_into` met à jour `publications`, `source_publications` et `apc_payments` en SQL littéral, hors du périmètre que le dépôt des revues déclare. L'opération demande une transaction unique, et repointer les dépendants en est le contenu même.

## Invariants métier

**Le type de document dépend du type de revue.** Le type canonique d'une publication se déduit en partie du type de sa revue. Deux chemins tiennent cette cohérence : la phase `metadata_correction`, qui recalcule tous les types de document en aval de `publishers_journals` et se rejoue sans dommage ; et `requalify_publications_for_journal`, appelé à l'édition d'une revue, qui requalifie ses publications sans attendre le passage suivant du pipeline.
