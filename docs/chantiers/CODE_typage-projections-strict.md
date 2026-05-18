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
- [x] **journals** (3 → port). `JournalOut`, `JournalListResponse` migrés vers `application/ports/api/journals_queries.py`. `JournalBasic` ajouté (port) pour typer `get_journal` (le router renvoyait `dict[str, Any]` avant). `JournalUpdate` (body PUT) reste dans `interfaces/api/models/journals.py`. Router propage les DTOs sans `model_validate`. PUT/POST passent à `OkResponse` / `MergeResponse` au lieu de dicts inline (shape JSON identique).
- [x] **publishers** (4 → port). `PublisherListItem`, `PublisherListResponse`, `PublisherBasic` migrés vers `application/ports/api/publishers_queries.py`. `PublisherUpdate` (body PUT) reste dans `interfaces/api/models/publishers.py`. Router propage les DTOs sans wrapping intermédiaire.
- [x] **perimeters** (5 admin → 2 port, 3 restent). `PerimeterOut` et `PerimeterStructureItem` migrés vers `application/ports/api/perimeters_queries.py`. `PerimeterCreate`, `PerimeterUpdate`, `AddPerimeterStructure` (bodies HTTP) restent dans `interfaces/api/models/admin/perimeters.py`. `PgPerimetersAdminQueries` instancie les DTOs directement (lecture `_mapping → dict` supprimée). Router propage sans `model_validate`.
- [x] **person_duplicates** (9 admin → 7 port, 2 restent). `PersonDedupIdentifier`, `PersonDedupPublication`, `PersonDedupLab`, `PersonDedupDetail`, `PersonDuplicatePair`, `PersonConflictPub`, `PersonConflictPair` migrés vers `application/ports/api/person_duplicates_queries.py`. `PersonDuplicatePairResponse` et `PersonConflictPairResponse` (wrappers `{"pair": ... | None}` construits par le router) restent dans `interfaces/api/models/admin/person_duplicates.py` et importent les types port. PgPersonDuplicatesQueries instancie les DTOs. Router : `Response(pair=pair)` au lieu de `model_validate({"pair": pair})`.
- [x] **hal_problems** (14 → port). Les 14 DTOs migrés vers `application/ports/api/hal_problems_queries.py`. Suppression complète de `interfaces/api/models/hal_problems.py`. PgHalProblemsQueries instancie tous les DTOs. Profite de la migration pour nettoyer une API smell : `hal_missing_collections` retournait un mix `Response | {"error": "no_collection"}` (sentinel dict), passe à `Response | None` ; le router transforme None en HTTPException 400.
- [x] **publication_duplicates** (7 admin → 6 port, 1 reste). `PubDedupJournal`, `PubDedupSource`, `PubDedupAuthor`, `PubDedupDetail`, `PubDuplicatePair`, `PubDuplicateNextResponse` migrés vers `application/ports/api/publication_duplicates_queries.py`. `PubMergeResponse` (réponse router post-merge) reste dans `interfaces/api/models/admin/publication_duplicates.py`. PgPublicationDuplicatesQueries instancie les DTOs. Au passage : `get_publications_basic(...) -> dict[int, Any]` (utilisé uniquement pour check d'existence côté router) remplacé par `existing_publication_ids(...) -> set[int]`, cohérent avec `existing_journal_ids` / `existing_publisher_ids`.
- [x] **feedback** (7 admin → 6 port, 1 reste). `FeedbackStats`, `FeedbackLabDetected`, `FeedbackMatchedForm`, `FeedbackAddressItem`, `FeedbackAddressesResponse`, `FeedbackStructureItem` migrés vers `application/ports/api/admin_feedback_queries.py`. `FeedbackStructuresResponse` (wrapper `{by_type, default_structure_id}` composé par le router) reste dans `interfaces/api/models/admin/feedback.py` et importe `FeedbackStructureItem` du port. PgAdminFeedbackQueries instancie les DTOs ; le calcul `detection_rate` (cohérence concordant/reviewed) est déplacé du router vers l'adapter, pour que le router soit un simple passe-plat.
- [x] **pipeline_config** (3 admin → 1 port, 2 restent) + **pipeline_logs** (4 admin → 0 port, 4 restent). Sweep mince : seul `ConfigItem` migre vers `application/ports/api/config_queries.py` (retourné par `ConfigQueries.list_config`). `HalCollectionsResponse` (wrapper avec `count`) et `ConfigValueUpdate` (body PUT) restent dans `interfaces/api/models/admin/pipeline_config.py`. Côté pipeline_logs : aucun DTO ne migre, tous sont construits par le router à partir de lectures filesystem (`read_status()`, `cron.log`, `reports/*.md`) sans passer par un query service du port. `PgConfigQueries.list_config()` instancie `ConfigItem` ; le router propage sans `model_validate`. `update_config_value` garde `ConfigItem.model_validate(...)` parce qu'il appelle `ConfigStore` (port repo généraliste, pas port API).
- [x] **structures** (12 admin → 5 port, 6 restent, 1 supprimé). `StructureListItem`, `StructureOut`, `RelatedStructureOut`, `NameFormOut`, `StructureDetailResponse` migrés vers `application/ports/api/structures_queries.py`. Restent dans `interfaces/api/models/admin/structures.py` les 5 bodies HTTP (`StructureCreate`, `StructureUpdate`, `RelationCreate`, `NameFormCreate`, `NameFormUpdate`) + `StructureRelationCreateResponse` (réponse polymorphe construite par le router : soit la relation créée, soit `{status: "already_exists"}`). `StructureRelationOut` était dead code (jamais importé) — supprimé. PgStructuresQueries instancie les DTOs ; les retours `StructureOut`/`NameFormOut` des services (POST/PUT) gardent `model_validate(...)` côté router (le service retourne un dict via `StructureRepository`, pas un DTO).
- [x] **addresses** (17 admin → 10 port, 7 restent). `AddressStructureSummary`, `AddressOut`, `AddressListResponse`, `AddressPublicationItem`, `CountryOut`, `CountrySuggestion`, `AddressForCountryAttribution`, `AddressesCountriesResponse`, `CountrySuggestionsResponse`, `AddressStatsResponse` migrés vers `application/ports/api/addresses_queries.py`. Restent dans `interfaces/api/models/admin/addresses.py` les 4 bodies HTTP (`ReviewAction`, `BatchReviewAction`, `SetCountry`, `BatchSetCountry`) + 3 réponses composées par le router (`AddressPublicationsResponse` = raw_text + publications, `AddressReviewResponse` = id + structures + link, `BatchCountryResponse` = updated + propagated). Au passage : `get_address_basic` (qui retournait un dict {id, raw_text} consommé seulement pour `raw_text`) simplifié en `get_address_raw_text(addr_id) -> str | None`. `get_structure_link` garde `dict[str, Any]` (2 champs consommés par le router pour composer `AddressReviewResponse`).
- [x] **stats** (14 → port). Tous les DTOs migrés vers `application/ports/api/stats_queries.py` : OaCounts (sous-type), PublisherStatsRow, JournalStatsRow, LabStatsRow, PublisherStatsResponse, JournalStatsResponse, LabStatsResponse, YearStatsRow, StatsSummary, YearFacet, LabFacet, OaFacet, ApcFacet, StatsFacetsResponse. Suppression complète de `interfaces/api/models/stats.py`. Les fonctions libres `_publisher_stats`/`_journal_stats`/`_stats_labs`/`_stats_summary`/`_stats_by_year`/`_stats_facets` continuent à retourner des dicts (réutilisables hors API) ; la conversion vers Pydantic se fait dans `PgStatsQueries` à la sortie. Router : suppression des 6 `model_validate` redondants.
- [x] **laboratories** (14 → port). Les 14 DTOs migrés vers `application/ports/api/laboratories_queries.py` (`LabTutelle`, `LaboratoryListItem`, `LabStructureCore`, `LabRelatedStructure`, `LaboratoryDetailResponse`, `LabPersonOut`, `LabPersonsFacets`, `LabOrphanAuthorships`, `LaboratoryPersonsResponse`, `LabAddressOut`, `LaboratoryAddressesResponse`, `LabDashboardCollab`, `LabTopCountry`, `LaboratoryDashboardResponse`). Suppression complète de `interfaces/api/models/laboratories.py`. PgLaboratoriesQueries instancie les DTOs ; router propage sans `model_validate`. Au passage : sweep `_common` port-side anticipé (6 types — `FacetValueCount`, `YesNoCount`, `ValueConfirmedOut`, `PubYearCount`, `DashboardOa`, `StructureRef` — déplacés vers `application/ports/api/_common.py` ; `interfaces/api/models/_common.py` les re-exporte pour compat des importeurs router et conserve les 10 types router-only `OkResponse`/`MergeRequest`/etc.). Tests d'intégration migrés de dict-access (`res["foo"]["bar"]`) vers attribute-access (`res.foo.bar`). Renommage SQL `AS count` → `AS n` dans 5 requêtes pour éviter le conflit mypy avec `Row.count` (méthode tuple).
- [x] **publications** (21 → 19 port, 2 bodies déplacés). Les 19 DTOs retours du query service migrés vers `application/ports/api/publications_queries.py` : `PubLabItem`, `PubApcPayment`, `PublicationListItem`, `PublicationListResponse`, `IntValueFacet`, `StrValueFacet`, `LabeledIntFacet`, `TextStrFacet`, `PublicationsFacetsResponse`, `PublicationDetailCore`, `SourcePublicationOut`, `ConsolidatedAuthorshipOut`, `SourceAuthorshipOut`, `ThesesAuthorshipOut`, `EcoleDoctorale`, `PartenaireThese`, `ThesisMeta`, `StructureInfo`, `PublicationDetailResponse`. Les 2 bodies `MergePublications` et `MarkDistinctPublications` (utilisés par `routers/admin/publication_duplicates.py`) déplacés vers `interfaces/api/models/admin/publication_duplicates.py` (à côté des autres bodies admin). Suppression complète de `interfaces/api/models/publications.py`. `PgPublicationsQueries` fait `Model.model_validate(...)` à la sortie de chaque fonction libre — pattern stats : les helpers `_list_publications`/`_publications_facets`/`_get_publication_detail` continuent à retourner des dicts (réutilisables hors API). Router : 3 `model_validate` supprimés. Note : `EcoleDoctorale` et `PartenaireThese` (port) servent désormais à la fois de DTOs API et de sous-modèles de la colonne JSONB `meta` (utilisés par `infrastructure/jsonb_models/publication.py:PublicationMeta`). `model_config = ConfigDict(extra="allow")` reste pour tolérer des clés inconnues côté JSONB sans casser à la lecture. `infrastructure.jsonb_models.publication` re-exporte les deux pour les importeurs historiques.
- [x] **persons** (21 + 16 admin + 12 authorships admin = 49 → 27 port, 22 router-only). Les 21 DTOs de `interfaces/api/models/persons.py` migrés vers `application/ports/api/persons_queries.py` (identifiants + name-forms, annuaire/recherche/liste, facettes/référentiels/stats, profil/thèses/adresses/dashboard). Sur les 16 admin/persons : 3 retours port (`NameFormAuthorshipRef`, `OtherPersonOut`, `NameFormAuthorshipsResponse`) migrés ; 9 bodies + 4 réponses mutations router-construites restent dans `interfaces/api/models/admin/persons.py`. Sur les 12 admin/authorships : 3 retours port (`OrphanCountResponse`, `OrphanAuthorshipOut`, `OrphanAuthorshipsResponse`) migrés ; 5 bodies + 4 réponses mutations router-construites restent dans `interfaces/api/models/admin/authorships.py`. Suppression complète de `interfaces/api/models/persons.py`. `PgPersonsQueries` fait `Model.model_validate(...)` au boundary pour chaque méthode (pattern stats/publications). Les 3 routers (`persons`, `admin/persons`, `admin/authorships`) propagent les DTOs port sans `model_validate` ; 18 `model_validate` redondants supprimés au total.

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

**Override mypy** : deux globs concernent ce chantier dans `[[tool.mypy.overrides]]` (`disallow_any_explicit = false`) :

- `interfaces.api.models.*` : nécessaire pour `ConfigItem.value: Any` / `ConfigValueUpdate.value: Any` (Pydantic ne supporte pas l'alias récursif `JsonValue` sur py310). Sans ces deux fields, le glob pourrait sortir.
- `application.ports.api.*` : nécessaire tant que la majorité des ports retournent `dict[str, Any]` — c'est précisément ce que Phase 4 vient liquider port par port. Un module qui n'a plus aucun `Any` après migration pourrait en sortir individuellement, mais le glob étant collectif, l'éclater à chaque sweep serait du bruit. **Phase 6 fera le ménage d'un bloc** une fois tous les ports passés.

Pas de nouvelle exception à ajouter pendant Phase 4 : les DTOs migrés tombent sous un glob qui existe déjà.

Note `_common.py` : la séparation port-side / router-side a été faite lors du sweep `laboratories`. 6 types port-side vivent dans `application/ports/api/_common.py` (`FacetValueCount`, `YesNoCount`, `ValueConfirmedOut`, `PubYearCount`, `DashboardOa`, `StructureRef`) ; les 10 types router-only restent dans `interfaces/api/models/_common.py` (`OkResponse`, `MergeRequest`, `MergeResponse`, `DeletedResponse`, `RemovedResponse`, `DetachedResponse`, `BatchUpdatedResponse`, `CreatedIdResponse`, `StatusResponse`, `TotalCountResponse`). Le router re-importe les 6 port-side via `interfaces/api/models/_common.py` (re-export) pour ne pas casser les importeurs historiques.

### Phase 5 — Records DB pipeline restants

Les `list[dict[str, Any]]` non triés par Phase 1-4 : queries `merge`, `name_forms`, `normalize_wos`, batchs SQL `executemany`, services `merge_pubs_by_hal_id`, `create_persons_from_source_authorships`, `resolve_addresses`. TypedDict ou dataclass par contrat, au cas par cas. Estimation ~80 occurrences restantes à ce stade.

Sous-phasage (du plus simple au plus risqué) :

- [x] **5.1 — `MergeQueries` + `merge_pubs_by_hal_id`**. 3 NamedTuple co-localisés dans le port (`NntDuplicateRow`, `OaScanrHalRow`, `HalSourceRow`) + 2 dataclass locales au caller (`HalLinkItem`, `HalMergeItem`) au lieu des fusions `{**dict, **dict}`. Tests `test_merge_pubs_by_hal_id.py` + `test_merge_pubs_by_nnt.py` adaptés (accès attribut au lieu de `["clé"]`). Test d'intégration `test_merge.py` aussi.
- [x] **5.2 — `NameFormsQueries`**. 1 NamedTuple `PersonNameRow` pour `fetch_persons_names`. 1 TypedDict `RawFormBatchItem` pour le batch executemany (SA consomme les dicts tels quels). Caller `populate_person_name_forms` adapté ; tests unit + intégration verts.
- [x] **5.3 — `WosNormalizeQueries` (batchs executemany)**. 3 TypedDict : `WosAddressBatchItem`, `WosAuthorshipBatchItem`, `WosAuthorshipAddressItem`. Construction explicite typée dans `normalize_wos.py`. Tests `test_normalize_wos.py` (72 unit + 1 intégration) verts sans modif (TypedDict compatible runtime avec dict).
- [x] **5.4 — `PersonsCreateQueries` + `create_persons_from_source_authorships`**. Refactor propre en 3 NamedTuple : `BareUnlinkedAuthorship` + `LinkedAuthorshipRow` côté port, `EnrichedAuthorship` côté caller (après parsing nom + flags). Plus de mutation de dict. `_enrich(row)` est pure (construit un nouvel `EnrichedAuthorship`). Boundary vers `application/persons.py` (link/add_identifiers qui restent en API dict) : conversion ponctuelle via `_asdict()` documentée. 9 tests intégration verts.
- [x] **5.5 — `AddressResolutionQueries` + `resolve_addresses`**. 1 NamedTuple `StructureNameForm` (8 colonnes : id, structure_id, form_text, is_word_boundary, requires_context_of, is_excluding, struct_code, struct_type) pour `load_name_forms`. Helpers (`match_form_in_text`, `resolve_address`, `build_forms_by_structure`, `has_form_match_for_structure`, `process_addresses`) typés. Test `test_none_form` supprimé (NOT NULL schema, cas non réaliste). 28 tests unit + 14 intégration verts.
- [ ] **5.6 — Subjects**. 1 TypedDict `OntologyEntry`. Port `upsert_subject` et `SubjectCache.get_or_upsert` signent `ontologies: dict[str, OntologyEntry] | None`.
- [ ] **5.7 — Staging : refactor en dataclass héritée**. Passer `StagingRow`/`HalStagingRow` de NamedTuple à `dataclass(frozen=True)` avec vrai héritage (`class HalStagingRow(StagingRow)`). Une seule méthode au port (`fetch_pending_staging → list[StagingRow]`, l'implémentation HAL retourne en fait des `HalStagingRow` — substitution LSP). Suppression du paramètre `columns: str`, des `Row[Any]`, de `_row_factory` côté `SourceNormalizer`, du `Generic[T_Row]`. Le normalizer HAL accède `.hal_collections` via `cast`/`isinstance`. Sweep plus large que prévu initialement mais nettement plus propre.
- [ ] **5.8 — Bilan**. Suite intégration verte, recompte des `Any` restants dans les zones traitées, mise à jour de la note Phase 6 sur les overrides mypy résiduels.

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
