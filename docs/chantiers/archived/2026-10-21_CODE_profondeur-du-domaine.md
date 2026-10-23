# Chantier — Règles du domaine complètes et uniques

## Contexte

Plusieurs règles métier sont découpées entre `domain/` et ses appelants. Le domaine expose des fragments ; le pipeline ou le SQL les assemble selon un ordre et des préconditions que seules les docstrings énoncent.

Règles assemblées par l'appelant :

- correction unaire d'un enregistrement source : `compute_update` (`pipeline/transformation/publications/correction/correct_unary.py`) enchaîne mapping, règles, type du dépôt HAL d'origine, retrait des clés de thèse et réapplication des retraits de la sous-étape cluster ;
- revue d'un enregistrement source par l'espace de noms de son DOI : la règle est dans `correction/journal_by_doi.py`, le domaine en garde une constante ;
- alignement des auteurs : `align_publication` (`domain/publications/author_grouping.py`) écrit dans les champs de `_SourceRecordLinks` après une séquence fixe d'étapes.

Connaissances écrites à plusieurs endroits :

- un prédicat de correction : la dataclass `MetadataForCorrection`, `_AppliesTo`, `_check_predicate`, `_SOURCE_ONLY_PREDICATES`, `UnaryCorrectionRow` et `for_correction()`, la requête `_SELECT`, les valeurs factices de `consolidation.py` ;
- les clés de configuration : `domain/config.py` (nature, validation), `infrastructure/db/tables.py` (CHECK), `pipeline/runtime/config.py` (littéraux, valeurs par défaut, recontrainte) ;
- la propriété des clés de `corrections` : chaque sous-étape de `metadata_correction` filtre ses clés à sa façon ;
- `CONVERGENCE_CASES`, re-listé dans `author_grouping/queries.py` ;
- « enregistrement ScanR issu de HAL », à quatre endroits, dont un `LIKE 'hal%'` sans validation de l'identifiant ;
- `source_extras ? 'conference'`, dans `metadata_correction_queries.py` et `type_proceedings_volumes.py` ;
- « prénom plein qui prolonge les initiales », à quatre endroits ;
- les seuils de comparaison des auteurs, dans `author_grouping.py` et `interfaces/cli/dev/estimate_residual_weights.py` ;
- les clés des JSON `source_extras` et `biblio` : écrites par `pipeline/ingestion/hal/payload.py`, lues par chaîne dans `domain/publications/conference.py` et `relations.py` ;
- le registre des dimensions de statistiques (`domain/stats.py`) et leur liaison SQL (`infrastructure/read_models/stats/pivot.py`), synchronisés par des `assert`.

Règles du domaine contournées :

- `reattribute_to` (`domain/persons/identifier_attribution.py`) réattribue seulement un identifiant `rejected` ; l'endpoint `PATCH /api/persons/identifiers/{id}/reassign`, sans appelant dans le frontend, réattribue depuis tout statut ;
- `allow_person_creation` (`domain/persons/creation.py`) décide sur la source `theses`. ScanR donne aussi les rôles de jury : 2 324 contributions sources ScanR dans le périmètre, à rôles de jury seuls, sur la base locale du 2026-10-20 ; aucune personne ne vient de ces seules contributions, 8 restent sans personne ;
- IdRef et idHAL sont normalisés seulement à l'écriture dans `person_identifiers` : HAL découpe l'IdRef à la main, ScanR le garde brut, et le matching compare une valeur brute à une valeur normalisée ;
- `map_doc_type` cherche une valeur absente de la table de sa source dans les tables des autres sources, dans l'ordre du dict ; une valeur inconnue devient `other` sans signal.

Classes d'identifiants : 15 value objects répètent `__post_init__`, `try_parse` et `__str__` (`publications/identifiers.py`, `persons/identifiers.py`, `structures/identifiers.py`), et `clean_doi`, `normalize_nnt`, `normalize_pmid`… appellent seulement leur `_normalize_*`.

## Décisions

- Une règle du domaine a une seule entrée publique, qui rend une décision complète. L'appelant lit les faits et écrit le résultat.
- Le verdict d'une règle se calcule en Python.
- Chaque fait a un seul propriétaire, qui le fournit au SQL comme au Python. Un fait que le SQL évalue sur des ensembles de lignes a un fragment unique dans `infrastructure/sql_fragments.py`.
- Un fait évalué en SQL et en Python a un test de parité.
- La projection SQL des faits que lisent les règles de correction se trouve à côté des règles. L'appelant demande la correction d'enregistrements sources, sans connaître les faits que lisent les règles.
- Un fait inconnu vaut `None`. Une règle qui lit un fait inconnu ne s'applique pas.
- `PERSON_SEARCH_IDENTIFIERS` et les listes de sources propres aux phases relèvent du chantier [Une source, un adaptateur](2026-10-23_CODE_adaptateur-par-source.md).
- La cascade de matching des personnes et le verdict d'une forme de nom relèvent du chantier [Résolution des personnes](../DATA_resolution-personnes.md).
- `normalize` traduit le type de document et la langue dans le vocabulaire du référentiel. `raw_doc_type` et `raw_language` gardent la valeur de la source. `corrections` garde seulement les corrections par une règle : pour `doc_type`, la valeur traduite avant correction.
- `application.ports` est la zone neutre de `infrastructure/` et du pipeline. `domain/config.py` reste dans le domaine : il définit les réglages et valide les valeurs saisies.

## Phasage

### Phase 1 — Personnes

- [x] `allow_person_creation` décidé sur les rôles. 49c40081a
- [x] Réattribution d'un identifiant seulement par l'agrégat : endpoint de réattribution retiré ; docstring de `AttributionStatus` alignée sur l'usage de l'admin.
- [x] Identifiants personne normalisés à l'ingestion par `compact_identifiers`. c309a275e
- [x] Prédicat « prénom plein qui prolonge les initiales » unique ; `author_grouping` lit `is_initials`. f5e86dfe4
- [x] IdRef normalisé sans ses blancs internes. 9a36b3b65

### Phase 2 — Correction des métadonnées

- [x] Colonnes `raw_doc_type` et `raw_language` ; type et langue traduits par `normalize` ; lecteurs de la valeur de la source branchés sur ces colonnes ; marqueurs `DOC_TYPE_MAP` et `LANGUAGE_MAP` retirés ; oneshot `split_raw_doc_type_language`. a543d6495
- [x] `map_doc_type` sans repli sur les autres sources ; valeurs inconnues journalisées. d473dd1b8
- [x] Règles des volumes Crossref sur la colonne `source_records.author_count` ; titre qui commence par un mot de volume sans condition d'auteurs. 70201133b
- [x] Colonne `raw_metadata` renommée `corrections`. e102ffc2f
- [x] Colonnes `meta` de `source_records` et `publications` renommées `source_extras` ; trace des corrections d'une publication dans `publications.corrections`. 3b584b73c
- [x] Faits des règles de correction optionnels ; `_SOURCE_ONLY_PREDICATES` et les valeurs factices de `consolidation.py` retirés ; fabrique `MetadataForCorrection.for_publication` ; prédicats d'égalité lus par nom de champ. d882da50e
- [x] Module propriétaire des clés de `source_extras` (`domain/source_records/source_extras.py`), fragments SQL dérivés ; les faits des règles lus dans `source_extras` en viennent. fddfe65f6
- [x] Clés de `biblio` et constructeur unique `compact_biblio`, appelé par les six normaliseurs. f3e31ae75
- [x] Projection SQL des faits des règles construite depuis les champs de `MetadataForCorrection`. fddfe65f6
- [x] Registre des clés de `corrections` et de leur sous-étape (`CorrectionKey`, `other_entries`). a1f18a42a
- [x] `correct_source_record` dans le domaine : valeurs corrigées et trace complète. a1f18a42a
- [x] Revue par espace de noms DOI en fonction de domaine (`attach_journal_by_doi`). 4491ae27a
- [x] Colonnes des mises à jour des corrections dérivées de `CorrectedSourceRecord` ; `correct_source_record` rend `None` sur un enregistrement source à jour ; colonne inconnue refusée. cf0cf2ab9, 05bba70ba
- [x] Pagination HAL et Crossref décomposée en `first_page` et `last_page` ; oneshot `split_biblio_pages` passé. 41c48358c

### Phase 3 — Doublons ponctuels

- [x] `CONVERGENCE_CASES` importé ; fragment SQL unique pour « ScanR issu de HAL », avec test de parité. e2fd36456
- [x] Seuils de comparaison des auteurs partagés avec `estimate_residual_weights.py`. 0262e76a2
- [x] `_SourceRecordLinks.resolve` ; `_Claim` en `NamedTuple` ; critères de création de publication en prédicats de `ReconcileMember`. b9526cc4f
- [x] Clés de confirmation : tokens dérivés des champs de `ConfirmationKeys`, identifiants normalisés par le registre de `external_ids`. 93b7c5964

### Phase 4 — Configuration et identifiants

- [x] Registre unique des clés de configuration (nom, nature, défaut), lecteur générique côté pipeline. 796a849bc
- [x] Base commune des value objects d'identifiants ; fonctions de normalisation passe-plats retirées. 8e7dd80f3

### Phase 5 — Documentation

- [x] Mise à jour de `docs/pipeline/` (`03-normalize.md`, `06-metadata-correction.md`, `08-persons.md`), `docs/agregats/`, `docs/donnees/02-sources.md`, `docs/sources/` (Crossref, DataCite, theses) ; noms `corrections` et `source_extras` dans les fiches des autres chantiers. cdf6f8314
- [x] Playbooks des règles de correction et de déduplication retirés ; leur procédure dans les docstrings de `rules.py` et `keys.py`. ae9de7097, d9ce60a4d

### Phase 6 — Registres hors du domaine

- [x] Registre du pivot dans le read model des statistiques, avec sa liaison SQL ; `domain/stats.py` retiré. 91659c168
- [x] Structures de transport des exécutions de phase dans `application/ports/pipeline/phase_executions.py` ; le contrat d'import ouvre `application.ports` au pipeline. a12c5a72c

## Questions ouvertes

- Types de document absents de la table de leur source, traduits en `other` (base locale, 2026-10-21) :
  - Crossref : `book-section` (3 enregistrements sources). Une section de livre peut réunir plusieurs chapitres : sa traduction en `book_chapter` reste à vérifier.
  - HAL : `PRESCONF`, `REPORT_RESPROT` (1 chacun).
  - OpenAlex : `reference-entry` (138).
  - DataCite : `StudyRegistration` (197), `Presentation` (94), `Technical note` (68), `Project` (34), `Wissenschaftlicher Artikel` (19), `article validé par les pairs` (14), `Journal Issue` (14), `RegistrationComponent` (14), `oceanographic cruise` (12), `Paratext` (10), `OutputManagementPlan` (10), `Project milestone` (10), `InteractiveResource` (8), `Protein-ligand binding data` (5), `Paper` (5). S'y ajoutent 49 valeurs à moins de 5 enregistrements sources, souvent des variantes de valeurs de la table (`Article de colloque`, `Book section`, `Doctoral Thesis`, `PhDThesis`).

