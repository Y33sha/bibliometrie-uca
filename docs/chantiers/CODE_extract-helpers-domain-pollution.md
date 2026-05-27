# Chantier — Rapatriement des helpers d'extraction hors de `domain/`

Commencé le 2026-05-27

## Contexte

5 fichiers `domain/sources/<source>_extract.py` (HAL, OpenAlex, ScanR, theses, WoS, 411 lignes) introduits par la migration des extracteurs vers `application/pipeline/extract/` (commits du 2026-05-20).

Ils contiennent du savoir adapter (delays HTTP, syntaxe Solr, noms de champs JSON par source) et quelques heuristiques d'orchestration (`count_full_fetch_pages`, `choose_extraction_mode`). **Rien de business**. La motivation du dépôt en `domain/` est documentée dans les docstrings : « la couche est partagée entre l'orchestrateur applicatif et l'adapter infra, qui ne peuvent pas s'importer mutuellement (couches plates) ».

C'est une réponse pragmatique à une contrainte réelle de l'archi en couches, mais elle pollue le domain et le déstabilise comme « zone de partage » au lieu de « cœur métier ».

## Pattern cible

Les helpers vivent dans `infrastructure/sources/<source>/` :
- **Constantes opérationnelles** (`DELAY`, `PER_PAGE`) : internes à l'adapter, jamais exposées. L'adapter se rate-limite tout seul entre deux appels HTTP — l'orchestrateur n'a aucune raison d'ordonnancer un `time.sleep`, c'est du savoir adapter qui n'a pas à fuiter. (Aujourd'hui les `time.sleep(DELAY)` vivent dans l'orchestrateur applicatif, ce qui est une seconde forme de pollution à corriger.)
- **Parsing JSON et build_query** : méthodes de l'adapter (`adapter.extract_id(doc)`, `adapter.build_query(years, since)`), exposées via le port.

Les heuristiques d'orchestration vont dans `application/pipeline/extract/<source>_helpers.py` (pas adapter knowledge, mais orchestrateur knowledge).

L'orchestrateur applicatif appelle les méthodes du port (Protocol) au lieu d'importer des fonctions depuis `domain/`. La règle « app ne connaît pas le format JSON HAL ni le rate-limit HAL » est ainsi rétablie.

## Phases

### Phase 1 — Pilote HAL

- [ ] Ajouter méthodes au port `HalExtractAdapter` : `extract_id(doc)`, `extract_doi(doc)`, `build_query(years, since)`, `per_page_for(collection_code)`. Pas de `delay_s` exposé — l'adapter se rate-limite seul.
- [ ] Implémenter ces méthodes dans `PgHalExtractAdapter` (`infrastructure/sources/hal/extract_hal.py`). Internaliser le `time.sleep(HAL_DELAY)` à l'intérieur de l'adapter (entre deux appels HTTP), retirer toute notion de delay côté orchestrateur.
- [ ] Migrer `count_full_fetch_pages` et `choose_extraction_mode` vers `application/pipeline/extract/hal_helpers.py`.
- [ ] Mettre à jour l'orchestrateur `application/pipeline/extract/extract_hal.py` : remplacer les imports depuis `domain/sources/hal_extract` par des appels à l'adapter (et à `hal_helpers`). Supprimer les `time.sleep(HAL_DELAY)`.
- [ ] Migrer les tests `tests/unit/domain/sources/test_hal_extract.py` → tests d'infra et d'app selon ce qui a bougé.
- [ ] Supprimer `domain/sources/hal_extract.py`.
- [ ] Valider : mypy + lint-imports + tests.

### Phase 2 — Application aux 4 autres sources

Même pattern, mécaniquement, sur OpenAlex / ScanR / theses / WoS. Une source = un commit.

### Phase 3 — Nettoyage final

- [ ] Confirmer que `domain/sources/` ne contient plus que du vrai domain (`openalex.py` avec `OpenalexLocation`, `is_theses_fr_location`, etc., qui relèvent du métier — à reprendre si besoin dans un chantier séparé).
- [ ] Mettre à jour `docs/architecture.md` si le partage app/infra est documenté quelque part comme « via domain ».

## Liens

- Commits d'origine : `f56c9b31` (OpenAlex), `6d5dfa3d` (HAL), `f9263704` (WoS), `221a2dba` (ScanR), `e4123314` (theses.fr), tous du 2026-05-20.
