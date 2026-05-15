# Chantier — Typage strict des projections et DTOs

## Contexte

Le chantier `CODE_chasse-aux-any` a verrouillé `disallow_any_explicit` et `disallow_any_generics` globalement. Subsistent quatre familles de types « bâtards » documentés et désactivés par module dans `pyproject.toml` :

- **`Row[Any]`** (28 occ.) — surtout signatures `process_work` des normalizers et retours de queries SA `.one()/.all()`. Le `[Any]` neutralise la vérification du contenu de la row alors qu'on sait quels champs sont sélectionnés.
- **`list[dict[str, Any]]`** (130 occ.) — mélange hétérogène : listes de records DB hydratés en dict, batchs SQL `executemany` à valeurs hétérogènes, listes JSON externes, retours de query services API (`infrastructure/db/queries/*` consommés par les routers FastAPI).
- **`fields: dict[str, Any]`** (6 occ.) — partial updates côté ports repository (`update_*_fields`). Les colonnes possibles sont connues du port mais pas exprimées dans le type.
- **Pydantic `BaseModel` dans `interfaces/api/models.py`** — DTOs de retour API. Les query services renvoient `dict[str, Any]`, les routers font `Model.model_validate(...)` pour fabriquer le `BaseModel` correspondant au `response_model` (option A retenue par `CODE_chasse-aux-any` Phase 2.4). Option C écartée à l'époque : faire en sorte que les query services renvoient directement des DTOs typés.

Le chantier `CODE_rich-domain-model` Phase 8 hydrate les **aggregates roots** (find_by_id → entité riche). Ce chantier-ci traite **tout le reste** : projections délibérément non hydratées, partial updates, DTOs de retour API.

## Décisions

À instruire au démarrage. Hypothèses de travail :

1. **Pas une hydratation systématique** : si une méthode retourne 2-3 colonnes pour usage immédiat, pas la peine de fabriquer une entité — un `NamedTuple` ou `TypedDict` suffit. Le critère « entité riche vs projection » se tranche au cas par cas selon ce que le caller en fait.
2. **Pattern de remplacement selon la couche** :
   - **Retours consommés par routers FastAPI** (`application/ports/api/*_queries.py`) : **Pydantic `BaseModel`**, parce que FastAPI a besoin du `response_model` pour la validation et la sérialisation JSON.
   - **Tout le reste** (pipeline, repos d'aggregate, batchs SQL, partial updates) : `TypedDict` / `NamedTuple` / `dataclass(frozen)` selon le cas. `NamedTuple` immutable et indexable, `TypedDict` zero-cost (pas d'objet créé), `dataclass` plus expressif (defaults, validators).
3. **DTOs API — déplacement structurel** : les Pydantic `BaseModel` actuels dans `interfaces/api/models.py` sortent vers `application/dtos/` (placement à trancher : global `application/dtos/` ou colocation par feature `application/persons/dtos.py`, etc.). Les Protocols `application/ports/api/*` retournent ces DTOs au lieu de `dict[str, Any]`. Les adapters `infrastructure/db/queries/Pg*Queries` instancient les DTOs côté infra. Les routers ne font plus de `model_validate` — ils propagent directement le DTO renvoyé par le query service.
4. **Partial updates** : `TypedDict(total=False)` par port (`JournalUpdateFields`, `PerimeterUpdateFields`, `PublisherUpdateFields`, `StructureUpdateFields`, `StructureNameFormUpdateFields`). Absorbé depuis `rich-domain-model` Phase 8.
5. **Batchs SQL hétérogènes** (`normalize_wos` notamment) : décomposer par batch (`WosAddressBatch`, `WosAuthorshipBatch`, …) avec un dataclass ou TypedDict par contrat.

## Phasage

À instruire. Esquisse :

- **Audit** : inventaire des 28 `Row[Any]` + 130 `list[dict[str, Any]]` + 6 `fields: dict[str, Any]` + ~30 modèles `BaseModel` de `interfaces/api/models.py`, classifiés par catégorie (record DB interne / batch SQL / liste JSON / partial update / retour API) et par fréquence d'usage.
- **Décision de pattern** par catégorie (cf. Décisions ci-dessus).
- **Sweep par couche** : domain ports → application ports → infrastructure adapters → application services. Le déplacement des DTOs Pydantic est un sous-sweep dédié (changement de package + adaptation des Pg*Queries et routers).
- **Retrait progressif des modules** correspondants de l'override de désactivation `disallow_any_explicit = false` dans `pyproject.toml`. Suppression d'une bonne partie de l'override « `interfaces.api.models` + records DB » au passage.

## Bénéfices attendus

- Typage fort de bout en bout (query service → router → réponse HTTP) sans `dict[str, Any]` intermédiaire.
- Typage statique des partial updates (les callers sont contraints aux colonnes valides du port).
- Sortie d'`Any` sur l'essentiel des modules encore en override.

## Questions ouvertes

- **`Row[Any]` vs `Row[tuple[type1, type2, ...]]`** : la version paramétrée est précise mais fragile (changement de SELECT → type cassé sans erreur runtime). Décision pragmatique probable : `NamedTuple` par requête plutôt que `Row` paramétré.
- **Coût/bénéfice par cas** : certains `Row[Any]` ne valent pas le typage (résultat lu une fois sur place, `.scalar_one()`). Un critère « > 2 colonnes ou propagé hors de la fonction » est probablement le bon seuil.
- **Placement des DTOs déplacés** : `application/dtos/` global vs colocation par feature (`application/persons/dtos.py`, `application/publications/dtos.py`, …). Le second est plus cohérent avec le découpage actuel par feature de `application/` ; le premier rassemble le contrat API en un point.
- **Periodicité du sweep** : un seul gros refactor par catégorie, ou progressif par feature (Pg*Queries persons d'abord, puis publications, …) ? Probablement progressif pour limiter le blast radius.

## Liens

- Préalable : `2026-05-15_CODE_chasse-aux-any.md` (verrou global posé, modules avec `Any` documentés en désactivation).
- Articulation avec `CODE_rich-domain-model.md` Phase 8 : la Phase 8 hydrate les aggregates roots (charge `Entity` au lieu de `dict[str, Any]` sur les `find_by_id`). Ce chantier-ci traite tous les autres retours non typés (projections minimales, batchs, partial updates, DTOs API).
