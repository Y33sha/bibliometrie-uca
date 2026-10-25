# Schémas `ref` et `ops`

*À jour le 2026-10-12.*

## `ref` : référentiels externes

- **`countries`** : référentiel des pays.
- **`place_name_forms`** : formes de noms pour la détection des pays.
- **`languages`** : référentiel des langues, avec leur code ISO 639-1, ou ISO 639-3 à défaut, et leur nom français.
- **`language_forms`** : formes sous lesquelles les sources désignent une langue, en minuscules : codes à deux et trois lettres, nom anglais.
- **`ror_organizations`** : organisations du Research Organization Registry, chargées depuis son dump. `structures.ror_id` les relie au référentiel interne.
- **`ror_relations`** : relations parent/enfant entre organisations ROR. `interfaces.cli.maintenance.report_ror_coherence` les compare à `structure_parents`.
- **`ror_dump_imports`** : imports du dump ROR, avec la date de chaque import.

## `ops` : exploitation

- **`config`** : réglages d'exploitation du pipeline (périmètres actifs, années couvertes…).
- **`audit_log`** : journal des événements (actions admin, fusions).
- **`pipeline_phase_executions`** : historique d'exécution des phases.

## Propriété des tables

| Table | Auteur | Écrit par |
|---|---|---|
| `countries`, `place_name_forms` | seed | `seed.sql` |
| `languages`, `language_forms` | seed | `seed.sql` |
| `config` | admin | `application/services/config/commands.py` |
