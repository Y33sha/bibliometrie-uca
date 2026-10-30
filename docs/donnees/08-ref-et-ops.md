# Référentiels externes et exploitation

*À jour le 2026-10-26.*

## Référentiels externes

Schéma PostgreSQL `ref`.

| Table | Contenu | Écrit par |
|---|---|---|
| `countries` | Pays | `infrastructure/db/seed.sql` |
| `place_name_forms` | Noms de pays, d'institutions et de villes, avec le pays désigné | `infrastructure/db/seed.sql` |
| `languages` | Langues, avec leur code ISO 639-1, à défaut ISO 639-3, et leur nom français | `infrastructure/db/seed.sql` |
| `language_forms` | Formes sous lesquelles les sources désignent une langue : codes à deux et trois lettres, nom anglais | `infrastructure/db/seed.sql` |
| `ror_organizations` | Organisations du Research Organization Registry. `structures.ror_id` les relie aux structures | `interfaces/cli/imports/import_ror_dump.py` |
| `ror_relations` | Relations parent-enfant entre organisations ROR | `interfaces/cli/imports/import_ror_dump.py` |
| `ror_dump_imports` | Imports du fichier ROR, avec leur date | `interfaces/cli/imports/import_ror_dump.py` |
| `hal_structures` | Structures du référentiel HAL citées par les contributions sources | phase [`affiliations`](../pipeline/04-affiliations.md) |
| `hal_structure_relations` | Relations parent-enfant entre structures HAL | phase `affiliations` |
| `hal_structure_aliases` | Fiches en double du référentiel HAL, avec la structure conservée | phase `affiliations` |

## Exploitation

Schéma PostgreSQL `ops`.

| Table | Contenu | Écrit par |
|---|---|---|
| `config` | Réglages du pipeline : périmètres en service, années couvertes… | administration (`application/services/config.py`) |
| `audit_log` | Journal des actions d'administration et des fusions | administration |
| `pipeline_phase_executions` | Historique d'exécution des phases | pipeline |
| `users` | Utilisateurs autorisés à ouvrir une session | `interfaces/cli/maintenance/manage_users.py`. L'API crée `ADMIN_USER` au démarrage |
| `roles` | Rôles connus du code (`domain.users.Role`) | migrations |
| `user_roles` | Rôles attribués à chaque utilisateur | `interfaces/cli/maintenance/manage_users.py` |

## Schéma `public`

| Table | Contenu |
|---|---|
| `merge_redirects` | Identifiant d'une personne, publication, publication en série, monographie ou éditeur absorbé par une fusion, et identifiant de l'entité conservée |
| `alembic_version` | Révision du schéma appliquée |

Le schéma `public` contient aussi les types énumérés et les extensions.
