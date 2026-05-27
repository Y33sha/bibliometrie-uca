# Plan — Requalification admin sur changement de `journal.type` (règle media)

## Context

La règle de correction « journal de type `media` ⇒ publications en `doc_type = media` » est la première règle dont l'input (`journal.journal_type`) est **éditable côté admin**. Aujourd'hui `PUT /api/journals/{id}` écrit le champ sans aucune conséquence ([application/journals.py:107-127](application/journals.py)) : changer le type ne requalifie pas les publications du journal. On veut pouvoir éditer le type d'un journal dans l'admin et voir ses publications requalifiées, avec une **modale de confirmation** annonçant l'ampleur (« x publications seront requalifiées en *intervention média*. Continuer ? »).

`effective_metadata` reçoit le `Journal` par paramètre : la règle media consomme `journal.journal_type`, donc le journal doit être fourni partout où la correction tourne (refresh pipeline ET requalification admin). C'est le cœur de ce chantier — le paramètre `journal` existe déjà sur `effective_metadata` mais n'est aujourd'hui alimenté par aucun caller.

On reste sur l'archi validée : flux **synchrone** preview → confirm → apply, pas de bus d'événements. L'`audit_log` existant trace l'action.

## Approche

### 1. Domaine — la règle

- `domain/publications/correction.py` : ajouter le membre `JOURNAL_TYPE_MEDIA_TO_MEDIA` à `MetadataCorrectionRule` et une règle dans la cascade `doc_type` : si `journal is not None and journal.journal_type == "media"` ⇒ `Correction("media", JOURNAL_TYPE_MEDIA_TO_MEDIA)`. **Ordre : theses.fr puis dumas priment, media en dernier** — une publication theses.fr/dumas reste thèse/mémoire même si rattachée à un journal typé media.
- `domain/journals/expected.py` : ajouter `"media"` à `EXPECTED_DOC_TYPES_BY_JOURNAL_TYPE["media"]` (sinon la pub corrigée serait signalée incohérente par `is_doc_type_expected_for_journal_type`).

### 2. Application — threader le `Journal` dans le refresh

- `application/publications.py` :
  - `_apply_corrections(sp, *, journal_repo)` : si `journal_repo` et `sp.journal_id`, fetch `journal_repo.find_by_id(sp.journal_id)` et le passer à `effective_metadata(sp, journal=...)`.
  - `refresh_from_sources(pub_id, *, repo, journal_repo, audit_repo=None)` : nouveau paramètre `journal_repo`, propagé à `_apply_corrections`.
- Répercuter `journal_repo` sur les appelants existants de `refresh_from_sources` :
  - boucle stale de [match_or_create_publications.py:321](application/pipeline/publications/match_or_create_publications.py) (et la signature de la phase + wiring `run_pipeline.py`).
  - [merge_by_key.py:68](application/pipeline/publications/merge_by_key.py).
- `find_or_create_journal`/`JournalRepository` exposent déjà `find_by_id(journal_id) -> Journal | None` — rien à ajouter côté lecture journal.

### 3. Application — service de requalification (avec dry-run)

- Nouvelle fonction dans `application/journals.py`, ex. `requalify_publications_for_journal(journal_id, *, prospective_type, dry_run, pub_repo, journal_repo, audit_repo=None) -> int` :
  - récupère les pubs du journal, pour chacune recompute le `doc_type` effectif avec un `Journal` portant `prospective_type`, compte celles dont le `doc_type` changerait ;
  - si `dry_run` : renvoie le compte, n'écrit rien ;
  - sinon : applique le changement de type (déjà fait par `update_journal`) puis `refresh_from_sources` sur chaque pub impactée, et émet un event d'audit `journal.type_requalified` (`{count, new_type, rule}`).
  - réutilise `effective_metadata` (source unique de vérité de la règle) — pas de réimplémentation SQL. Pour la règle media, le compte dégénère en « pubs du journal dont `doc_type != 'media'` ».
- `JournalRepository` : ajouter `find_publication_ids_by_journal_id(journal_id) -> list[int]` (n'existe pas ; la fiche le prévoyait).

### 4. API

- `interfaces/api/routers/journals.py` :
  - **Preview** : `GET /api/journals/{id}/type-change-impact?new_type=media` → `{ "count": N }` (appelle le service en `dry_run=True`).
  - **Apply** : déclencher la requalification quand `PUT /api/journals/{id}` change `journal_type`. Soit dans `update_journal` (comparer ancien/nouveau type, requalifier si différent), soit via un flag `requalify` du body confirmé par la modale. Recommandé : requalifier dans la transaction du PUT quand le type change, + audit.
- Modèles Pydantic dédiés dans `interfaces/api/models/journals.py` (pas de `body: dict`).

### 5. Frontend — la modale

- `interfaces/frontend/src/routes/admin/journals/+page.svelte` : le modal d'édition a déjà un `<select journal_type>` (ligne 170) et un `save()` (ligne 61-67). Au save, si `journal_type` a changé : appeler le preview, afficher une modale de confirmation « x publications seront requalifiées en *intervention média*. Continuer ? », et n'appeler `journalsApi.update` qu'après confirmation. Étendre `journalsApi` / `schema.ts` pour le preview.

## Décisions (tranchées)

1. **Nom de la règle** : `JOURNAL_TYPE_MEDIA_TO_MEDIA`, conforme à la convention.
2. **Ordre des règles `doc_type`** : theses.fr/dumas priment, media en dernier.
3. **Côté dédup** (`process_document` / `_sp_from_row`) : on ne thread PAS le journal là (hors-slice).
4. **Sync** : requalification synchrone sur confirmation. Job de fond ([CODE_background-jobs.md](docs/chantiers/CODE_background-jobs.md)) réservé aux inputs à très gros fan-out (ex. `publisher.type`), plus tard.

## Fichiers critiques

- `domain/publications/correction.py`, `domain/journals/expected.py`
- `application/publications.py`, `application/journals.py`
- `application/ports/repositories/journal_repository.py` (+ impl `infrastructure/repositories/`)
- `application/pipeline/publications/match_or_create_publications.py`, `merge_by_key.py`, `run_pipeline.py` (wiring `journal_repo`)
- `interfaces/api/routers/journals.py`, `interfaces/api/models/journals.py`
- `interfaces/frontend/src/routes/admin/journals/+page.svelte` (+ `lib/api` / `schema.ts`)

## Vérification

- Tests unitaires : règle media dans `test_correction.py` ; `_apply_corrections` avec un `journal_repo` fake renvoyant un journal media (extension de `test_publications_corrections.py`) ; service de requalification en `dry_run` (compte) et en apply (doc_type + audit).
- Tests d'intégration : `PUT` qui change le type → pubs requalifiées ; endpoint preview renvoie le bon compte.
- Manuel (le but de Laura) : `bash start.sh`, admin journals, éditer un journal en `media`, vérifier la modale (compte) puis la requalification effective. Sous réserve d'une base locale avec des journaux/pubs exploitables.
