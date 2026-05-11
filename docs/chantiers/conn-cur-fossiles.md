# Chantier — Suppression des `conn`/`cur` fossiles

Commencé le 2026-05-11.

## Contexte

Dette héritée du chantier SQLAlchemy : nombreuses fonctions de
`application/` (et probablement `infrastructure/sources/`,
`interfaces/api/routers/`, tests) déclarent un argument
`conn: Connection` ou `cur: Connection` qu'elles n'utilisent **pas**.
Vestige du pattern psycopg où le curseur servait à `cur.execute(...)`
directement. Avec `repo` qui encapsule la connexion, l'argument est
devenu un fossile sur les signatures.

Audit initial dans `application/persons.py` : 13 fonctions sur 16
avec un argument fossile. Présomption d'une situation similaire dans
les autres modules `application/*`.

## Cascade

Beaucoup de `conn`/`cur` *utilisés* le sont uniquement pour les
transmettre à une autre fonction qui ne l'utilise pas non plus. En
supprimant les feuilles, on libère les remontées. Le chantier est
itératif : sweep, propage, re-sweep.

## Stratégie

1. **Audit initial** : pour chaque fonction de `application/*`,
   identifier si `conn`/`cur` est référencé dans le corps.
2. **Sweep itératif** :
   - Supprimer les arguments des feuilles (fonctions qui n'utilisent
     jamais `conn`/`cur` dans leur corps).
   - Adapter tous les call sites (qui ne passent plus l'argument).
   - Re-auditer : certains callers deviennent feuilles à leur tour.
   - Itérer.
3. **Tests adaptés** au passage (les tests appellent souvent les
   use cases avec un `conn`).
4. **Validation continue** : mypy + tests à chaque sweep.

## Hors scope

- Refactor de l'usage interne (continuer à passer `conn` aux repos
  qui en ont besoin par leur `__init__`).
- `infrastructure/sources/*` extracteurs API : les `cur` y sont des
  vrais curseurs psycopg (pas des Connection SA), à voir séparément.

## Phasage

### Phase 1 — Audit complet

- [x] Lister toutes les fonctions de `application/`, `interfaces/api/`,
  `tests/integration/` qui déclarent `conn` ou `cur` mais ne
  l'utilisent jamais dans leur corps. Audit initial : 62 fossiles
  effectifs (53 si on retire les ports `Protocol` et les
  abstract methods, hors faux positifs).

### Phase 2 — Sweep itératif

- [x] Sweep modules `application/*` (commit `cfd4510`) :
  `config.py`, `publishers.py`, `journals.py`, `structures.py`,
  `addresses_countries.py` (28 fonctions).
- [x] Sweep modules `application/*` partie 2 (commit `50d35ec`) :
  `persons.py`, `publications.py`, `authorships/core.py`,
  `authorships/assign_orphans.py` (~30 fonctions). Callers
  patchés par AST en respectant les défs locales (helpers
  `_create_person`, etc.) et les aliases d'imports.
- [x] Sweep finale routers + pipeline (commit `80270ec`) : retrait de
  `conn: Connection = Depends(db_conn_sync)` dans 33 endpoints
  FastAPI (FastAPI résout la cascade via le repo) + 17 helpers
  internes pipeline (`upsert_publisher`, `upsert_journal`,
  `find_publication`, `step1_cross_source`, `step3_name_forms`).

### Phase 3 — Renommage `cur` → `conn`

- [x] (commit `41ff74d`) Renommage AST-driven : 53 paramètres
  `cur: Connection` typés SA mais nommés `cur` par héritage psycopg,
  renommés en `conn` avec leurs références internes. 13 fichiers
  touchés.

### Phase 4 — Validation finale

- [x] mypy : aucune erreur.
- [x] Tests : 1403/1403 OK à chaque étape.
- [x] Restent ~6 fossiles acceptés (mocks `monkeypatch` qui doivent
  matcher la signature de la cible, hook abstrait `summary_stats`).
