# Roadmap des roadmaps

## Chantiers non archivés

### En cours

- [Lisibilité](CODE_lisibilite.md)

### En pause

- [Gestion et dédoublonnage assistés de la base personnes](DATA_personnes-dedoublonnage-assiste.md)

### Non commencé

- [Qualité et cohérence des sujets](METIER_sujets-qualite.md)
- [Signatures institutionnelles](METIER_signatures-institutionnelles.md)

## Chantiers archivés

- 2026-07-19 — [Projections de lecture des personnes : deux endpoints pour une entité](archived/2026-07-19_CODE_projections-de-lecture-des-personnes.md)
- 2026-07-19 — [Structures et laboratoires : une entité, deux piles de lecture](archived/2026-07-19_CODE_structures-et-laboratoires.md)
- 2026-07-19 — [Typage des paramètres de requête : ce que `str` ne dit pas](archived/2026-07-19_CODE_typage-des-parametres-de-requete.md)
- 2026-07-18 — [Routes API par ressource : supprimer le dossier `admin`](archived/2026-07-18_CODE_routes-par-ressource.md)
- 2026-07-18 — [Les liens adresse ↔ site ne s'écrivent pas en base](archived/2026-07-18_DATA_liens-adresse-site-non-persistes.md)
- 2026-07-17 — [Exceptions : démêler les `HTTPException` des routers](archived/2026-07-17_CODE_exceptions-des-routers.md)
- 2026-07-17 — [Périmètre APC : le résoudre dans l'adapter au lieu de le faire descendre du router](archived/2026-07-17_CODE_apc-perimetre-au-router.md)
- 2026-07-17 — [Domaines HAL : libellés depuis la source, suppression de la table](archived/2026-07-17_CODE_hal-domaines-libelles.md)
- 2026-07-17 — [Normalize : factoriser l'upsert des `source_publications`](archived/2026-07-17_CODE_normalize-upsert-source-publications.md)
- 2026-07-12 — [Phase personnes — lisibilité et refonte](archived/2026-07-12_CODE_phase-persons.md)
- 2026-07-12 — [Simplification de la phase sujets](archived/2026-07-12_CODE_simplification-sujets.md)
- 2026-07-12 — [Fusion des publications — dénouer l'enchevêtrement](archived/2026-07-12_CODE_merge-publications.md)
- 2026-07-11 — [Countries : caches pays intermédiaires](archived/2026-07-11_CODE_countries-caches-intermediaires.md)
- 2026-07-10 — [run_pipeline : réduire à la coquille CLI](archived/2026-07-10_CODE_run-pipeline-coquille-cli.md)
- 2026-07-09 — [Hors périmètre : ne pas matérialiser plutôt que masquer](archived/2026-07-09_DATA_hors-perimetre-non-materialise.md)
- 2026-07-08 — [Personnes : résolution d'identité ordre-indépendante](archived/2026-07-08_DATA_persons-cascade-ordre-independante.md)
- 2026-07-08 — [Supprimer le dossier `interfaces/cli/pipeline/`](archived/2026-07-08_CODE_supprimer-cli-pipeline.md)
- 2026-07-03 — [Scinder `source_authorships` (identité ⊥ liaison)](archived/2026-07-03_DATA_scinder-source-authorships.md)
- 2026-07-02 — [Refresh stale par identifiants natifs](archived/2026-07-02_DATA_refresh-stale-identifiants-natifs.md)
- 2026-07-01 — [Skip propre des sources d'API tierces non configurées](archived/2026-07-01_CODE_extract-sources-non-configurees.md)
- 2026-07-01 — [Observabilité du pipeline](archived/2026-07-01_CODE_observabilite-pipeline.md)
- 2026-06-30 — [Brancher le domaine riche orphelin](archived/2026-06-30_CODE_domaine-riche-orphelin.md)
- 2026-06-29 — [Déduire le journal_id manquant par préfixe DOI](archived/2026-06-29_DATA_journal-id-par-doi-prefix.md)
- 2026-06-28 — [Visualisations dynamiques (pivot listes ↔ tableaux de bord)](archived/2026-06-28_METIER_visualisations-pivot.md)
- 2026-06-26 — [Relations entre publications](archived/2026-06-26_METIER_relations-publications.md)
- 2026-06-26 — [Déduplication des publications sans identifiant fiable (arête pairwise-gated)](archived/2026-06-26_DATA_dedup-pairwise-gated.md)
- 2026-06-25 — [Écritures API : frontière transactionnelle (commit avant réponse)](archived/2026-06-25_CODE_commit-avant-reponse.md)
- 2026-06-25 — [Résolution de la RA en amont de cross_imports](archived/2026-06-25_CODE_resolve-ra-amont.md)
- 2026-06-22 — [Identifiants partagés entre signatures (corruption source) : généraliser le `_dubious`](archived/2026-06-22_DATA_identifiants-partages-dubious.md)
- 2026-06-20 — [DOI Registration Agencies & DataCite](archived/2026-06-20_METIER_doi-ra-datacite.md)
- 2026-06-20 — [Extraction HAL : requête unique multi-collections](archived/2026-06-20_CODE_hal-extract-mono-requete.md)
- 2026-06-20 — [Embargo HAL : statut OA intermédiaire « sous embargo »](archived/2026-06-20_METIER_embargo-oa-status.md)
- 2026-06-19 — [Types de documents : enum, mappings, règles suspects](archived/2026-06-19_METIER_doc-types.md)
- 2026-06-19 — [Matching cross-source des authorships](archived/2026-06-19_DATA_authorships-cross-source-matching.md)
- 2026-06-19 — [Adresses → pays : détection, suggestion et performances de la cascade](archived/2026-06-19_DATA_addresses-countries.md)
- 2026-06-16 — [Publications : retour à match_or_create, corrections a priori, fusion réparatrice](archived/2026-06-16_DATA_publications-match-or-create.md)
- 2026-06-14 — [Performance du pipeline (phase par phase)](archived/2026-06-14_CODE_perf-pipeline.md)
- 2026-06-13 — [Performance des pages de listes (UI)](archived/2026-06-13_DATA_perf-pages-listes.md)
- 2026-06-11 — [Publications : matching par création⇒fusion + modélisation des identifiants](archived/2026-06-11_DATA_publications-creation-fusion.md)
- 2026-06-11 — [Fusions abusives de documents distincts par les sources](archived/2026-06-11_METIER_fusions-abusives-sources.md)
- 2026-06-09 — [Complétude des identifiants externes & clés de déduplication](archived/2026-06-09_METIER_completude-identifiants.md)
- 2026-06-08 — [Export CSV fidèle à l'affichage (filtres + colonnes + titres nettoyés)](archived/2026-06-08_CODE_export-csv-fidele.md)
- 2026-06-08 — [Peaufinage UI (cohérence, responsivité, ergonomie)](archived/2026-06-08_CODE_peaufinage-ui.md)
- 2026-06-07 — [Barres à facettes homogènes + extraction des ListView (thèses, personnes) + alignement endpoint personnes](archived/2026-06-07_CODE_listviews-facettes-homogenes.md)
- 2026-06-07 — [Filtres composables pour le repérage des adresses (admin)](archived/2026-06-07_CODE_filtres-adresses-composables.md)
- 2026-06-06 — [Background jobs pour les endpoints longs : matview pipeline-only, garde-fou batch_set_country, propagation des reviews en tâche de fond](archived/2026-06-06_CODE_background-jobs.md)
- 2026-06-05 — [Stratégie de tests : dé-fictionnaliser, factoriser, parcimonie](archived/2026-06-05_CODE_strategie-tests.md)
- 2026-06-04 — [Matérialiser le périmètre (`perimeter_structures`) — audit `in_perimeter` : conservé](archived/2026-06-04_DATA_perimeter-materialise.md)
- 2026-06-04 — [Rejet durable d'une paire (publication, personne) : garde matching, détachement, réassignation](archived/2026-06-04_METIER_detachement-rejet-durable.md)
- 2026-06-03 — [Zenodo : dédup concept/version en matching, pas en normalize](archived/2026-06-03_METIER_zenodo-concept-version.md)
- 2026-06-03 — [Données dérivées : audit + cadre de décision (matérialisation vs vue)](archived/2026-06-03_DATA_donnees-derivees.md)
- 2026-06-03 — [Normalize : batcher l'insertion des authorships](archived/2026-06-03_CODE_batcher-normalize-authorships.md)
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
