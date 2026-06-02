# Chantier — Adoption d'Alembic

Commencé et terminé le 2026-05-11

## Contexte

Suite du chantier `sqlalchemy-core-adoption.md` (Phase 5). SQLAlchemy Core est désormais adopté dans tout le code applicatif, et la MetaData explicite vit dans `infrastructure/db/tables.py` (25 tables). Le coût d'adoption d'Alembic est donc minime — Alembic se branche naturellement sur cette MetaData.

L'enjeu : remplacer le système maison (`infrastructure/db/migrate.py` + 23 fichiers SQL versionnés + table `schema_migrations`) par Alembic, et bénéficier de `alembic revision --autogenerate` pour les migrations futures.

## Décisions de cadrage

- **Baseline = `op.execute(schema.sql)`** : la première migration Alembic copie le contenu de `schema.sql` (snapshot pg_dump exhaustif) dans son `upgrade()`. Garantit qu'une base bootstrappée via `alembic upgrade head` est identique à la prod (vues, triggers, enums, fonctions inclus — ce que la MetaData seule ne couvre pas).
- **Décommissionnement complet de `migrate.py`** : suppression du fichier, des 23 migrations SQL, de la table `schema_migrations`. Le `--dump-schema` est extrait dans un script dédié `infrastructure/db/dump_schema.py`.
- **Pas de branche dédiée** : commits directs sur master en ff.

## Phase 1 — Préparation

- [x] Vérifier que `schema.sql` est à jour vs base actuelle
  (`pg_dump --schema-only` + diff sémantique) — diff vide hors tokens
  `\restrict` aléatoires
- [x] Ajouter `alembic==1.18.0` à `pyproject.toml`, `uv sync`

## Phase 2 — Initialisation Alembic

- [x] `alembic init alembic` → crée `alembic/` + `alembic.ini`
- [x] Adapter `alembic/env.py` : `target_metadata = metadata`, URL
  construite depuis `infrastructure.settings`
- [x] Adapter `alembic.ini` : `file_template` avec préfixe date,
  URL retirée (gérée par env.py)

## Phase 3 — Baseline (squash)

- [x] Créer `alembic/versions/<rev>_baseline.py` (charge le SQL depuis
  `0001_baseline.sql` à côté pour garder le .py lisible)
- [x] Filtrer `schema.sql` (retirer `\restrict`/`\unrestrict` psql et
  les `SET` de session qui vident le `search_path`)
- [x] Valider sur base vierge : `createdb bibliometrie_alembic_test`,
  `DB_NAME=... alembic upgrade head`, `pg_dump --schema-only` puis
  diff avec la base actuelle → diff sémantique vide (seuls écarts :
  tokens `\restrict` aléatoires et table `alembic_version` propre à
  Alembic)
- [x] Valider `alembic downgrade base` → reset propre (recréation
  manuelle de `alembic_version` dans le downgrade pour éviter qu'Alembic
  plante sur son DELETE final)

## Phase 4 — Bascule de la base dev locale

- [x] L'utilisatrice : `alembic stamp head` sur la base dev (marque
  la baseline appliquée sans la rejouer)
- [x] L'utilisatrice : `DROP TABLE schema_migrations`

## Phase 5 — Décommissionnement

- [x] Supprimer `infrastructure/db/migrations/*.sql` (23 fichiers)
- [x] Supprimer `infrastructure/db/migrate.py`
- [x] Créer `infrastructure/db/dump_schema.py` (équivalent du
  `--dump-schema`)
- [x] `conftest.py` : bascule sur `alembic upgrade head` au lieu de
  lire `schema.sql` (Alembic devient unique source de vérité ;
  option B retenue après discussion). `env.py` étendu pour accepter
  une URL surchargée via config.
- [x] **Hors périmètre, fix au passage** : `tables.py.source_persons`
  avait encore `last_name`/`first_name` (migration 022 appliquée en
  DB mais MetaData oubliée — masqué jusqu'ici par un `schema.sql`
  désynchronisé). Test `test_all_metadata_columns_exist_in_db` à
  nouveau vrai.
- [x] **Hors périmètre, fix au passage** : 4 tests dans
  `test_extract_hal_adaptive` cassés depuis sqla Phase 4 (signature
  cursor → SA Connection non répercutée côté tests), adaptés.

## Phase 6 — Documentation

- [x] `CLAUDE.md` : nouveau workflow (`alembic upgrade head`,
  `alembic revision --autogenerate -m "..."`, `dump_schema`)
- [x] `README.md`, `CONTRIBUTING.md`, `docs/architecture.md`,
  `docs/exploitation.md` : références à `migrate.py` remplacées
- [x] Phase 5 de `2026-05-11_sqlalchemy-core-adoption.md` déléguée
  à cette fiche (déjà fait par l'utilisatrice lors du renommage)
- [x] `alembic/README` : workflow Alembic (créer / relire / appliquer
  / rollback / dump_schema, cas particulier de la baseline)

## Phase 7 — Tests finaux

- [x] Suite complète (`pytest tests/ -v`) — 1403/1403
- [x] Smoke test `--autogenerate` : a révélé 7 tables manquantes dans
  la MetaData (héritage du chantier sqla-core qui ne les avait pas
  toutes couvertes) ainsi que tous les Index, UniqueConstraints,
  CheckConstraints et column comments. Dette remboursée en une
  passe : 85 indexes, 23 UC, 4 CC, ~10 comments ajoutés à
  `tables.py`. `--autogenerate` produit maintenant un diff vide.
  - Outil one-shot utilisé pour générer les déclarations :
    `sqlacodegen --generator tables` (5 index sur expressions
    `md5/lower/normalize_name_form` complétés à la main).
- [x] `env.py` : `include_object` configuré pour skipper les
  `foreign_key_constraint` reflétées (la MetaData ne déclare pas les
  FK — pattern délibéré, query-building only).
