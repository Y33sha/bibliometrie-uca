# Chantier — Typage strict des projections et DTOs

Commencé le 2026-05-17

## Contexte

Le chantier `CODE_chasse-aux-any` a verrouillé `disallow_any_explicit` et `disallow_any_generics` globalement. Subsistent quatre familles de types « bâtards » documentés et désactivés par module dans `pyproject.toml` (chiffres recomptés à l'ouverture du chantier) :

- **`Row[Any]`** (45 occ., 23 fichiers) — surtout signatures `process_work` des normalizers et retours de queries SA `.one()/.all()`. Le `[Any]` neutralise la vérification du contenu de la row alors qu'on sait quels champs sont sélectionnés.
- **`list[dict[str, Any]]`** (141 occ., 56 fichiers) — mélange hétérogène : listes de records DB hydratés en dict, batchs SQL `executemany` à valeurs hétérogènes, listes JSON externes, retours de query services API (`infrastructure/queries/*` consommés par les routers FastAPI).
- **`fields: dict[str, Any]`** (6 occ., 5 ports repository) — partial updates côté ports repository (`update_*_fields`). Les colonnes possibles sont connues du port mais pas exprimées dans le type.
- **Pydantic `BaseModel` dans `interfaces/api/models/`** (~175 classes réparties par feature) — DTOs de retour API. Les query services renvoient `dict[str, Any]`, les routers font `Model.model_validate(...)` pour fabriquer le `BaseModel` correspondant au `response_model` (option A retenue par `CODE_chasse-aux-any` Phase 2.4). Option C écartée à l'époque : faire en sorte que les query services renvoient directement des DTOs typés.

Le chantier `CODE_rich-domain-model` Phase 8 hydrate les **aggregates roots** (find_by_id → entité riche). Ce chantier-ci traite **tout le reste** : projections délibérément non hydratées, partial updates, DTOs de retour API.

## Décisions

1. **Pas d'hydratation systématique** : si une méthode retourne 2-3 colonnes pour usage immédiat, pas la peine de fabriquer une entité — un `NamedTuple` ou `TypedDict` suffit. Le critère « entité riche vs projection » se tranche au cas par cas selon ce que le caller en fait.
2. **Pattern de remplacement selon la couche** :
   - **Retours consommés par routers FastAPI** (`application/ports/api/*_queries.py`) : **Pydantic `BaseModel`**, parce que FastAPI a besoin du `response_model` pour la validation et la sérialisation JSON.
   - **Tout le reste** (pipeline, repos d'aggregate, batchs SQL, partial updates) : `TypedDict` / `NamedTuple` / `dataclass(frozen)` selon le cas. Règles de choix :
     - **TypedDict** quand le dict existe déjà (`RealDictCursor` psycopg, JSON parsé) — zero-cost. Aussi pour les champs optionnels avec `total=False`.
     - **NamedTuple** quand on crée la structure à partir d'un tuple-like SA (`row.col` accès nommé + destructuration possible).
     - **dataclass(frozen=True)** quand on veut des methods / properties calculées / defaults complexes.
3. **DTOs API — co-localisés avec le port qui les retourne**. Les Pydantic `BaseModel` qui sont les **types de retour d'un query service** sont définis dans `application/ports/api/<feature>_queries.py`, à côté du `Protocol` et des dataclasses de filtres déjà présentes (`DirectoryFilters`, `ListFilters`). Aucun dossier `application/<feature>/dtos.py` séparé — la zone neutre `application.ports.**` est leur place naturelle (les adapters `infrastructure.queries.*` peuvent les instancier sans casser le contrat DDD layered).

   Restent dans `interfaces/api/models/` les schémas Pydantic qui ne sont **pas** retournés par un query service : bodies de requête HTTP (POST/PUT/PATCH validés par FastAPI à l'entrée), réponses construites directement par le router (`OkResponse`, `MergeResponse`, etc.), enrichissements router-only.

   Test mental : « Est-ce qu'un adapter `Pg*Queries` instancie ce model ? » Oui → port. Non → `interfaces/api/models/`.

   Les routers ne font plus de `model_validate` sur les retours port — ils propagent directement le DTO renvoyé.
4. **Partial updates** : `TypedDict(total=False)` par port (`JournalUpdateFields`, `PerimeterUpdateFields`, `PublisherUpdateFields`, `StructureUpdateFields`, `StructureNameFormUpdateFields`). Absorbé depuis `rich-domain-model` Phase 8.
5. **Batchs SQL hétérogènes** (`normalize_wos` notamment) : décomposer par batch (`WosAddressBatch`, `WosAuthorshipBatch`, …) avec un dataclass ou TypedDict par contrat.
6. **`Row[Any]` SQLAlchemy** : remplacer par **NamedTuple par requête** (pas par `Row[tuple[...]]` paramétré, plus fragile au reorder de colonnes du SELECT). Critère de seuil : on type dès qu'on accède à `row.col_x` ou qu'on propage la row hors de la fonction. Les `.scalar_one()` mono-colonne restent intactes.
7. **Périodicité** : **sweep progressif par feature** (persons d'abord, puis publications, …) plutôt qu'un gros bang. Vu le volume (175 BaseModel + 141 `dict[str, Any]` + 45 `Row[Any]`), un refactor monolithique aurait un blast radius ingérable. Une feature à la fois, sortie de l'override mypy module par module.

## Phasage

Audit Phase 0 effectué à l'ouverture (cf. chiffres dans Contexte). Phases d'exécution :

### Phase 1 — Partial updates (TypedDict, scope étroit)

Les 6 `fields: dict[str, Any]` des ports repository deviennent des `TypedDict(total=False)` (un par port). Victoire rapide, test : type-check verrouille les callers à des clés de colonne valides.

- [x] `application/ports/repositories/journal_repository.py` → `JournalUpdateFields`
- [x] `application/ports/repositories/perimeter_repository.py` → `PerimeterUpdateFields`
- [x] `application/ports/repositories/publisher_repository.py` → `PublisherUpdateFields`
- [x] `application/ports/repositories/structure_repository.py` → `StructureUpdateFields` + `StructureNameFormUpdateFields`
- [x] Adapter les implémentations `infrastructure/repositories/*` correspondantes.
- [x] Adapter les callers application services (`journals`, `publishers`, `config`, `structures`).

### Phase 2 — `Row[Any]` des normalizers (staging)

Les 6 normalizers (`normalize_wos`, `_hal`, `_openalex`, `_crossref`, `_scanr`, `_theses`) consomment une row issue de `staging.raw_data`. Deux NamedTuple : `StagingRow` (4 colonnes : id, source_id, doi, raw_data) commune à 5 normalizers, `HalStagingRow` (5 colonnes, +`hal_collections`) pour HAL. `SourceNormalizer` devient `Generic[T_Row]`, et chaque sous-classe hydrate la row SA via un `_row_factory` abstract.

- [x] Définir `StagingRow` et `HalStagingRow` (NamedTuple) dans `application/ports/pipeline/staging.py`.
- [x] Adapter `application/pipeline/normalize/base.py` : `Generic[T_Row]`, `_row_factory` abstract, `_iter_rows` mappe via `_row_factory`, `process_work(row: T_Row)`.
- [x] Propager aux 6 normalizers (wos, hal, openalex, crossref, scanr, theses) : sous-classe `SourceNormalizer[StagingRow]` ou `[HalStagingRow]`, implémenter `_row_factory`, typer `process_work` / `process_record`.
- [x] Supprimer les alias FETCH_COLUMNS devenus inutiles (`source_id AS ut/scanr_id/openalex_id`) et l'override redondant Crossref.
- [x] Supprimer la branche morte `isinstance(staging_row, dict)` dans `normalize_openalex.process_work`.
- [x] Adapter les tests d'intégration idempotence et `test_reprocessing` qui appellent `process_work` directement (construction de `StagingRow`/`HalStagingRow` à partir de la row SA).
- [x] `infrastructure/queries/staging.py` reste avec `list[Row[Any]]` : le port garde son contrat paramétrable (`columns: str` ad-hoc). Les 6 `Row[Any]` ports/queries staging sont reportés à Phase 5 (records DB restants) — le mapping fort est dans la base normalizer, suffisant pour purger les 14 occurrences `Row[Any]` côté pipeline.

### Phase 3 — `Row[Any]` des repositories (hydratation entité)

Un NamedTuple par `_*_from_row`, **local au repo** (préfixe `_`, pure projection SQL, pas un concept domain). 7 NamedTuple créés sur 6 fichiers `infrastructure/repositories/*`.

- [x] `_PerimeterRow` (perimeter_repository) — projection `find_by_id`.
- [x] `_PublisherRow` (publisher_repository) — projection `find_by_id`.
- [x] `_JournalRow` (journal_repository) — projection `find_by_id`. Coerce `journal_type` et `is_academic` vers leur DEFAULT côté `_journal_from_row` (DB nullable, aggregate non-nullable).
- [x] `_AuthorshipRow` (authorship_repository) — projection `find_by_publication_id` avec `structure_ids` agrégé depuis `authorship_structures`.
- [x] `_SourcePublicationRow` (publication_repository) — projection `get_source_publications`. 24 colonnes.
- [x] `_StructureRow` + `_StructureNameFormRow` (structure_repository) — projections `find_by_id` (l'aggregate Structure compose les deux).
- [x] Construction des NamedTuple au site d'appel par déballage positionnel : `_XxxRow(*raw)`. Les signatures `_xxx_from_row` sont strictement typées au NamedTuple.

### Phase 4 — Sweep DTO par feature (gros morceau)

Un sweep par feature, dans cet ordre (du plus petit au plus gros pour roder le pattern) :

- [x] **subjects** (7 BaseModel). DTOs (`SubjectOntologyEntry`, `SubjectOut`, `SubjectListItem`, `SubjectListResponse`, `SubjectNeighborOut`, `SubjectDetailResponse`, `SubjectFrequency`) co-localisés dans `application/ports/api/subjects_queries.py` avec le `Protocol`. PgSubjectsAdminQueries instancie les DTOs ; router propage sans `model_validate`. `interfaces/api/models/subjects.py` supprimé (les 3 importeurs cross-feature — `models/publications.py`, `routers/persons.py`, `routers/laboratories.py` — pointent directement vers le port).
- [x] **auth** (2). Pas de port query (auth lit un cookie HMAC, pas la DB). `LoginRequest` est un body HTTP (entrée FastAPI), `AuthCheckResponse` est construit par le router — les deux restent dans `interfaces/api/models/auth.py` (cf. Décision 3 : seuls les retours de query service migrent au port).
- [ ] **journals** (3)
- [ ] **publishers** (4)
- [ ] **perimeters** (5 admin)
- [ ] **person_duplicates** (9 admin)
- [ ] **hal_problems** (14)
- [ ] **publication_duplicates** (7 admin)
- [ ] **feedback** (7 admin)
- [ ] **pipeline_config** (3 admin) + **pipeline_logs** (4 admin)
- [ ] **structures** (12 admin)
- [ ] **addresses** (17 admin)
- [ ] **stats** (14)
- [ ] **laboratories** (14)
- [ ] **publications** (21)
- [ ] **persons** (21 + 16 admin + 12 authorships admin = 49)

Pour chaque feature, étapes type :

1. Identifier les BaseModels qui sont des **retours de query service** (le port `application/ports/api/<feature>_queries.py` les retourne) vs les **bodies / réponses router-only** (qui restent dans `interfaces/api/models/`).
2. Déplacer les premiers vers `application/ports/api/<feature>_queries.py`, à côté du `Protocol` (cf. Décision 3). Les seconds restent en place.
3. Adapter la signature du port pour retourner les DTOs typés au lieu de `dict[str, Any]`.
4. Adapter `infrastructure/queries/<feature>` pour instancier les DTOs côté infra.
5. Simplifier le routeur (plus de `model_validate` sur les retours port).
6. Supprimer `interfaces/api/models/<feature>.py` si plus aucun BaseModel n'y vit (sinon le réduire à ce qui reste).
7. Adapter `interfaces/api/models/__init__.py` (retirer les imports/exports déplacés).
8. Adapter les importeurs cross-feature qui pointaient via `interfaces.api.models` → pointage direct vers le port.
9. Tests : la suite d'intégration de la feature doit rester verte.

**Override mypy** : le glob `interfaces.api.models.*` reste dans l'override `disallow_any_explicit = false` (Pydantic 2 propage des `Any` en interne). Les DTOs déplacés vers `application/ports/api/*` sont couverts par le glob `application.ports.api.*` qui existe déjà dans le même override — pas de nouvelle exception à ajouter. L'objectif Phase 4 n'est pas de sortir les DTOs de l'override, mais d'évacuer les `dict[str, Any]` des ports et adapters.

Note `_common.py` (16 BaseModel partagés transverses) : à traiter à la fin selon la nature (retours port vs réponses router-only).

### Phase 5 — Records DB pipeline restants

Les `list[dict[str, Any]]` non triés par Phase 1-4 : queries `merge`, `name_forms`, `normalize_wos`, batchs SQL `executemany`, services `merge_pubs_by_hal_id`, `create_persons_from_source_authorships`, `resolve_addresses`. TypedDict ou dataclass par contrat, au cas par cas. Estimation ~80 occurrences restantes à ce stade.

### Phase 6 — Bilan override mypy

Retrait final des modules de l'override `disallow_any_explicit = false` qui peuvent l'être. Documentation des modules irréductibles (sources API externes, CLI) avec justification durable dans le commentaire `pyproject.toml`.

## Résiduel JSONB (à tout hasard)

Le typage des colonnes JSONB côté Python est **déjà largement fait** dans `infrastructure/jsonb_models/` (cf. `PublicationMeta`, `PublicationTopics`, `PublicationBiblio`, `ExternalIds`, `StructureApiIds`). Restent **2 colonnes non modélisées** sur `source_authorships`, à intégrer opportunément quand un sweep touche le code qui les manipule (normalizers + `create_persons_from_source_authorships`) :

- **`source_authorships.person_identifiers`** : dict avec clés normalisées (`orcid`, `idhal`, `idref`, `hal_person_id`, `researcher_id` selon la source). Un modèle Pydantic réutiliserait les VOs `ORCID`, `IdHAL`, `IdRef` existants pour normaliser à l'écriture — cohérent avec `ExternalIds`.
- **`source_authorships.source_data`** : fourre-tout par source (payload résiduel hétérogène). Modèle plausible mais retour sur investissement faible — cette colonne est consommée brut, sans logique métier dessus. À laisser tel quel à moins d'un cas d'usage concret.

Le volet "introspection BI" du reproche initial (un outil Metabase/Superset ne sait pas explorer un JSONB libre) n'est pas couvert par les Pydantic models — il demanderait de promouvoir des clés en colonnes natives ou créer des vues SQL. À attendre un signal réel de la DSI sur un outil BI à brancher avant d'instruire.

## Bénéfices attendus

- Typage fort de bout en bout (query service → router → réponse HTTP) sans `dict[str, Any]` intermédiaire.
- Typage statique des partial updates (les callers sont contraints aux colonnes valides du port).
- Sortie d'`Any` sur l'essentiel des modules encore en override.

## Questions ouvertes

Aucune au démarrage — les 4 questions initiales ont été tranchées (cf. Décisions 3, 6, 7 et le seuil de typage en 6). Toute question apparaissant en cours de chantier va ici.

## Liens

- Préalable : `2026-05-15_CODE_chasse-aux-any.md` (verrou global posé, modules avec `Any` documentés en désactivation).
- Articulation avec `CODE_rich-domain-model.md` Phase 8 : la Phase 8 hydrate les aggregates roots (charge `Entity` au lieu de `dict[str, Any]` sur les `find_by_id`). Ce chantier-ci traite tous les autres retours non typés (projections minimales, batchs, partial updates, DTOs API).

## Exceptions documentées

Cas où le typage statique ne peut pas être strict, avec justification durable. Chaque entrée doit pointer un emplacement précis (fichier + ligne ou fonction) et expliquer pourquoi l'exception est inévitable, pas juste pratique.

- **`application/structures.update_structure` — `# type: ignore[literal-required]`** (Phase 1) : la clé de l'affectation `update_fields[col_name] = val` vient d'une variable (`col_name` issu de `_STRUCTURE_FIELD_MAP`), pas d'un littéral. TypedDict exige des clés littérales pour vérifier la conformité statiquement. Alternative possible : déplier en `if/elif` avec littéraux, mais le mapping reste plus lisible et la valeur traversée est en sortie de whitelist Pydantic.
