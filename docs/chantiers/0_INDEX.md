# Roadmap des roadmaps

## Chantiers non archivés

### En cours

- [Types de documents : enum, mappings, règles suspects](METIER_doc-types.md)
- [Stratégie de tests : dé-fictionnaliser, factoriser, parcimonie](CODE_strategie-tests.md) — Problèmes 2 (mocks) et 3 (parcimonie) clôturés ; reste la dé-fictionnalisation du helper (problème 1 + périmètre tests pipeline)

### En pause

- [Matching cross-source des authorships](METIER_authorships-cross-source-matching.md)
- [Observabilité et robustesse du pipeline](CODE_observabilite-robustesse-pipeline.md)
- [DOI Registration Agencies & DataCite](METIER_doi-ra-datacite.md)
- [Qualité et cohérence des sujets](METIER_sujets-qualite.md)

### Non commencé

- [Background jobs pour les endpoints longs](CODE_background-jobs.md)
- [Relations entre publications](METIER_relations-publications.md)

## Chantiers archivés

- 2026-06-04 — [Matérialiser le périmètre (`perimeter_structures`) — audit `in_perimeter` : conservé](archived/2026-06-04_DATA_perimeter-materialise.md)
- 2026-06-04 — [Rejet durable d'une paire (publication, personne) : garde matching, détachement, réassignation](archived/2026-06-04_METIER_detachement-rejet-durable.md)
- 2026-06-03 — [Données dérivées : audit + cadre de décision (matérialisation vs vue)](DATA_donnees-derivees.md)
- 2026-06-03 — [Normalize : batcher l'insertion des authorships](CODE_batcher-normalize-authorships.md)
- 2026-06-02 — [Authorships : build source-agnostique en une passe convergente](archived/2026-06-02_CODE_simplifier-build-authorships.md)
- 2026-06-01 — [Sidecar `rejected_authorships` (extraire `authorships.excluded`)](archived/2026-06-01_DATA_rejected-authorships-sidecar.md)
- 2026-05-31 — [Stockage des données brutes (raw store)](archived/2026-05-31_DATA_raw-data-store.md)
- 2026-05-31 — [Cycle de vie des rows `staging` : machine à états, backoff, fraîcheur](archived/2026-05-31_DATA_cycle-vie-staging.md)
- 2026-05-30 — [Exploitation de l'API CrossRef](archived/2026-05-30_METIER_crossref.md)
- 2026-05-30 — [Cascade unifiée de matching personnes (`decide_person_match`)](archived/2026-05-30_METIER_decide-person-match.md)
- 2026-05-29 — [Publishers & Journals : typage, pipeline, cohérence, UI](archived/2026-05-29_METIER_publishers-journals.md)
- 2026-05-29 — [Dérive `pub_meta` des normalizers](archived/2026-05-29_CODE_normalizers-pub-meta-drift.md)
- 2026-05-28 — [Correction des métadonnées canoniques](archived/2026-05-28_METIER_metadata-correction.md)
- 2026-05-28 — [Déduplication des publications par métadonnées](archived/2026-05-28_METIER_metadata-deduplication.md)
- 2026-05-26 — [Pipeline : phase `publishers_journals` (référentiels enrichis)](archived/2026-05-26_METIER_pipeline-publishers-journals.md)
- 2026-05-23 — [Documentation HTML précompilée avec sommaire scrollable](archived/2026-05-23_CODE_doc-statique-prerender.md)
- 2026-05-21 — [Parallélisation des extractions HTTP pipeline](archived/2026-05-21_CODE_async-extractions-http.md)
- 2026-05-21 — [Repositories → use cases (orchestration en application)](archived/2026-05-21_CODE_repositories-vers-use-cases.md)
- 2026-05-18 — [Couverture de tests : viser 80 %](archived/2026-05-18_CODE_couverture-tests.md)
- 2026-05-18 — [Typage strict des projections et DTOs](archived/2026-05-18_CODE_typage-projections-strict.md)
- 2026-05-17 — [Audit « DSI qui reprend le projet »](archived/2026-05-17_CODE_audit-cto.md)
- 2026-05-16 — [Normaliser les relations many-to-many cachées (arrays + JSONB de jointure)](archived/2026-05-16_DATA_jointures-many-to-many.md)
- 2026-05-15 — [Domaine riche (entités métier)](archived/2026-05-15_CODE_rich-domain-model.md)
- 2026-05-15 — [Chasse aux `Any`](archived/2026-05-15_CODE_chasse-aux-any.md)
- 2026-05-14 — [Séparer le matching de la normalisation](archived/2026-05-14_DATA_separer-matching-normalisation.md)
- 2026-05-14 — [Rationalisation du matching/fusion de publications](archived/2026-05-14_CODE_deduplication-fusion-publications.md)

- 2026-05-13 — [Normalisation du schéma `person_name_forms`](archived/2026-05-13_DATA_person-name-forms-normalisation.md)

  La table `person_name_forms` stocke les formes de nom normalisées, avec une colonne `person_ids` (personnes liées) et une colonne `sources` (sources où la forme de nom a été observée). Les deux ne sont pas corrélés: on ne sait pas de quelle source vient chaque forme pour chaque personne. Problème résolu en remplaçant les deux colonnes par une colonne JSONB `persons` au format `{ "<person_id>": ["src1", "src2"], ... }`.

  *NB*. Ultérieurement, choix révisé: colonnes `person_id` INT (FK) et `sources` TEXT[]. Permet d'avoir une contrainte FK.

- 2026-05-13 — [Simplification des tables sources](archived/2026-05-13_DATA_simplify-source-tables.md)

- 2026-05-12 — [Pureté du domain/](archived/2026-05-12_CODE_purete-domain.md)

  Des fichiers du `domain/` importaient `pydantic` pour modéliser des colonnes JSONB qui sont en réalité de l'I/O, pas du métier. Déplacement des `BaseModel` vers `infrastructure/db/jsonb_models/`. Interdiction des imports de bibliothèques tierces par `domain/`, verrouillée par `import-linter`.

- 2026-05-11 — [Suppression des `conn`/`cur` fossiles](archived/2026-05-11c_CODE_conn-cur-fossiles.md)

  Nettoyage post-migration SQLAlchemy. De nombreuses fonctions déclarent un argument `conn: Connection` ou `cur: Connection` qu'elles n'utilisent pas. Vestige du pattern psycopg où le curseur servait à `cur.execute(...)` directement.

- 2026-05-11 — [Adoption d'Alembic](archived/2026-05-11b_CODE_alembic-adoption.md)

  Remplacement du système maison (`infrastructure/db/migrate.py`) par Alembic pour la gestion des migrations.

- 2026-05-11 — [Adoption SQLAlchemy Core](archived/2026-05-11a_CODE_sqlalchemy-core-adoption.md)

  Adoption de SQLAlchemy Core (pas l'ORM) comme *query builder* de référence pour les queries dynamiques, en coexistence pragmatique avec du SQL brut là où c'est plus lisible (CTE complexes, opérations JSON spécifiques à PostgreSQL).

- 2026-05-09 — [Convergence sync/async (suppression de la duplication)](archived/2026-05-09_CODE_sync-async-deduplication.md)

  Deux familles de repositories quasi identiques : *sync* (utilisées par le pipeline et les CLI) et *async* (utilisées par les routes FastAPI). Déduplication et passage en *sync* partout. Les routes `def` sont exécutées dans un threadpool Starlette (~40 workers par défaut).

- 2026-05-08 — [Formalisation des règles métier dans `domain/`](archived/2026-05-08_CODE_regles-metier-domain.md)

  Exploration de la codebase pour retrouver des invariants métier implicites dispersés dans `application/` et les rapatrier dans `domain/`.

- 2026-05-06 — [Inversion de dépendance dans les routers](archived/2026-05-06_CODE_routers-di.md)

  18 routers sur 20 importaient depuis `/infrastructure`, malgré l'interdiction documentée mais non enforcée. Mise en conformité et règle verrouillée par `import-linter`.

- 2026-05-05 — [DRY publications tables](archived/2026-05-05_CODE_dry-publications-tables.md)

  Le composant `<PublicationsListView>` sert désormais pour 4 pages partageant le même tableau de publications avec filtres à facettes.

- 2026-04-30 — [Sujets / mots-clés](archived/2026-04-30_METIER_sujets-mots-cles.md)

  Les sujets et mots-clés étaient stockés dans `source_publications`mais pas exploités. Création des tables `subjects` et `subject_cooccurrences`. Création de la page sujets, création du nuage de mots dans les dashboards personne et labo.

- 2026-04-28 — [Repenser `source_persons`](archived/2026-04-28_DATA_source-persons.md)

  Clarification du rôle de la table `source_persons`. Elle était peuplée pour toutes les sources, y compris celles sans identité auteur stable (OA, WoS, auteurs HAL sans compte) avec des `source_id` synthétiques, impossibles à mapper utilement aux `persons` réelles. Le chantier restreint cette table aux sources avec identifiant stable (HAL avec`personId`, ScanR et theses.fr avec `idref`).

  *NB*. Le chantier **DATA_simplify-source-tables** va plus loin dans la simplification du schéma en supprimant `source_persons` et `source_structures`.
