# Chantier — Rapatriement des helpers d'extraction hors de `domain/`

Commencé le 2026-05-27

## Contexte

5 fichiers `domain/sources/<source>_extract.py` (HAL, OpenAlex, ScanR, theses, WoS, 411 lignes) introduits par la migration des extracteurs vers `application/pipeline/extract/` (commits du 2026-05-20).

Ils contiennent du savoir adapter (delays HTTP, syntaxe Solr, noms de champs JSON par source) et quelques heuristiques d'orchestration (`count_full_fetch_pages`, `choose_extraction_mode`). **Rien de business**. La motivation du dépôt en `domain/` est documentée dans les docstrings : « la couche est partagée entre l'orchestrateur applicatif et l'adapter infra, qui ne peuvent pas s'importer mutuellement (couches plates) ».

C'est une réponse pragmatique à une contrainte réelle de l'archi en couches, mais elle pollue le domain et le déstabilise comme « zone de partage » au lieu de « cœur métier ».

## Pattern cible

Les helpers vivent dans `infrastructure/sources/<source>/` :
- **Constantes opérationnelles** (`DELAY`, `PER_PAGE`) : elles existent déjà dans le registre infra `infrastructure/sources/api_limits.py` (« centralise les rate limits pour éviter la dérive entre scripts »). L'adapter les consomme depuis là — pas de duplication, pas de copie privée dans le module adapter. « Jamais exposées » s'entend au sens fort : elles ne franchissent jamais la frontière vers `application/` (le port n'expose pas de `delay_s`). L'adapter se rate-limite tout seul entre deux appels HTTP — l'orchestrateur n'a aucune raison d'ordonnancer un `time.sleep`, c'est du savoir adapter qui n'a pas à fuiter. (Avant ce chantier, les `time.sleep(DELAY)` vivaient dans l'orchestrateur applicatif, seconde forme de pollution corrigée ici.)
- **Parsing JSON et build_query** : méthodes de l'adapter (`adapter.extract_id(doc)`, `adapter.build_query(years, since)`), exposées via le port.

Les heuristiques d'orchestration vont dans `application/pipeline/extract/<source>_helpers.py` (pas adapter knowledge, mais orchestrateur knowledge).

L'orchestrateur applicatif appelle les méthodes du port (Protocol) au lieu d'importer des fonctions depuis `domain/`. La règle « app ne connaît pas le format JSON HAL ni le rate-limit HAL » est ainsi rétablie.

## Phases

### Phase 1 — Pilote HAL

- [x] Ajouter méthodes au port `HalExtractAdapter` : `extract_id(doc)`, `extract_doi(doc)`, `build_query(years, since)`, `per_page_for(collection_code)`. Pas de `delay_s` exposé — l'adapter se rate-limite seul.
- [x] Implémenter ces méthodes dans `PgHalExtractAdapter` (`infrastructure/sources/hal/extract_hal.py`). Rate-limit internalisé via `_get` (compteur monotonic, ≥ `HAL_DELAY` entre deux GET), `HAL_DELAY`/`hal_per_page_for` lus depuis `api_limits`.
- [x] Migrer `count_full_fetch_pages` et `choose_extraction_mode` vers `application/pipeline/extract/hal_helpers.py`.
- [x] Mettre à jour l'orchestrateur `application/pipeline/extract/extract_hal.py` : appels à l'adapter (et à `hal_helpers`), suppression de `import time` et des `time.sleep(HAL_DELAY)`.
- [x] Migrer les tests `test_hal_extract.py` → `tests/unit/application/pipeline/extract/test_hal_helpers.py` (heuristiques) + `tests/unit/infrastructure/sources/hal/test_extract_hal.py` (parsing/requête/pagination). Fixture `no_sleep` supprimée du test d'intégration (devenue inutile).
- [x] Supprimer `domain/sources/hal_extract.py`.
- [x] Valider : mypy + lint-imports + tests (pre-commit).

### Phase 2 — Application aux 4 autres sources

Même esprit que le pilote, une source = un commit. **Nuance constatée sur OpenAlex** : le parsing y est partagé par deux modules infra (l'adapter extract *et* `fetch_missing_doi`). Le transformer en méthodes d'adapter dupliquerait → il vit dans un module infra neutre (`infrastructure/sources/<source>/parsing.py`), et l'adapter n'expose via le port que ce que l'orchestrateur consomme réellement (ici `extract_id` seul ; `extract_doi` reste interne car aucun orchestrateur ne l'appelle). Vérifier le partage source par source avant de choisir « méthode d'adapter » vs « module partagé ».

- [x] OpenAlex — `parsing.py` (extract_id/extract_doi partagés avec `fetch_missing_doi`), `extract_id` au port, rate-limit interne, `OPENALEX_DELAY` via `api_limits`.
- [ ] ScanR
- [ ] theses.fr
- [ ] WoS

### Phase 3 — Nettoyage final

- [ ] Confirmer que `domain/sources/` ne contient plus que du vrai domain (`openalex.py` avec `OpenalexLocation`, `is_theses_fr_location`, etc., qui relèvent du métier — à reprendre si besoin dans un chantier séparé).
- [ ] Mettre à jour `docs/architecture.md` si le partage app/infra est documenté quelque part comme « via domain ».

## Liens

- Commits d'origine : `f56c9b31` (OpenAlex), `6d5dfa3d` (HAL), `f9263704` (WoS), `221a2dba` (ScanR), `e4123314` (theses.fr), tous du 2026-05-20.
