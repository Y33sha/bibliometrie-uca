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

- [x] `domain/` (43 corrections en mode `--strict` : 4 `Any` explicites
  + 39 `dict`/`list`/`tuple` non paramétrés. Contrainte
  `disallow_any_generics` activée pour `domain.*`).
- [~] `application/` services racine : `existing: Any` →
  `PubByDoi` (résolution conflit DOI). Restent justifiés : `set[Any]`
  / `list[Any]` dans `_merge_lists` (items hétérogènes par champ),
  `value: Any` dans `update_config_value` (frontière JSONB).
  Ports + orchestrateurs pipeline : pas encore traités.
- [~] `infrastructure/` racine : `_get_from_db(key: Any)` → `key: str`
  dans `app_config.py`. Le retour `Any` est conservé et justifié en
  docstring (frontière JSONB libre — chaque caller fait son
  `isinstance(...)` avant usage). Adapters, queries, repositories :
  pas encore traités.
- [x] `interfaces/api/app.py` + `interfaces/api/deps.py` (18 occ.) :
  `lifespan` → `AsyncIterator[None]` ; exception handlers → `JSONResponse` ;
  middleware → `RequestResponseEndpoint` / `Response` (`starlette.middleware.base`) ;
  `health`/`metrics` → `JSONResponse | dict[str, Any]` / `dict[str, Any]` ;
  `pool: Any` → `cast(QueuePool, engine.pool)` (justifie l'accès à
  `_max_overflow`/`checkedout`/`checkedin`) ; `SPAStaticFiles.get_response` →
  signature parente `(str, Scope) -> Response` ; `require_admin` → `None`.
  Override mypy `disallow_any_generics` posé.
- [x] `interfaces/api/routers/` (124 occ., 17 fichiers) : tous les
  handlers avec `response_model=` retournent désormais leur BaseModel.
  Pattern retenu (option A de la question Pydantic ci-dessous) :
  `Model.model_validate(dict_du_query_service)` pour les retours
  composites ; constructeur direct `Model(...)` pour les retours
  scalaires (`OkResponse()`, `MergeResponse(...)`). `_: Any = Depends(require_admin)`
  → `_: None` (puisque `require_admin` retourne `None` après
  Phase 2 sur `deps.py`). Handlers sans `response_model` (3 dans
  `journals.py`, 3 dans `docs.py`) typés en `dict[str, Any]` ou
  `list[dict[str, ...]]` faute de modèle adapté. Override mypy
  `disallow_any_generics` posé sur `interfaces.api.routers.*`.
- [x] `interfaces/cli/` : 11 `Any` explicites + 4 `dict` non
  paramétrés corrigés (records DB → `list[dict[str, Any]]`,
  helper `c(text, *styles)` → `(object, *str) -> str`,
  `parse_date(val)` → `object`, `escape_sql(value)` →
  union `str | int | float | bool | list[Any] | dict[str, Any] | None`).
  mypy strict 0 erreur sur la couche.
- [ ] `tests/` : signatures alignées sur les fonctions testées.

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
- **Tests psycopg restants** : si Phase 5 SQLA (Alembic) n'est pas
  faite, le `cur` psycopg subsiste dans `migrate.py`. Cohérent
  avec le périmètre, mais à reconfirmer si Phase 5 dérape.
