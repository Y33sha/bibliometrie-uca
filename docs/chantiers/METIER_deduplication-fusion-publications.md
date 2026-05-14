# Chantier — Déduplication & fusion de publications

Commencé le 2026-05-14.

## Contexte

Le pipeline contient aujourd'hui **5 cascades de matching/fusion disséminées** qui font la même chose à chaque source ou presque, plus des règles de fusion multi-sources dupliquées entre `refresh_from_sources` et les phases dédiées de fusion. Chantier coordonné nécessaire — toucher l'un sans les autres laisse un état incohérent.

**Deux dimensions imbriquées** :

- **Refactorisation** : extraire les décisions pures vers `domain/publications/deduplication.py` (cascades) et nouveau `domain/publications/merge.py` (algorithme de fusion multi-sources), unifier les sites qui font la même chose.
- **Changement de logique** : la règle « choix de la publication cible de fusion » est arbitraire (les métadonnées canoniques sont triangulées par `refresh_from_sources` après fusion) — simplifier cette règle partout, supprimer le ranking SQL, gérer correctement les redirections en chaîne. Et inclure `title` dans l'agrégation cross-sources, ce que `refresh_from_sources` oublie actuellement.

### Sites concernés (inventaire)

**Cascades de matching** (5 sites, 5 variantes) :

- `application/publications.py:find_or_create` — cascade DOI → NNT → création, avec gestion de conflit DOI déléguée à `resolve_doi_conflict`. Enchaîne `try_merge_by_doi` quand une thèse trouvée par NNT n'a pas de DOI alors qu'on en propose un.
- `application/publications.py:try_merge_by_doi` — mini-règle de dédup tardive : si la pub courante n'a pas de DOI mais qu'un DOI candidat est fourni et qu'une autre pub porte ce DOI → fusion ; sinon attribution.
- `application/pipeline/normalize/normalize_openalex.py:find_publication` — cascade priorisée HAL > NNT > openalex_id > title.
- `application/pipeline/normalize/normalize_theses.py:find_publication` — cascade DOI/NNT puis dédup spéciale par titre+année + compatibilité auteur.
- `application/pipeline/normalize/normalize_hal.py:process_work` — fusion HAL deux pubs (si `hal_id` pointait sur `old_pub_id` mais `find_publication` DOI/NNT trouve `publication_id` différent).

**Algorithme de fusion multi-sources** : `application/publications.py:refresh_from_sources` + helpers inlinés `_first_non_null`, `_merge_lists`, `_merge_jsonb`, `_topics_by_source`, `_first_doc_type`. Inclut une auto-fusion sur collision DOI (la pub qui occupe déjà le DOI agrégé est absorbée — déjà exposée via `RefreshResult.absorbed_publication_id` depuis le chantier `CODE_rich-domain-model`).

**Choix de la publication cible de fusion** (4 sites, 4 règles ad hoc) :

- `merge_pubs_by_hal_id` : « HAL gagne » (ordre des arguments fixé dans `_merge_pub(cur, hal_pub_id, src_pub_id, ...)`).
- `merge_pubs_by_nnt` : ranking SQL `rank_publications_by_merge_priority` (DOI shape + complétude + id ASC).
- `try_merge_by_doi` : sa propre cascade.
- `process_work` HAL : fusion `old → new` (la nouvelle survit).

**Préalable déjà fait** (commit `ce5cf4f`) : `refresh_from_sources(target)` est désormais appelé après chaque fusion dans les phases dédiées (`merge_pubs_by_hal_id`, `merge_pubs_by_nnt`) — auparavant les métadonnées canoniques de la cible restaient figées après absorption.

## Décisions

1. **Vocabulaire** : « déduplication » partout dans le code, les fichiers et la doc. Jamais « dedup ». Renommage de `domain/publications/dedup.py` en `domain/publications/deduplication.py` inclus comme préliminaire.

2. **Architecture domaine** : règles pures dans `domain/publications/deduplication.py` (cascades de matching) et nouveau `domain/publications/merge.py` (algorithme de fusion multi-sources + résolveur de chaîne). Pattern aligné sur l'hydratation de `Publication` faite en Phase 4 du chantier `CODE_rich-domain-model`.

3. **Choix de la cible de fusion** : règle triviale `min(pub_ids)` appliquée partout. Suppression du ranking SQL `rank_publications_by_merge_priority`, de son port `MergeQueries.rank_publications_by_merge_priority`, et de ses tests dédiés. Justification : les métadonnées sont triangulées par `refresh_from_sources` selon `SOURCE_PRIORITY` après chaque fusion, donc le choix n'a aucun impact métier.

4. **Helper unifié `merge_publications_by_key(...)`** consolidant les sites de fusion par clé (HAL, NNT, repointing). Applique le choix trivial de cible, **porte le résolveur de chaîne** (présent dans `merge_pubs_by_hal_id`, absent dans `merge_pubs_by_nnt`) pour suivre `pub_A → pub_B` puis `pub_X → pub_A` accumulés dans un batch, lance `merge_publications` + `refresh_from_sources`.

5. **Cascade de matching unifiée** : `decide_publication_match(*, doi_match, nnt_match, ...)` paramétrée par les lookups disponibles, pas une fonction par source. Les normalizers prefetchent les lookups pertinents (un seul appel par identifiant), passent au décideur, la décision retournée est pure.

6. **Algorithme de fusion** exfiltré vers `merge.py` : helpers `_first_non_null`, `_merge_lists`, `_merge_jsonb`, `_topics_by_source`, `_first_doc_type` deviennent publics (`first_non_null`, etc.), et une fonction `merge_source_rows(rows, *, source_priority) -> MergedPubFields` encapsule l'algo complet de `refresh_from_sources`. **Inclut `title` et `title_normalized`** comme scalaires fusionnés au même titre que les autres (premier non-null prioritaire) — corrige la limitation actuelle où la cible canonique gardait son titre même si une source l'avait amélioré. Ferme l'item ouvert de Phase 4 de `CODE_rich-domain-model`.

7. **`DEDUPLICATION_KEYS` enum** (`str, Enum`) portant les noms d'identifiants et l'ordre de priorité (par ordre de définition). Évite la dispersion de constantes string + permet d'itérer la cascade dans l'ordre standardisé. Inclut au moins `DOI`, `NNT`, `HAL_ID` au démarrage.

8. **Hors-scope** : DOI dataset vs article (trigger figshare déjà en place côté DB).

## Phasage

### Phase 0 — Préliminaire de vocabulaire

- [x] `git mv domain/publications/dedup.py domain/publications/deduplication.py` + idem pour `tests/unit/domain/publications/test_dedup.py` → `test_deduplication.py`. Renommage analogue du fichier de fiche : `METIER_dedup-fusion-publications.md` → `METIER_deduplication-fusion-publications.md`.
- [x] Sites d'import mis à jour : `application/publications.py`, `application/pipeline/publications/create_publications.py`, `application/pipeline/normalize/normalize_{hal,scanr,crossref}.py`, `tests/unit/domain/publications/test_deduplication.py`.
- [x] Docstrings (`domain/publications/__init__.py`, `domain/publications/deduplication.py`, `domain/publication.py`) et fiche `CODE_rich-domain-model.md` mises à jour (toutes les références `dedup.py` → `deduplication.py`, chemins vers la fiche METIER renommée).

### Phase 1 — Exfiltration de l'algorithme de fusion vers `merge.py`

Ferme le dernier item ouvert de Phase 4 du chantier `CODE_rich-domain-model`.

- [x] Création de `domain/publications/merge.py`.
- [x] Helpers publicisés (`first_non_null`, `merge_lists_dedup_ci`, `shallow_merge_jsonb`, `topics_by_source`, `arbitrate_doc_type_with_article_subtype`) et `merge_source_rows(pub, rows, *, source_priority) -> None` qui mute l'entité `Publication` en place (pas de `MergedPubFields` séparé : `Publication` étendue porte toutes les colonnes canoniques).
- [x] Extension de `Publication` avec les 6 champs manquants : `abstract`, `is_retracted`, `keywords`, `topics`, `biblio`, `meta`.
- [x] Extension de `repo.find_by_id` / `repo.save` pour charger/persister ces 6 champs ; retrait de `repo.update_aggregated` (redondant). — `8e30bcd`
- [x] Title et title_normalized inclus dans l'agrégation cross-sources. title_normalized recalculé via `normalize_text(pub.title)` après agrégation.
- [x] `refresh_from_sources` orchestre désormais : load → pré-merge sur collision DOI → `merge_source_rows` → `save`. `RefreshResult.absorbed_publication_id` conservé.

### Phase 2 — Choix de cible trivial + suppression du ranking SQL

- [x] `merge_pubs_by_nnt` utilise désormais `min(pub_ids)` (via `sorted(...)[0]`) au lieu du ranking SQL.
- [x] Query SQL `rank_publications_by_merge_priority` supprimée.
- [x] Port `MergeQueries.rank_publications_by_merge_priority` + implémentation `PgMergeQueries.rank_publications_by_merge_priority` retirés.
- [x] Tests dédiés `TestRankPublicationsByMergePriority` supprimés.

### Phase 3 — Helper unifié de fusion par clé

- [ ] Définir `merge_publications_by_key(pub_ids_by_key, *, repo, audit_repo)` dans `application/publications.py` (ou un sous-module si nécessaire).
- [ ] Inclure le résolveur de chaîne (porté depuis `merge_pubs_by_hal_id`).
- [ ] Le helper applique `min(pub_ids)`, résout les chaînes, appelle `merge_publications` puis `refresh_from_sources`.
- [ ] Migrer `application/pipeline/publications/merge_pubs_by_hal_id.py` vers le helper.
- [ ] Migrer `application/pipeline/publications/merge_pubs_by_nnt.py` vers le helper.

### Phase 4 — Factorisation des cascades de matching

- [ ] Définir `DEDUPLICATION_KEYS` enum dans `domain/publications/deduplication.py`.
- [ ] Définir `PublicationMatchDecision` (dataclass frozen) + `decide_publication_match(*, doi_match, nnt_match, ...)` dans `domain/publications/deduplication.py`.
- [ ] Migrer `application/publications.py:find_or_create` vers le décideur.
- [ ] Migrer `application/pipeline/normalize/normalize_openalex.py:find_publication` (cascade HAL > NNT > openalex_id > title).
- [ ] Migrer `application/pipeline/normalize/normalize_theses.py:find_publication` (cascade DOI/NNT puis title+author).
- [ ] Migrer `application/pipeline/normalize/normalize_hal.py:process_work` (repointing). Décision dédiée `decide_hal_id_repointing(old_pub_id, new_pub_id)`.
- [ ] Trancher Q3 sur `try_merge_by_doi`.

### Phase 5 — Cleanup

- [ ] Selon arbitrage de Q3 : `try_merge_by_doi` absorbé dans `decide_doi_attribution` ou laissé.
- [ ] Selon arbitrage de Q4 : wrapper `application/publications.py:resolve_doi_conflict` simplifié ou supprimé.

## Questions ouvertes

- **Q2 — `MergedPubFields` shape** : dataclass typé (frozen, slots) vs kwargs match du contrat actuel de `repo.update_aggregated`. Trade-off : typé/explicite vs minimal/zero-boilerplate. À trancher avant Phase 1.

- **Q3 — `try_merge_by_doi` absorbé par `decide_doi_attribution` ?** Ou laissé comme is (mini-règle distincte du flow normal de cascade) ? À trancher avant la fin de Phase 4.

- **Q4 — wrapper `application/publications.py:resolve_doi_conflict`** : devient-il redondant après la factorisation ? Pourrait disparaître si `decide_publication_match` retourne aussi les effets de bord à appliquer (style `RefreshResult`). À trancher en fin de Phase 4.

## Liens

- Chantier prérequis : `CODE_rich-domain-model.md` (Phase 4 — hydratation Publication, déjà faite).
- Fix préalable du refresh post-fusion : commit `ce5cf4f`.
- Pattern de référence (règle pure déjà en domain) : `resolve_doi_conflict` dans `domain/publications/deduplication.py` (après rename).
