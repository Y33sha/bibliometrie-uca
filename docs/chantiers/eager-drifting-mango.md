# Plan — Requalification admin sur changement de `journal.type` (règle media)

**Statut** : implémenté. Commits `59db89d9` (View + règle + refacto refresh), `16b98985` (service + endpoints API), `49d22cd7` (modale frontend). Test manuel restant : `bash start.sh`, admin journals, éditer un journal en `media`, vérifier la modale (compte) puis la requalif effective.

**Décision A/B tranchée** : option B (DTO de lecture `SourcePublicationWithJournalView` dans `domain/source_publications/views.py`, l'agrégat `SourcePublication` reste pur). Les corrections refresh-side et l'agrégation opèrent sur la vue ; la dédup-entrée garde son chemin actuel via une vue à `journal_type=None` (TODO posé dans `_view_from_row` pour le jour où une règle journal-dépendante produirait un type routé).

## Context

La règle de correction « journal de type `media` ⇒ publications en `doc_type = media` » est la première règle dont l'input (`journal.journal_type`) est **éditable côté admin**. Aujourd'hui `PUT /api/journals/{id}` écrit le champ sans aucune conséquence ([application/journals.py:107-127](application/journals.py)) : changer le type ne requalifie pas les publications du journal. On veut pouvoir éditer le type d'un journal dans l'admin et voir ses publications requalifiées, avec une **modale de confirmation** annonçant l'ampleur (« x publications seront requalifiées en *intervention média*. Continuer ? »).

`effective_metadata` reste le **point de correction unique côté SP**, et c'est structurel : la dédup par métadonnées (`match_or_create`) s'aiguille sur le `doc_type` **corrigé** d'un orphelin, *avant* qu'une `Publication` existe ([match_or_create_publications.py:184-202](application/pipeline/publications/match_or_create_publications.py#L184-L202), routage `thesis`/`proceedings`). Toute règle qui change le `doc_type` peut faire (dis)paraître une publication d'un cas de dédup — et les deux ensembles (règles, cas de dédup) grandiront, donc la collision est certaine, pas hypothétique. La règle media consomme `journal.journal_type` ; le `Journal` doit donc être disponible **partout où `effective_metadata` tourne, y compris à l'entrée dédup**, pas seulement au refresh.

**Cul-de-sac acté** : appliquer les corrections journal-dépendantes *en sortie*, post-agrégation sur la `Publication` hydratée, ne marche pas — à l'entrée dédup il n'y a pas encore de Publication, or c'est précisément là qu'on a besoin du `doc_type` corrigé. Ne pas rouvrir cette piste.

La vraie question ouverte : **comment fournir le `Journal` à `effective_metadata`** (cf. section 2). Le paramètre `journal` existe déjà sur la signature mais n'est alimenté par aucun caller.

On reste sur l'archi validée : flux **synchrone** preview → confirm → apply, pas de bus d'événements. L'`audit_log` existant trace l'action.

## Approche

### 1. Domaine — la règle

- `domain/publications/correction.py` : ajouter le membre `JOURNAL_TYPE_MEDIA_TO_MEDIA` à `MetadataCorrectionRule` et une règle dans la cascade `doc_type` : si `journal is not None and journal.journal_type == "media"` ⇒ `Correction("media", JOURNAL_TYPE_MEDIA_TO_MEDIA)`. **Ordre : theses.fr puis dumas priment, media en dernier** — une publication theses.fr/dumas reste thèse/mémoire même si rattachée à un journal typé media.
- `domain/journals/expected.py` : ajouter `"media"` à `EXPECTED_DOC_TYPES_BY_JOURNAL_TYPE["media"]` (sinon la pub corrigée serait signalée incohérente par `is_doc_type_expected_for_journal_type`).

### 2. Application — fournir le `Journal` à `effective_metadata` (DÉCISION OUVERTE)

`effective_metadata` tourne à deux endroits : à l'entrée dédup (`match_or_create.process_document`, sur l'orphelin) et au refresh (`_apply_corrections`, par-SP). Le `Journal` doit être fourni aux **deux**. Deux mécanismes possibles, à trancher :

- **(A) Threader un `journal_repo`** dans le chemin `match_or_create` (+ sa phase + wiring `run_pipeline.py`) et dans `refresh_from_sources`. `_apply_corrections`/`process_document` font `journal_repo.find_by_id(sp.journal_id)` et passent l'objet `Journal` (complet → future-proof pour les règles consommant `oa_model`/`status`/`apc`). Coût : un paramètre repo qui se propage dans plusieurs signatures et call sites (dont les chemins de merge `merge_pubs_by_nnt`/`hal_id` si on veut la cohérence partout — une publi de journal media PEUT être sur HAL, donc fusionnée par hal_id).
- **(B) Enrichir la projection de lecture de la SP** : `SourcePublicationRow` (match_or_create) et `get_source_publications` (refresh) embarquent les champs journal nécessaires via un JOIN `journals`. Pas de repo threadé. **DDD-propre** : c'est un *modèle de lecture* (projection/DTO), pas l'hydratation d'un agrégat `Journal` dans l'agrégat `SourcePublication` — la règle « références entre agrégats par id » concerne l'écriture, pas les lectures. `SourcePublicationRow` est déjà une telle projection. Coût : dénormalisation de la lecture SP + `effective_metadata` reçoit des champs journal ciblés plutôt qu'un objet `Journal` (moins future-proof si une règle veut un champ journal non projeté → ajouter une colonne au JOIN).

Compromis A/B = objet `Journal` complet et threadé vs champs ciblés portés par la lecture. À trancher avant d'implémenter.

### 3. Application — service de requalification (avec dry-run)

- Nouvelle fonction dans `application/journals.py`, ex. `requalify_publications_for_journal(journal_id, *, prospective_type, dry_run, pub_repo, journal_repo, audit_repo=None) -> int` :
  - récupère les pubs du journal, pour chacune recompute le `doc_type` effectif avec un `Journal` portant `prospective_type`, compte celles dont le `doc_type` changerait ;
  - si `dry_run` : renvoie le compte, n'écrit rien ;
  - sinon : applique le changement de type (déjà fait par `update_journal`) puis `refresh_from_sources` sur chaque pub impactée, et émet un event d'audit `journal.type_requalified` (`{count, new_type, rule}`).
  - réutilise `effective_metadata` (source unique de vérité de la règle) — pas de réimplémentation SQL. Pour la règle media, le compte dégénère en « pubs du journal dont `doc_type != 'media'` ».
- `PublicationRepository` : ajouter `find_ids_by_journal_id(journal_id) -> list[int]`. La lecture de `publications` appartient au repo publications (discipline ISP : le `JournalRepository` ne requête pas la table `publications`, cf. le `text()` du merge).

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
3. **`effective_metadata` reste côté SP, point unique** ; la correction journal-dépendante doit tourner à l'entrée dédup (sur l'orphelin) comme au refresh. Piste « post-agrégation sur Publication hydratée » écartée (cf. Context).
4. **Sync** : requalification synchrone sur confirmation. Job de fond ([CODE_background-jobs.md](docs/chantiers/CODE_background-jobs.md)) réservé aux inputs à très gros fan-out (ex. `publisher.type`), plus tard.

**Reste ouvert** : mécanisme A (threader `journal_repo`) vs B (enrichir la projection de lecture SP) — cf. section 2.

## Fichiers critiques

- `domain/publications/correction.py`, `domain/journals/expected.py`
- `application/publications.py`, `application/journals.py`
- `application/ports/repositories/publication_repository.py` (+ impl) pour `find_ids_by_journal_id` ; `journal_repository.find_by_id` pour l'option A
- `application/pipeline/publications/match_or_create_publications.py`, `merge_by_key.py`, `run_pipeline.py` (wiring `journal_repo`)
- `interfaces/api/routers/journals.py`, `interfaces/api/models/journals.py`
- `interfaces/frontend/src/routes/admin/journals/+page.svelte` (+ `lib/api` / `schema.ts`)

## Vérification

- Tests unitaires : règle media dans `test_correction.py` ; `_apply_corrections` avec un `journal_repo` fake renvoyant un journal media (extension de `test_publications_corrections.py`) ; service de requalification en `dry_run` (compte) et en apply (doc_type + audit).
- Tests d'intégration : `PUT` qui change le type → pubs requalifiées ; endpoint preview renvoie le bon compte.
- Manuel (le but de Laura) : `bash start.sh`, admin journals, éditer un journal en `media`, vérifier la modale (compte) puis la requalification effective. Sous réserve d'une base locale avec des journaux/pubs exploitables.
