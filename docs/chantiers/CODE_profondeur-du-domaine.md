# Chantier — Règles du domaine complètes et uniques

## Contexte

Plusieurs règles métier sont découpées entre `domain/` et ses appelants. Le domaine expose des fragments ; le pipeline ou le SQL les assemble selon un ordre et des préconditions que seules les docstrings énoncent.

Règles assemblées par l'appelant :

- matching des personnes : `decide_person_match` (`domain/persons/matching.py`) reçoit six résultats précalculés par `pipeline/transformation/persons/cascade.py`, qui appelle `decide_match_by_identifier` par type d'identifiant, applique `trusted_identifier` à l'ORCID et passe le même `rejected_person_ids` à deux fonctions ;
- verdict d'une forme de nom : décidé dans un `CASE` de `fetch_name_form_status_map` (`cascade.py`), comparé à des chaînes dans `matching.py` ;
- correction unaire d'un enregistrement source : `compute_update` (`pipeline/transformation/publications/correction/correct_unary.py`) enchaîne mapping, règles, type du dépôt HAL d'origine, retrait des clés de thèse et réapplication des retraits de la sous-étape cluster ;
- revue d'un enregistrement source par l'espace de noms de son DOI : la règle est dans `correction/journal_by_doi.py`, le domaine en garde une constante ;
- alignement des auteurs : `align_publication` (`domain/publications/author_grouping.py`) écrit dans les champs de `_SourceRecordLinks` après une séquence fixe d'étapes.

Connaissances écrites à plusieurs endroits :

- un prédicat de correction : la dataclass `MetadataForCorrection`, `_AppliesTo`, `_check_predicate`, `_SOURCE_ONLY_PREDICATES`, `UnaryCorrectionRow` et `for_correction()`, la requête `_SELECT`, les valeurs factices de `consolidation.py` ;
- les clés de configuration : `domain/config.py` (nature, validation), `infrastructure/db/tables.py` (CHECK), `pipeline/runtime/config.py` (littéraux, valeurs par défaut, recontrainte) ;
- la propriété des clés de `raw_metadata` : chaque sous-étape de `metadata_correction` filtre ses clés à sa façon ;
- `CONVERGENCE_CASES`, re-listé dans `author_grouping/queries.py` ;
- « enregistrement ScanR issu de HAL », à quatre endroits, dont un `LIKE 'hal%'` sans validation de l'identifiant ;
- `meta ? 'conference'`, dans `metadata_correction_queries.py` et `type_proceedings_volumes.py` ;
- la définition d'une revue diamant, seulement dans `infrastructure/sql_fragments.py` ;
- « prénom réduit à des initiales », trois prédicats ; `cascade.py` recopie `attested_full_first_names` ;
- les seuils de comparaison des auteurs, dans `author_grouping.py` et `interfaces/cli/dev/estimate_residual_weights.py` ;
- les clés des JSON `meta` et `biblio` : écrites par `pipeline/ingestion/hal/payload.py`, lues par chaîne dans `domain/publications/conference.py` et `relations.py` ;
- le registre des dimensions de statistiques (`domain/stats.py`) et leur liaison SQL (`infrastructure/read_models/stats/pivot.py`), synchronisés par des `assert`.

Règles du domaine contournées :

- `reattribute_to` (`domain/persons/identifier_attribution.py`) réattribue seulement un identifiant `rejected` ; l'endpoint `PATCH /api/persons/identifiers/{id}/reassign`, sans appelant dans le frontend, réattribue depuis tout statut ;
- `allow_person_creation` (`domain/persons/creation.py`) décide sur la source `theses`. ScanR donne aussi les rôles de jury : 2 324 contributions sources ScanR dans le périmètre, à rôles de jury seuls, sur la base locale du 2026-10-20 ; aucune personne ne vient de ces seules contributions, 8 restent sans personne ;
- IdRef et idHAL sont normalisés seulement à l'écriture dans `person_identifiers` : HAL découpe l'IdRef à la main, ScanR le garde brut, et le matching compare une valeur brute à une valeur normalisée ;
- `map_doc_type` cherche une valeur absente de la table de sa source dans les tables des autres sources, dans l'ordre du dict ; une valeur inconnue devient `other` sans signal.

Classes d'identifiants : 15 value objects répètent `__post_init__`, `try_parse` et `__str__` (`publications/identifiers.py`, `persons/identifiers.py`, `structures/identifiers.py`), et `clean_doi`, `normalize_nnt`, `normalize_pmid`… appellent seulement leur `_normalize_*`.

## Décisions

- Une règle du domaine a une seule entrée publique, qui rend une décision complète. L'appelant lit les faits et écrit le résultat.
- Le SQL rend des faits bruts ; le verdict se calcule en Python. Une règle qui doit rester en SQL a un fragment unique dans `infrastructure/sql_fragments.py`.
- Une règle répétée en SQL et en Python a un test de parité.
- `PERSON_SEARCH_IDENTIFIERS` et les listes de sources propres aux phases relèvent du chantier [Une source, un adaptateur](CODE_adaptateur-par-source.md).

## Phasage

### Phase 1 — Personnes

- [x] `allow_person_creation` décidé sur les rôles. 49c40081a
- [x] Réattribution d'un identifiant seulement par l'agrégat : endpoint de réattribution retiré ; docstring de `AttributionStatus` alignée sur l'usage de l'admin.
- [ ] Identifiants personne normalisés à l'ingestion par `normalized_identifier_value`.
- [ ] Cascade de matching en une entrée de domaine, sur un index de personnes ; `NameFormDecision` et `PersonMatchDecision` fusionnées.
- [ ] Verdict d'une forme de nom en Python, sur `AttributionStatus`.
- [ ] Un prédicat « prénom réduit à des initiales », un prédicat « prénom plein qui prolonge les initiales ».

### Phase 2 — Correction des métadonnées

- [ ] `correct_source_record` dans le domaine : valeurs corrigées et provenances.
- [ ] Revue par espace de noms DOI en fonction de domaine.
- [ ] Registre des clés de `raw_metadata` et de leur sous-étape ; `effective_external_ids`.
- [ ] Prédicats d'égalité lus par nom de champ ; champs propres aux enregistrements sources marqués ; fabrique `MetadataForCorrection.for_publication`.
- [ ] `map_doc_type` sans repli sur les autres sources ; valeurs inconnues journalisées.

### Phase 3 — Doublons ponctuels

- [ ] `CONVERGENCE_CASES` importé ; fragments SQL uniques pour « ScanR issu de HAL » et `declares_conference` ; revue diamant définie dans le domaine.
- [ ] Seuils de comparaison des auteurs partagés avec `estimate_residual_weights.py`.
- [ ] Clés et accesseurs des JSON `meta` et `biblio` dans un module commun.
- [ ] `_SourceRecordLinks.resolve` ; `_Claim` en `NamedTuple` ; critères de création de publication en prédicats de `ReconcileMember`.

### Phase 4 — Configuration et identifiants

- [ ] Registre unique des clés de configuration (nom, nature, défaut), lecteur générique côté pipeline.
- [ ] Base commune des value objects d'identifiants ; fonctions de normalisation passe-plats retirées.

### Phase 5 — Documentation

- [ ] Mise à jour de `docs/pipeline/08-persons.md`, `06-metadata-correction.md` et `docs/agregats/`.

## Questions ouvertes

- `source_records.doc_type` contient le vocabulaire de la source jusqu'à `metadata_correction`. Le traduire dès `normalize`, avec le type source dans une colonne dédiée, retirerait le marqueur `DOC_TYPE_MAP` et le remapping des phases antérieures. Décision de schéma.
- `domain/` contient des contrats entre couches qui ne sont pas des règles métier : `config`, `stats`, `pipeline_runs`. Import-linter interdit `pipeline → application`, donc `domain/` est le seul paquet commun. Un paquet neutre déclaré dans import-linter, ou le statu quo.
- Registre des dimensions de statistiques : dans le read model, avec sa liaison SQL, ou dans le paquet neutre.
