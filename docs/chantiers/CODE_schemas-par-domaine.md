# Chantier — Un schéma PostgreSQL par domaine

## Contexte

Toutes les tables sont dans le schéma `public`. La fiche [Architecture cible du pipeline](CODE_architecture-cible-pipeline.md) décide un schéma par domaine (question 3) : le découpage suit la lecture du modèle, et les droits pourront vérifier la catégorie d'une table là où elle est nette.

## Décisions

- **Rattachement des tables**
  - `sources` : `staging`, `source_publications`, `source_authorships`, `author_identifying_keys`, `source_authorship_addresses`, `source_authorship_rors`, `failed_lookups`, la vue `candidate_dois`, la vue matérialisée `source_authorship_structures`.
  - `publications` : `publications`, `publications_detail`, `authorships`, `publication_relations`, `publication_subjects`, `subjects`, les vues matérialisées `subject_cooccurrences`, `authorship_structures` et `publication_structures`.
  - `persons` : `persons`, `persons_rh`, `person_identifiers`, `person_name_forms`, `distinct_persons`, `rejected_authorships`, `confirmed_authorships`.
  - `publishing` : `journals`, `journal_issns`, `journal_name_forms`, `journal_doi_namespaces`, `publishers`, `publisher_name_forms`, `monographs`, `doi_prefixes`, `apc_payments`.
  - `structures` : `structures`, `structure_name_forms`, `structure_tutelles`, `perimeters`, `perimeter_structures`, `addresses`, `address_structures`.
  - `ref` : `countries`, `languages`, `language_forms`, `place_name_forms`, `ror_organizations`, `ror_relations`, `ror_dump_imports`.
  - `ops` : `config`, `audit_log`, `pipeline_phase_executions`.
- **Restent dans `public`** : les types énumérés, partagés entre domaines ; les extensions (`pg_trgm`, `unaccent`) ; `alembic_version`, qu'Alembic lit avant de jouer les migrations.
- **Une vue matérialisée rejoint la table qu'elle prolonge.**
- **Les requêtes ne qualifient pas les noms de table.** Le `search_path` de la base liste les schémas : le SQL existant reste valable, dans le code comme dans `psql`. `tables.py` déclare le schéma de chaque table.
- **Les migrations qualifient leurs tables.** Elles se connectent avec `public` pour seul `search_path`, pour qu'Alembic compare chaque table sous son schéma.

## Phasage

### Phase 1 — Migration

- [x] Migration Alembic : création des schémas, déplacement des tables et des vues, `search_path` de la base, `USAGE` et privilèges par défaut des rôles dans chaque schéma.
- [x] `tables.py` déclare le schéma de chaque table ; Alembic compare les schémas du projet.
- [x] `roles.sql` accorde les droits schéma par schéma.
- [x] `schema.sql` régénéré.

### Phase 2 — Code

- [ ] `pipeline/containers` devient `pipeline/publishing`.

### Phase 3 — Documentation

- [ ] `docs/donnees` : une page par schéma.

## Questions ouvertes

- Droits par catégorie : décisions et référentiels tenus à la main réservés à l'API.
