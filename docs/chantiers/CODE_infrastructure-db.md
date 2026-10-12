# Chantier — Le SQL métier partagé hors d'`infrastructure/db`

## Contexte

`infrastructure/db/` est un dossier bas niveau : connexion et transactions (`engine.py`, `transaction.py`), garde-fous d'exécution (`dml_guard.py`, `read_only_guard.py`), types et lecture des relevés (`jsonb.py`, `rows.py`, `scalars.py`), description du schéma (`tables.py`).

Trois modules y contiennent du SQL métier, partagé entre les repositories ou read models de l'API et le pipeline :

- `sql_fragments.py` : utilitaires génériques (`in_clause`, `case_priority`) et prédicats métier (identifiant neutralisé, paires rejetées, appartenance d'une authorship au périmètre, ISSN actifs, détenteurs d'une forme de nom). 27 modules l'importent.
- `journal_issns.py` : lecture des ISSN d'une revue sous forme de `JournalIssn`.
- `merge_steps.py` : mécanique des fusions de personnes, d'éditeurs et de revues, et condition « sans décision humaine ».

### Inventaire

| Fragment | Nature | Table visée | Côté API | Pipeline |
|---|---|---|---|---|
| `in_clause` | utilitaire | — | read models, repository des personnes | — |
| `case_priority` | utilitaire | — | repository des authorships | `publications` |
| `identifier_neutralized` | prédicat | `source_authorships` | read models, repository des personnes | `persons` |
| `usable_identifier` | prédicat | `source_authorships` | read models | `persons` |
| `signature_display_name` | prédicat | `source_authorships` | read models | — |
| `has_author_role` | prédicat | `source_authorships` | read models | — |
| `authorship_has_signature_from` | prédicat | `authorships` | read models | — |
| `AUTHORSHIP_IN_PERIMETER_EXPR` | prédicat | `authorships` | repository des authorships | `structures` |
| `REJECTED_PAIRS`, `publication_rejected_for` | prédicat | `rejected_authorships` | repository des authorships | `persons`, `publications` |
| `name_form_holder`, `other_name_form_holders` | prédicat | `person_name_forms` | read models | — |
| `active_issns`, `has_active_issn` | prédicat | `journal_issns` | read models | `publishing` |
| `journal_issns.py` | lecture d'une table | `journal_issns` | repository des revues | `publishing` |
| `merge_steps.py` | mécanique de fusion | — | fusions de personnes et d'éditeurs | fusion de revues |

`person_without_decision_sql`, déclarée dans le repository des personnes avec les étapes de leur fusion, sert aussi à la purge de la phase `persons` : le pipeline importe ce repository.

## Décisions

- **Fragments partagés entre l'API et le pipeline** : un module `infrastructure/sql_fragments.py`, avec les deux utilitaires. Une duplication ferait diverger les règles qu'ils encodent.
- **Fragments propres aux read models** : `infrastructure/read_models/sql_fragments.py`.
- **`journal_issns.py` et `merge_steps.py`** : dans `infrastructure/repositories/`. Le premier lit une table, le second sert aux fusions d'entités.
- **`person_without_decision_sql`** reste dans le repository des personnes : le pipeline a le droit d'importer les repositories.

## Phasage

### Phase 1 — Inventaire

- [x] Classer chaque fragment de `sql_fragments.py` : utilitaire générique, ou prédicat métier, avec son domaine et ses utilisateurs.

### Phase 2 — Déplacements

- [x] Fragments partagés vers `infrastructure/sql_fragments.py`, fragments des read models vers `infrastructure/read_models/sql_fragments.py`.
- [x] `journal_issns.py` et `merge_steps.py` vers `infrastructure/repositories/`.
- [x] Mise à jour de la documentation.
