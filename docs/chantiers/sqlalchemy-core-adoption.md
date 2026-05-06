# Chantier — Adoption SQLAlchemy Core
Commencé le 2026-05-06.

## État : à exécuter (phase 0 de cadrage à faire en premier)

Décision actée : on adopte SQLAlchemy Core. La porte vers Alembic
reste ouverte et sera réévaluée à la fin du chantier en
coût-bénéfice (cf. section dédiée).

## Pour l'instance Claude qui exécute ce chantier

Tu n'as pas le contexte de la session qui a produit ce chantier. Lis
cette fiche en entier avant de commencer. Trois entrées utiles :

- `docs/architecture.md` — couches DDD, règle de placement des ports,
  exception cross-aggregate `address_repository`. C'est la grille
  qui ne bouge pas.
- `docs/chantiers/audit-cto.md` — origine de la décision, mention en
  Phase 1 (« SQLAlchemy Core : on adopte ou on ferme la porte »).
  Item à cocher avec pointeur vers cette fiche en fin de chantier.
- `ROADMAP.md` §1.4 (« Pas de mini-framework maison ») et §X (ligne
  ~215, mention « SQLAlchemy Core à explorer »). Cette mention sera
  retirée / réécrite en fin de chantier.

Le chantier est à phaser dans le temps : **ne pas tout migrer d'un
seul commit**. Voir « Phasage proposé » plus bas.

## Contexte

Le projet utilise psycopg3 directement, avec deux familles de
constructions SQL :

- **Queries statiques** : la majorité (~80 %). Ex.
  `cur.execute("SELECT id FROM persons WHERE id = %s", (id_,))`.
  Lisibles, paramétrées, sans bug connu.
- **Queries dynamiques** : `infrastructure/db/queries/filters.py`,
  `infrastructure/db/queries/publications/facets.py`
  (`_PublicationFacetsBuilder`, ~500 lignes), listings paginés avec
  filtres variables (`addresses`, `persons/list.py`,
  `publications/list.py`). Pattern actuel : muter une `conditions:
  list[str]` et une `params: list` en parallèle, puis assembler la
  requête finale.

Ce pattern « muter deux listes en parallèle » est un mini-framework
maison déguisé. Il marche mais introduit une classe d'erreurs
runtime (désalignement string ↔ params) et n'est pas composable :
chaque builder est ad hoc. ROADMAP §1.4 anticipait précisément ce
piège.

SQLAlchemy Core remplace ce pattern par le standard de l'écosystème
Python, sans rien renvoyer côté ORM.

## Décision retenue

**Adopter SQLAlchemy Core** (pas l'ORM) comme query builder de
référence pour les queries dynamiques, en coexistence pragmatique
avec du SQL brut là où c'est plus lisible (CTE complexes, opérations
JSON spécifiques à PostgreSQL).

## Périmètre du chantier

**Inclus** :
- Toutes les queries dynamiques (`filters.py`, `*facets.py`,
  listings paginés).
- Repositories (`infrastructure/repositories/*.py`) : les méthodes
  d'écriture comme `update_*_fields` (déjà `dict`-based depuis le
  chantier ports-cleanup) deviennent `update(t).values(**fields)`.
- Pool de connexions : remplacer `AsyncConnectionPool` psycopg par
  `AsyncEngine` SQLAlchemy (driver psycopg3 conservé sous le
  capot — `postgresql+psycopg://`).

**Inclus mais à valider en phase 0** :
- Description des tables côté Python : MetaData explicite (pattern
  standard) vs reflection au démarrage. Recommandation initiale :
  MetaData explicite, déclarée dans `infrastructure/db/tables.py`,
  cohérent avec `schema.sql`. Synchronisation par revue manuelle à
  chaque migration (peu fréquent).

**Exclus** :
- ORM SQLAlchemy (mappers, sessions identity-map, `relationship()`,
  lazy loading). Hors scope. Le domaine reste pur (value objects
  dans `domain/`), aucun mapping objet-table.
- Migrations Alembic — décision séparée, voir section dédiée.
- `infrastructure/db/migrate.py` — reste tel quel (141 lignes
  lisibles, aucune raison de toucher).
- `interfaces/cli/` — les scripts one-shot continuent d'utiliser
  les repos via les factories ; pas de réécriture spécifique.

## Décisions de cadrage

### 1. Engine de bout en bout, pas builder pur

Deux options :
- **A** — SQLAlchemy uniquement comme générateur de string SQL ;
  on continue à exécuter via `cur.execute(str_sql, params)`.
- **B** *(retenu)* — SQLAlchemy `AsyncEngine` + `AsyncConnection`
  remplace le pool psycopg. `await conn.execute(stmt)` partout.

Raisonnement : en partant de zéro, B est le pattern standard. Il
ouvre proprement la voie à Alembic (qui s'attend à un Engine), il
unifie le typage des Result et il évite un mode hybride bancal. Le
driver reste psycopg3 (`postgresql+psycopg://`), donc aucune
régression de perf/feature côté DB.

### 2. Coexistence Core / SQL brut

Règle : **Core par défaut, SQL brut quand il est strictement plus
lisible**. Critères concrets pour basculer en SQL brut :

- CTE imbriquées (`WITH RECURSIVE …` notamment) — déjà présentes
  dans `infrastructure/perimeter.py`.
- Opérations JSON PostgreSQL avancées (`->`, `->>`, `#>>`,
  `jsonb_set`, etc.) — déjà présentes dans `subjects.py`,
  `staging`, etc.
- Window functions complexes (`ROW_NUMBER() OVER (PARTITION BY …)`).

Dans tous les cas, l'exécution passe par
`AsyncConnection.execute(text(sql), params)` (bind paramétré),
jamais par interpolation string.

### 3. Description des tables (MetaData)

Recommandation initiale : MetaData déclaré à la main dans
`infrastructure/db/tables.py`. Avantages :
- Autocomplete IDE (`Person.c.id`, `Person.c.name`).
- Typage statique des colonnes.
- Pas de couplage runtime au schéma (pas de reflection au
  démarrage).

Inconvénient assumé : duplication entre `schema.sql` et
`tables.py`. Mitigé par la revue manuelle à chaque migration
(rythme : ~1/mois) et par un test d'intégration qui vérifie la
cohérence (cf. validation).

À confirmer en phase 0 — option fallback si jugée trop lourde :
reflection au démarrage avec cache.

### 4. Le domaine reste pur

`domain/` ne connaît pas SQLAlchemy. Les value objects (`DOI`,
`ORCID`, `IdRef`, `StructureApiIds`, etc.) restent intacts. Les
ports (`domain/ports/*.py`, `application/ports/*.py`) restent des
`Protocol` sans dépendance externe.

SQLAlchemy vit exclusivement dans `infrastructure/`.

### 5. Pas de session ORM, pas d'unit of work

Pour les transactions, on reste sur le pattern actuel
(`AsyncConnection.begin()` / context manager). Pas d'introduction
de `Session.commit()` / `flush()`. Ce projet n'a pas la complexité
qui justifierait une session.

## Phasage proposé

### Phase 0 — Cadrage et POC (avant tout commit massif)

- Mise en place de `infrastructure/db/engine.py` (AsyncEngine basé
  sur `postgresql+psycopg://`, paramètres pool équivalents à
  l'actuel : `pool_size=db_pool_min`, `max_overflow`,
  `pool_pre_ping`, etc.). Ne pas brancher encore.
- Création de `infrastructure/db/tables.py` avec MetaData et
  **2-3 tables pilotes** seulement : ex. `perimeters`, `config`,
  `structures`. Vérifier que l'autocomplete IDE fonctionne et que
  les types ressortent correctement.
- POC sur **un seul module pilote** : `application/ports/config.py`
  + `infrastructure/db/queries/config.py` + `application/config.py`
  → tout le flux `update_config_value` re-câblé en SQLAlchemy Core,
  AsyncEngine en parallèle de l'ancien pool. Tests d'intégration du
  module pilote doivent passer.
- Décision finale sur MetaData explicite vs reflection.
- Décision finale sur la stratégie de remplacement du pool
  (basculer brutal ou cohabiter pendant la migration ?).

**Livrable phase 0** : un patch isolé qui prouve que la chaîne
fonctionne sur un module pilote, plus une mise à jour de cette
fiche avec les décisions tranchées.

### Phase 1 — Migration des queries dynamiques

Ce sont les queries qui justifient le chantier (le gain est
maximal là). Ordre d'attaque :

1. `infrastructure/db/queries/filters.py` — refondre l'API en
   retournant des fragments SQLAlchemy composables au lieu de
   muter `(conditions, params)`.
2. `infrastructure/db/queries/publications/facets.py`
   (`_PublicationFacetsBuilder`) — le plus complexe ; vérifier que
   la lisibilité gagne réellement.
3. Listings paginés : `addresses.py`, `persons/list.py`,
   `publications/list.py`, `journals.py`, `publishers.py`,
   `structures.py`.
4. `subjects.py` — partiellement (queries dynamiques uniquement,
   les opérations JSON spécifiques restent en SQL brut).

**À chaque étape** : commit séparé, tests d'intégration verts, pas
de mélange ancien/nouveau pattern dans un même fichier.

### Phase 2 — Migration des repositories d'écriture

Repositories `infrastructure/repositories/async_*_repository.py` :
les méthodes d'écriture (`update_*_fields`, `create_*`,
`delete_*`, etc.). C'est mécanique, aucun pattern dynamique :
gain principalement en cohérence et en futur-proofing pour
Alembic.

Ordre suggéré : par agrégat (un repo = un commit), en commençant
par les plus simples (Perimeter, Config) pour valider le pattern.

### Phase 3 — Migration des queries statiques restantes

Queries SELECT/INSERT/UPDATE/DELETE statiques sans construction
dynamique. Gain principal : uniformité du codebase. À faire au
fil de l'eau, pas en bloc.

Critère d'arrêt : si un fichier reste plus lisible en SQL brut
(CTE complexe, JSON ops avancés), on le laisse en `text()` et on
documente le choix dans une note locale.

### Phase 4 — Bascule du pool psycopg vers AsyncEngine

Une fois toutes les queries migrées, remplacer définitivement
`AsyncConnectionPool` psycopg par AsyncEngine SQLAlchemy. Côté
sync (pipeline) : `Engine` SQLAlchemy synchrone, en remplacement
de l'usage actuel.

À ce stade, plus aucun `cur.execute(...)` ne devrait subsister.

### Phase 5 — Décision Alembic

Voir section dédiée ci-dessous. À traiter une fois Phase 4
terminée (avant, c'est prématuré).

## Alembic — porte ouverte

Une fois SQLAlchemy Core en place avec MetaData explicite, le coût
d'adoption d'Alembic devient mineur (Alembic se branche
naturellement sur la MetaData SQLAlchemy). Question à reposer en
fin de Phase 4 :

**Bénéfices Alembic** :
- Migrations auto-générées par diff entre MetaData et schéma DB
  (`alembic revision --autogenerate`). Plus besoin de rédiger les
  `ALTER TABLE` à la main.
- Downgrades (`alembic downgrade -1`) — utile si la DSI les exige
  ou si nous-mêmes en avons besoin un jour.
- Standard de l'écosystème Python.

**Coûts** :
- Réécriture des 21+ migrations existantes au format Alembic
  (mécanique mais long).
- Adoption d'un outil supplémentaire à comprendre pour un
  reprenant.
- Notre `migrate.py` actuel (141 lignes) est extrêmement simple
  et fait son travail.

**Critère de décision** : la motivation principale serait la
génération automatique des migrations à partir des diffs MetaData.
Si on garde MetaData explicite (donc on revoit la MetaData à chaque
migration manuelle), l'auto-génération est un vrai gain. Si on part
sur reflection, Alembic perd l'essentiel de son intérêt.

À trancher en Phase 5 avec le recul de l'utilisation réelle.

## Validation

Critères pour considérer une phase comme terminée :

- Tous les tests d'intégration passent
  (`pytest tests/integration/ -v`).
- `mypy` passe sans nouveau `ignore`.
- `lint-imports` passe (les frontières DDD ne sont pas violées —
  notamment `domain/` ⊥ SQLAlchemy).
- Pas de régression de perf perceptible sur les endpoints API
  critiques (à mesurer ponctuellement avec un timing simple sur
  `/api/publications` avec filtres).
- Pour Phase 0 : un test d'intégration spécifique vérifie la
  cohérence MetaData ↔ schéma réel
  (cf. `infrastructure/db/tables.py` introspecté contre la DB).

## Hors scope de ce chantier

- ORM SQLAlchemy. Définitivement non.
- Réécriture de `domain/` (value objects, ports). Tout reste pur.
- Migration de `interfaces/cli/` à un nouveau pattern. Les CLI
  utilisent les repos comme aujourd'hui.
- Modification du pattern de transaction (savepoints,
  context managers actuels). On garde tel quel.
- Refonte de `infrastructure/perimeter.py` (CTE récursive). Ça
  reste en `text()`.
- Création de modèles Pydantic-SQLAlchemy. Pydantic vit côté API
  (`interfaces/api/models.py`), pas couplé au schéma.

## Lien avec les autres chantiers

- `docs/chantiers/audit-cto.md` (Phase 1, item « SQLAlchemy
  Core ») — ce chantier clôt cet item.
- `docs/chantiers/sync-async-deduplication.md` — indépendant, mais
  les deux chantiers convergent : si la convergence sync/async est
  faite avant celui-ci, on a moins de fichiers à migrer ; si elle
  est faite après, le chantier sync/async sera trivialement plus
  simple parce que SQLAlchemy fournit `Engine` (sync) et
  `AsyncEngine` (async) naturellement.
- `docs/chantiers/ports-cleanup.md` (terminé) — ce chantier-ci
  consomme directement le résultat (les `update_*_fields` reçoivent
  déjà un `dict`, prêt à être passé à `update(...).values(**dict)`).
