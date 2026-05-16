# Chantier — Couverture de tests : viser 80 %

## Contexte

Seuil `fail_under` aujourd'hui = 70 % (`pyproject.toml`,
`[tool.coverage.report]`). La couverture brute mesurée à la dernière
campagne est **71 %** sur 11 920 lignes (cf. `python -m pytest tests/
--cov`). On veut pousser à **80 %** avant transmission DSI, sans
écrire de tests pour le plaisir des tests : la cible est la valeur
de garantie, pas le pourcentage.

Deux poches très en dessous de la moyenne, identifiées au dernier
rapport :

1. **Extracteurs API** (`infrastructure/sources/*/extract_*.py`,
   `fetch_missing_doi.py`, `fetch_missing_hal_id.py`,
   `refetch_truncated.py`) — 14 % à 39 % selon les modules.
2. **Routers admin / annexes** sous les 60 % : `docs` (22 %),
   `admin_pipeline` (32 %), `admin_duplicates` (43 %), `journals`
   (48 %), `perimeters` (50 %), `subjects` (50 %), `auth` (56 %),
   `admin_person_duplicates` (59 %).

Le reste de la base (domain, application, queries, repositories,
models Pydantic) est entre 84 % et 100 %.

## Décisions

### 1. Exclure les extracteurs API de la couverture

Les modules suivants sortent du calcul (`[tool.coverage.run] omit`) :

- `infrastructure/sources/hal/extract_hal.py`
- `infrastructure/sources/hal/fetch_missing_hal_id.py`
- `infrastructure/sources/hal/fetch_missing_doi.py`
- `infrastructure/sources/openalex/extract_openalex.py`
- `infrastructure/sources/openalex/fetch_missing_doi.py`
- `infrastructure/sources/openalex/refetch_truncated.py`
- `infrastructure/sources/scanr/extract_scanr.py`
- `infrastructure/sources/scanr/fetch_missing_doi.py`
- `infrastructure/sources/theses/extract_theses.py`
- `infrastructure/sources/wos/extract_wos.py`
- `infrastructure/sources/wos/fetch_missing_doi.py`
- `infrastructure/sources/crossref/fetch_missing_doi.py`

**Pourquoi.** Ces modules sont des adapters HTTP : `httpx.get()` →
parsing JSON spécifique à l'API source → mapping vers le schéma
staging. Trois propriétés rendent les tests unitaires à faible ROI :

- **Le code change quand l'API source change.** Or les régressions
  qu'on craint (champ renommé, structure imbriquée différente, code
  HTTP nouveau) ne se voient qu'avec une réponse réelle de l'API. Des
  fixtures figées dans le repo donnent une illusion de couverture
  sans tester ce qui casse en vrai.
- **Le code utile est ailleurs.** La normalisation (`application/
  pipeline/normalize/normalize_*.py`) est testée par les tests
  d'idempotence (`tests/integration/pipeline/idempotence/`) : on
  insère un raw_data JSON dans staging et on vérifie la sortie. C'est
  le bon niveau pour valider notre logique métier sans simuler httpx.
- **Validation = run réel.** Le pipeline tourne en complet
  périodiquement ; un changement d'API casse l'extraction de manière
  immédiatement visible (count anormal sur la source, erreur de
  parsing). C'est la boucle de feedback qui couvre ces modules.

Les modules `infrastructure/sources/base.py` (38 %) et
`infrastructure/sources/common.py` (86 %) **restent dans le scope** :
ce sont des helpers partagés (retry, pagination, normalisation
d'erreurs) qui méritent des tests unitaires — pas du parsing
spécifique.

### 2. Couvrir les routers admin sous 70 %

Tests d'intégration FastAPI (`TestClient`), même pattern que les
routers déjà à 100 % (`addresses`, `publishers`, `stats`,
`structures`). Trois sous-objectifs :

- **Lecture** : endpoint répond 200 sur un état nominal.
- **Erreur** : 404 / 400 sur les cas explicites du router.
- **Effet de bord** : pour les POST/PUT/PATCH/DELETE, vérifier l'état
  base après l'appel.

Pas de mock sur l'infra DB : les tests d'intégration tournent contre
`bibliometrie_test` (cf. `tests/integration/conftest.py`).

### 3. Cible chiffrée

Une fois (1) appliqué, recalculer le `fail_under`. Estimation à la
louche : retirer ~1100 lignes d'extracteurs essentiellement non
couvertes fait remonter mécaniquement la couverture à ~78-79 %.
(2) doit donc apporter le delta restant pour franchir 80 %.

Une fois le palier 80 % atteint, on suit la doctrine actuelle :
seuil progressif jamais à la baisse.

## Phasage

### Phase 1 — Exclusion des extracteurs

- [ ] Ajouter les 12 fichiers à `[tool.coverage.run] omit` dans
  `pyproject.toml`, regroupés sous un commentaire explicatif (renvoi
  vers cette fiche).
- [ ] Recalculer la couverture, bumper `fail_under` au plus haut
  palier rond ≤ couverture mesurée (probablement 78 %).
- [ ] Mettre à jour `docs/architecture.md` (section Tests) et
  `README.md` (commande pytest cov) avec le nouveau seuil.

### Phase 2 — Routers admin sous 70 %

Par ordre de priorité (impact UI puis surface) :

- [ ] `interfaces/api/routers/admin_pipeline.py` (32 %) — endpoints
  de relance / consultation de runs. Pages `/admin/pipeline`.
- [ ] `interfaces/api/routers/admin_duplicates.py` (43 %) — gestion
  des doublons de publications. Page `/admin/duplicates`.
- [ ] `interfaces/api/routers/journals.py` (48 %) — CRUD journaux
  (mode admin).
- [ ] `interfaces/api/routers/perimeters.py` (50 %) — CRUD
  perimeters.
- [ ] `interfaces/api/routers/subjects.py` (50 %) — facettes /
  recherche subjects.
- [ ] `interfaces/api/routers/docs.py` (22 %) — *à arbitrer* : si le
  router est en passe d'être retiré ou réécrit DSI-side, ne pas y
  investir. Sinon, l'inclure en dernier.

### Phase 3 — Quick-wins ciblés

Optionnel si Phase 1+2 a déjà fait passer le seuil :

- [ ] `interfaces/api/routers/admin_person_duplicates.py` (59 %)
- [ ] `interfaces/api/routers/auth.py` (56 %) — dépend du contrat
  CAS final ; pas prioritaire avant que la doctrine d'auth soit
  tranchée par la DSI.
- [ ] `interfaces/api/routers/hal_problems.py` (63 %)
- [ ] `infrastructure/sources/base.py` (38 %) — helpers de retry /
  pagination, tests unitaires (pas d'I/O réseau).

## Questions ouvertes

- **Faut-il tester les extracteurs *du tout* ?** Avec l'exclusion,
  zéro test unitaire sur ces 12 fichiers. La sécurité repose
  entièrement sur les runs de pipeline + les tests de normalisation
  en aval. Si on veut une garantie sur le format des réponses
  (snapshot de l'API à un instant T), on peut ajouter quelques tests
  `respx` ciblés (1-2 par source) sans rentrer dans la couverture —
  marqués `@pytest.mark.snapshot` ou équivalent. À trancher au
  démarrage de la Phase 1, pas indispensable.
- **Router `docs` retiré ou conservé ?** Le frontend actuel disparaît
  à la transmission. Si la doc consultable côté admin est jugée
  Laura-only (et donc retirée avec le frontend), ne pas couvrir.
  Sinon, la DSI réécrira un router équivalent et nos tests serviront
  de spec — à inclure.
- **Tests d'auth** : conditionner à la décision DSI sur le
  remplacement du JWT actuel par CAS. Tant que ce n'est pas tranché,
  laisser auth.py à 56 % sans investir.
