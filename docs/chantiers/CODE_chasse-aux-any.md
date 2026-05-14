# Chantier — Chasse aux `Any`

Commencé le 2026-05-10.

## Contexte

`disallow_untyped_defs = true` est configuré dans `pyproject.toml`,
mais neutralisé en pratique par 748 occurrences de `Any` dans 133
fichiers du code applicatif (`grep -rn ": Any\b\|-> Any\b"`). mypy
strict ne vérifie quasi rien dans les couches haute. C'est de la
décoration de discipline.

Distribution :
- `domain/` : 4 (déjà clean)
- `application/` : 355
- `infrastructure/` : 204
- `interfaces/` : 170

Patterns dominants :
- `conn: Any` → 265 occurrences (35 %). Hérité du chantier SQLA où
  le dispatch psycopg/SA imposait `Any`. Maintenant tout-SA, c'est
  `Connection` partout.
- `logger: Any` → 41 → `logging.Logger`.
- `row: Any` → 12 (au cas par cas : `Row` SA ou `dict`).
- Reste ~430 `Any` dispersés : ports (`Protocol`), helpers,
  signatures FastAPI, types ad-hoc.

## Décisions

1. **Tolérance** : zéro par défaut. `Any` admis seulement avec
   justification expresse dans une docstring ou un `# noqa` parlant
   (ex. mock `MagicMock` dans les tests, frontière dynamique avec
   une lib externe non typée).
2. **Activation strict** : module incrémental via
   `[[tool.mypy.overrides]]` dans `pyproject.toml`. Chaque module
   nettoyé bascule en `disallow_any_explicit = true` localement,
   verrouille la régression. Pas de bigbang en fin de chantier.
3. **Ordre d'attaque** : par pattern d'abord (`conn`, `logger`,
   `row` → 318 occ. ≈ 42 % en mécanique), puis par couche sur le
   reste (`domain` déjà propre, `application` → `infrastructure` →
   `interfaces`).
4. **Périmètre** :
   - `infrastructure/db/migrate.py` migré avec le reste (~141 lignes,
     trivial).
   - Tests : signatures alignées sur les fonctions testées (un test
     d'une fonction `(conn: Connection)` reçoit la fixture
     `sa_sync_conn`, pas besoin d'`Any`). `Any` toléré pour les
     `MagicMock`.

## Phasage

### Phase 1 — Sweep par pattern

- [x] `conn: Any` (265 occ.) et `cur: Any` (95 occ.) → `Connection`,
  sauf `migrate.py` (`psycopg.Cursor[Any]`, exclu SQLA).
- [x] `logger: Any` → `logging.Logger` (41 occ.).
- [x] `row: Any` → `Row` ou `dict[str, Any]` selon le contexte
  (12 occ.).

### Phase 2 — Sweep par couche

#### Phase 2.1 — `domain/`

- [x] 43 corrections en mode `--strict` : 4 `Any` explicites + 39 `dict`/`list`/`tuple` non paramétrés. Contrainte `disallow_any_generics` activée pour `domain.*`.

#### Phase 2.2 — `application/`

- [~] Services racine : `existing: Any` → `PubByDoi` (résolution conflit DOI). Restent justifiés : `set[Any]` / `list[Any]` dans `_merge_lists` (items hétérogènes par champ), `value: Any` dans `update_config_value` (frontière JSONB).
- [ ] `application/pipeline/` (82 occ. recensées) — découpage par patterns :
  - [x] Sweep A : `Callable[[Any], …Repository]` → `Callable[[Connection], …Repository]` sur les 6 normalizers (16 occ.) ; `_iter_rows -> Any` → `Iterator[Row[Any]]` dans `base.py` ; `list[Any]` → `list[Row[Any]]` dans `application/ports/pipeline/staging.py` + `infrastructure/db/queries/staging.py` (extension révélée par le sweep).
  - [x] Sweep B : `topics: Any` → `JsonValue` dans les 6 `subjects/ingest_*.py` (+ `entry`, `_extract_domain_labels`, `ontology_entry` au passage dans `ingest_openalex.py` et `ingest_scanr.py`).
  - [x] Sweep C : `dict[str, Any]` JSONB locaux dans les normalizers (`ext`, `biblio`, `meta`, `sd` : 5 occ. — réel < estimé) → `dict[str, JsonValue]`. Touchés : `normalize_crossref.py`, `normalize_scanr.py`, `normalize_theses.py`.
  - [x] Sweep D : `affiliations/resolve_addresses.py` — 9 `Any` sur 5 fonctions (`match_form_in_text`, `build_forms_by_structure`, `has_form_match_for_structure`, `resolve_address`, `process_addresses`) typés depuis les contrats du port `AddressResolutionQueries` : `form: dict[str, Any]` (row SA hydraté), `text_normalized: str`, `forms_by_structure: dict[int, list[dict[str, Any]]]`, retours `bool` / `list[tuple[int, int]]`.
  - Hors scope : `persons/create_persons_from_source_authorships.py` (6 `Any` dans la cascade matching — refonte attendue via `METIER_decide-person-match`). Cas résiduels (~10 occ.) : helpers `as_str` / `_safe_list` / `dedup_strs` (frontières dynamiques à documenter), `sp: Any` (savepoint SA), `INGESTORS: dict[str, Any]` (registry).
- [~] `application/ports/normalize_*.py` : tous les `Any` JSONB (frontière vers `bindparam(type_=JSONB)`) remplacés par `JsonValue` (alias récursif `str | int | float | bool | None | Sequence[JsonValue] | Mapping[str, JsonValue]` dans `domain/json_types.py`). 6 ports (HAL, OpenAlex, CrossRef, Theses, WoS, ScanR) + leurs 6 implémentations `infrastructure/db/queries/normalize_*.py` (top-level functions et signatures complètes CrossRef). Override mypy `disallow_any_explicit` posé sur 5 ports (`normalize_wos` exclu : utilise encore `list[dict[str, Any]]` pour les batchs SQL hétérogènes — tranche suivante). `compact_identifiers` (`domain/persons/identifiers.py`) typé en retour `dict[str, JsonValue] | None` au passage (alimente le JSONB `source_authorships.identifiers`). Restent à traiter : `**kwargs: Any` sur les méthodes adapter `Pg*NormalizeQueries` (HAL/OpenAlex/Theses/WoS/ScanR, ~13 méthodes) — implique d'éclater en signatures explicites façon CrossRef.

#### Phase 2.3 — `infrastructure/`

- [~] Racine : `_get_from_db(key: Any)` → `key: str` dans `app_config.py`. Le retour `Any` est inscrit en Phase 2.6 (frontière JSONB → `JsonValue`).
- [x] Sweep E : `filters: Any` → dataclass concrète importée du port (`ListFilters`, `FacetFilters`, `DirectoryFilters`, `AddressListFilters`, `AddressCountriesFilters`, `LabPersonsFilters`). 17 occurrences sur 6 fichiers : `publications/list.py` (10), `publications/facets.py` (3, dont `self.lab_hal_col: Any` → `str | None`), `persons/list.py` (2), `persons/facets.py` (1), `addresses.py` (2), `laboratories.py` (2 + `run_yesno_facet -> Any` → `Row[Any]`). Pré-requis : assouplissement `import-linter` (ignore `infrastructure.** -> application.ports.**`) + clarification `architecture.md` règle 3 (zone neutre `application.ports/` importable depuis infra ; le couplage interdit est *comportemental*, pas *transport de types*).
- [x] Sweep F : `**kwargs: Any` → signatures explicites sur les adapters `Pg*Queries`.
  - [x] Adapters API : `PgPublicationsQueries` (4 méthodes), `PgPersonsQueries` (5 méthodes), `PgStatsQueries` (6 méthodes) + top-level functions `stats/{publishers,journals,labs,summary}.py` (6 fonctions).
  - [x] Adapters pipeline `Pg*NormalizeQueries` : HAL (2 méthodes), OpenAlex (2), ScanR (2), Theses (2), WoS (1). Éclatement façon `normalize_crossref` (déjà fait).
- [ ] Sweep G : retours `Any` isolés (`db/connection.py:get_connection`, `repositories/publication_repository.py:_source_publication_from_row`, `sources/wos/extract_wos.py:insert_batch / log_remaining_quota`, `sources/hal/extract_hal.py`, `sources/hal/fetch_missing_hal_id.py:main`).
- [ ] Sweep H : héritage explicite `class Pg*Queries(*Queries):` pour les ~33 adapters. Documente l'implémentation, fait vérifier la conformité par mypy à la définition de classe (en complément du check au composition root). Dépend du Sweep F pour bénéficier pleinement de la vérification statique (sinon les `**kwargs: Any` masquent les divergences de signature).

#### Phase 2.4 — `interfaces/`

- [x] `interfaces/api/app.py` + `interfaces/api/deps.py` (18 occ.) : `lifespan` → `AsyncIterator[None]` ; exception handlers → `JSONResponse` ; middleware → `RequestResponseEndpoint` / `Response` (`starlette.middleware.base`) ; `health`/`metrics` → `JSONResponse | dict[str, Any]` / `dict[str, Any]` ; `pool: Any` → `cast(QueuePool, engine.pool)` (justifie l'accès à `_max_overflow`/`checkedout`/`checkedin`) ; `SPAStaticFiles.get_response` → signature parente `(str, Scope) -> Response` ; `require_admin` → `None`. Override mypy `disallow_any_generics` posé. Note : `health()` retourne `JSONResponse | dict[str, Any]` (Union avec `Response`) → FastAPI ne peut pas inférer le `response_model`. Ajouter `response_model=None` sur le décorateur (sinon `FastAPIError` à l'import de l'app). Cas non détecté par les hooks pre-commit qui ne lancent que `tests/unit/` ; le test smoke `tests/integration/interfaces/test_api.py::TestHealth::test_health` aurait capté le crash.
- [x] `interfaces/api/routers/` (124 occ., 17 fichiers) : tous les handlers avec `response_model=` retournent désormais leur BaseModel. Pattern retenu (option A de la question Pydantic ci-dessous) : `Model.model_validate(dict_du_query_service)` pour les retours composites ; constructeur direct `Model(...)` pour les retours scalaires (`OkResponse()`, `MergeResponse(...)`). `_: Any = Depends(require_admin)` → `_: None` (puisque `require_admin` retourne `None` après Phase 2 sur `deps.py`). Handlers sans `response_model` (3 dans `journals.py`, 3 dans `docs.py`) typés en `dict[str, Any]` ou `list[dict[str, ...]]` faute de modèle adapté. Override mypy `disallow_any_generics` posé sur `interfaces.api.routers.*`.
- [x] `interfaces/cli/` : 11 `Any` explicites + 4 `dict` non paramétrés corrigés (records DB → `list[dict[str, Any]]`, helper `c(text, *styles)` → `(object, *str) -> str`, `parse_date(val)` → `object`, `escape_sql(value)` → union `str | int | float | bool | list[Any] | dict[str, Any] | None`). mypy strict 0 erreur sur la couche.

#### Phase 2.5 — `tests/`

- [ ] Signatures alignées sur les fonctions testées.

#### Phase 2.6 — Généraliser `JsonValue` aux frontières JSON

Maintenant que l'alias existe (`domain/json_types.py`), tous les `dict[str, Any]` qui représentent en réalité du JSON / JSONB doivent basculer vers `JsonValue` pour cohérence. Action transverse — peut se faire au fil des sweeps Phase 2.1-2.5 ou en passe finale dédiée.

Périmètres identifiés :

- [ ] `interfaces/api/models.py` : `ConfigItem.value`, `ConfigValueUpdate.value`.
- [ ] `interfaces/api/app.py` : handlers `health`/`metrics`.
- [ ] `interfaces/cli/` : helpers `escape_sql`, records DB.
- [ ] `application/` : `_merge_lists` (devenu `merge_lists_dedup_ci` dans `domain/publications/aggregation.py`), `update_config_value`.
- [ ] `infrastructure/` : `app_config._get_from_db`.

### Phase 3 — Verrouillage

- [ ] `[[tool.mypy.overrides]]` par module au fil du nettoyage :
  `disallow_any_explicit = true` activé module par module dans
  `pyproject.toml` (un commit par bascule).
- [ ] Une fois tous les modules nettoyés, promotion en règle
  globale (retrait des overrides individuels, activation au niveau
  `[tool.mypy]`).

## Hors scope (chantiers de suite)

- **Renommage de variables historiques** : `cur` → `conn` partout
  (notamment dans les `process_work` des normalizers, les helpers
  qui ont gardé le nommage psycopg). Volontairement reporté à un
  chantier dédié pour ne pas mélanger « typer » et « renommer » dans
  les mêmes commits. État intermédiaire actuel : `cur: Connection`,
  techniquement correct mais visuellement bancal.

## Questions ouvertes

- **Frontière Pydantic / FastAPI — tranchée** : option A retenue,
  les handlers instancient le `BaseModel` du `response_model` au
  retour (`Model.model_validate(...)` ou constructeur direct).
  Option C (les query services retournent directement des types
  forts, plus de `dict[str, Any]` en infra) reste plus propre mais
  c'est un chantier architectural à part — déplacement des
  modèles hors de `interfaces/api/`, DTOs application-level. Pas
  ouvert ici, à reprendre si l'envie revient.
- **Payloads JSONB dans les `BaseModel`** : les 2 derniers `Any`
  explicites dans `interfaces/api/models.py` (`ConfigItem.value`,
  `ConfigValueUpdate.value`) restent volontairement libres
  (frontière JSON/JSONB documentée).
- **`Row` SA** : utiliser `Row` (générique sans paramétrage), ou
  des `NamedTuple` / `dataclass` typés par requête ? Le second est
  plus rigoureux mais double la dette si on bouge une colonne.
