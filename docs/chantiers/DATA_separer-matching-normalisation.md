# Chantier — Séparer le matching de la normalisation

Commencé le 2026-05-14

## Contexte

Aujourd'hui, chaque normalizer (`normalize_hal`, `normalize_openalex`, `normalize_scanr`, `normalize_wos`, `normalize_theses`, `normalize_crossref`) fait **deux choses différentes** dans le même flux par document :

1. **Normalisation** : staging → `source_publications` + `source_authorships`.
2. **Matching** : rattacher le `source_publication` à une `publication` canonique existante via une cascade d'identifiants (DOI, NNT, HAL_ID, etc.), ou laisser `publication_id = NULL`.

Plus tard dans le pipeline, la phase `create_publications` (`application/pipeline/publications/create_publications.py`) reprend les `source_publications` orphelins (avec `publication_id IS NULL` et au moins un `source_authorship in_perimeter`) et fait elle aussi un matching avant d'éventuellement créer la publication.

**Conséquence** : la logique de matching est dupliquée et fragmentée. Chaque normalizer construit sa propre cascade (avec ses extractions source-spécifiques + des appels à `find_or_create(allow_create=False)`), et `create_publications` refait à nouveau le même travail en aval pour les orphelins. Le chantier `METIER_deduplication-fusion-publications` partait du constat que 5 cascades font la même chose, et tentait de les factoriser site par site — mais une fois les primitives en place (`decide_publication_match`, `decide_doi_attribution`, `try_merge_by_doi` wrappé, `merge_publications_by_key`), il devient évident que la bonne réponse n'est pas de migrer chaque cascade mais de **centraliser tout le matching en aval, dans une phase dédiée du pipeline**.

### Bénéfices attendus

- **Une seule cascade** dans tout le pipeline, vivant dans la phase publications. Plus de duplication entre normalizers.
- **Séparation propre des responsabilités** : la normalisation extrait/transforme, la phase publications décide du rattachement canonique. Les normalizers ne touchent plus aux publications canoniques.
- **Cohérence** : aujourd'hui les `source_publications` créés en phase normalize sont parfois rattachés, parfois pas, et le matching dépend de l'ordre des sources. Demain, tous les `source_publications` passent par la même cascade dans le même ordre.

### Hors-scope

- **Évolution de la logique de matching** (nouveaux critères de dédup, scoring, blocking, etc.) : pas dans ce chantier. On déplace, on ne change pas la logique. Une fois la cascade centralisée, ces évolutions seront beaucoup plus simples.
- **Refactoring des normalizers eux-mêmes** : on ne retire que la partie matching ; le reste (extraction, normalisation, upsert source_publications, process_authorships) reste en place.

## Décisions

1. **Le matching disparaît des normalizers**. Chaque `source_publication` est créé avec `publication_id = NULL` ; le rattachement canonique se fait exclusivement dans la phase publications.

2. **Pas de matching « partiel » en phase normalize**. Pas de pré-match optimiste qui éviterait un passage en phase publications : c'est cette dualité actuelle qui crée la duplication. Tous les `source_publications` passent par la phase publications.

3. **Acceptation que les métadonnées canoniques (`publications.*`) ne sont PAS à jour à la fin de la phase normalize**. Le `refresh_from_sources` se fait en phase publications, après matching ou création. C'est cohérent avec ce qu'on attend d'une phase de normalisation pure.

4. **Les identifiants cross-source (`hal_id`, `nnt`, `openalex_id` natifs, etc.) sont posés dans `source_publications.external_ids` par les normalizers**. C'est le réceptacle déjà existant — il faut juste s'assurer qu'il est complet et exploitable par la cascade unifiée (vérification Phase 0).

5. **Phase publications étendue** : `create_publications.py` traite désormais TOUS les `source_publications`, pas seulement les orphelins. La sélection « avec au moins un `source_authorship in_perimeter` » reste : on ne matche/crée que pour ceux qui entrent dans le périmètre UCA. À renommer (proposition : `match_or_create_publications.py`).

6. **Cascade unifiée** : `decide_publication_match` avec prefetch de DOI/NNT/HAL_ID depuis `external_ids` (et `source_publications.doi` pour le DOI). Cas `MetadataDeduplicationCase.THESIS_TITLE_YEAR` pour les thèses (lecture des `source_authorships` du `source_publication` courant pour le test de compatibilité auteur).

7. **Repointing HAL** géré nativement par le résolveur de chaîne de `merge_publications_by_key` (Phase 3 du chantier METIER). Cas typique : un `source_publication` HAL pointait précédemment sur `pub_A` (`hal_id` connu), la cascade découvre via le DOI une `pub_B` distincte → fusion de `pub_A` et `pub_B`, le `source_publication` retombe sur la cible résolue.

8. **Enrichissement DOI tardif (`try_merge_by_doi`)** appelé post-cascade sur la pub matchée/créée, dans la phase publications. Idempotent quand la pub porte déjà le DOI.

9. **Q4 du chantier METIER (wrapper `application/publications.py:resolve_doi_conflict`)** : à trancher en fin de Phase 3 du présent chantier, quand l'utilisation effective sera figée.

## Phasage

### Phase 0 — Audit + harmonisation des clés de `external_ids`

Audit fait. Bilan :

- **Convention retenue (option B)** : `source_publications.source_id` reste l'identifiant natif (interprété selon `source_publications.source`) ; `external_ids` ne contient que les identifiants cross-source détectés en plus (pas l'identifiant natif). Le matching aval combine les deux via un helper Python `extract_known_identifiers(sp) -> dict[str, str]` qui aplatit `{native_kind_by_source[sp.source]: sp.source_id, **sp.external_ids}`.
- **Couverture aujourd'hui** : `hal_id` (OpenAlex via URL, ScanR via `externalIds`), `nnt` (HAL/OpenAlex/ScanR/Theses), `pmid` (OpenAlex via URL, ScanR via `externalIds`), `pmc` (OpenAlex via URL), `issn`/`isbn` (Crossref — pour matching journal, hors matching pub), `source_doi` (OpenAlex post-invalidation chapter/book).
- **WoS** : aucun cross-source aujourd'hui (`external_ids = None`). Extraction PMID + autres reportée à un chantier ultérieur quand on généralisera l'extraction PMID à toutes les sources.

Décisions :

- **Harmoniser `external_ids.hal` → `external_ids.hal_id`** (cohérence avec `nnt`, `pmid`, `pmc` qui sont des acronymes courts ; `hal` était une abréviation ambiguë du HAL ID). `nnt`/`pmid`/`pmc` restent : déjà des acronymes standard. `pmid` et `pmc` sont deux identifiants distincts (PubMed vs PubMed Central), coexistent sur un même document.
- **Migration Alembic** pour renommer les clés sur les `source_publications` existants.
- **`source_doi`** : conservé dans `external_ids` (trace historique, n'intervient pas dans la cascade). Sa pose sera centralisée en phase publications (avec le `resolve_doi_conflict`) et donc systématiquement appliquée à toutes les sources, plus seulement OpenAlex.

Tâches :

- [x] Migration Alembic : `external_ids.hal` → `external_ids.hal_id` sur tous les `source_publications` existants.
- [x] Renommer dans le code écriture : `domain/sources/openalex.py`, `application/pipeline/normalize/normalize_scanr.py`. Tests associés.
- [x] Renommer dans le code lecture SQL : `infrastructure/sources/hal/fetch_missing_hal_id.py`, `infrastructure/db/queries/merge.py`. Tests associés.
- [x] Mettre à jour le modèle Pydantic `infrastructure/db/jsonb_models/publication.py:ExternalIds` (champ `hal` → `hal_id` + validator) et la doc.
- [x] Mettre à jour les commentaires/docstrings résiduels (`application/pipeline/publications/merge_pubs_by_hal_id.py`).

### Phase 1 — Cascade unifiée dans la phase publications

Réécrire `create_publications.py` pour intégrer la cascade complète.

- [x] Helper `extract_known_identifiers(source, source_id, external_ids)` : aplatit l'identifiant natif (interprété selon `source`) + les `external_ids` cross-source en un dict plat consommable par la cascade. Tests purs.
- [x] `find_by_hal_id` sur le port `PublicationRepository` + adapter Postgres. Couvre le path natif HAL (`source='hal' AND source_id=hal_id`) ET le path cross-source (`external_ids->>'hal_id'=hal_id` posé par OpenAlex/ScanR). Tests d'intégration.
- [x] Queries thèse côté `PublicationsCreateQueries` : `fetch_thesis_primary_author(publication_id)` (auteur primary d'une pub canonique candidate) et `fetch_thesis_primary_author_from_source_publication(source_publication_id)` (auteur primary d'un source_publication courant, avant rattachement).
- [x] Cascade dans `process_document` : prefetch DOI (avec `resolve_doi_conflict`) → NNT → HAL_ID → THESIS_TITLE_YEAR (si `doc_type='thesis'`) → `decide_publication_match` → match/create → `try_merge_by_doi` post-match si non-DOI → `link_source_publication_to_publication` → `refresh_from_sources`.

### Phase 2 — Retrait du matching des normalizers + élargissement de la phase publications

**Retrait par normalizer**. Chaque `source_publication` est créé avec `publication_id = NULL`.

- [x] `normalize_hal.py` : retrait du `find_publication` + `try_merge_by_doi` + `refresh_from_sources` + cas repointing dans `process_work`.
- [x] `normalize_openalex.py` : retrait du `find_publication` + cascade HAL/NNT primary_location + `find_hal_publication_id` + `resolve_doi_conflict` + `try_merge_by_doi` + `refresh_from_sources`. Conservation de l'extraction NNT/HAL_ID depuis primary_location → mémorisée dans `external_ids`.
- [x] `normalize_theses.py` : retrait du `find_publication` + dédup spéciale title+year+author + `try_merge_by_doi` + `refresh_from_sources` + `_update_thesis_meta`.
- [x] `normalize_scanr.py` : retrait du `find_publication` + `try_merge_by_doi` + `refresh_from_sources`.
- [x] `normalize_crossref.py` : retrait du `find_publication` + `try_merge_by_doi` + `refresh_from_sources`.
- [x] `normalize_wos.py` : retrait analogue.

**Élargissement de la phase publications**. Une fois que les normalizers ne rattachent plus, la phase devient le seul site de rattachement et doit gérer les cas qui apparaissent alors.

- [x] Renommer `create_publications.py` → `match_or_create_publications.py` (phase, port, adapter, entry point CLI, `run_pipeline.py`). `PublicationsCreateQueries` → `PublicationsMatchOrCreateQueries`.
- [x] Refresh sélectif des pubs stale : colonne `source_publications.updated_at` (clock_timestamp), comparaison `sp.updated_at > p.updated_at`, 2e passe dans la phase `match_or_create_publications.run`.
- [x] Repointing HAL : pas besoin d'un mécanisme spécifique. On ne re-matche pas au re-normalize (risque de doublons). Le cas « hal_id pointait vers pub_A, le DOI émerge plus tard et désigne pub_B » est traité par la phase dédiée `merge_pubs_by_hal_id` en aval.
- [x] Filtrage `publication_id IS NULL` conservé pour la passe matchorcreate. Pas de `matched_at` nécessaire : le rattachement est figé une fois fait, les méta sont propagées via la 2e passe de refresh (sp.updated_at vs p.updated_at).

### Phase 3 — Cleanup

- [ ] Suppression des helpers source-spécifiques devenus inutilisés : `find_hal_publication_id` (openalex), `get_openalex_publication_id`, `get_hal_publication_id`, `find_hal_publication_id` (theses si applicable).
- [ ] Audit de l'API `application/publications.py` : `find_or_create` n'est plus appelé que depuis la phase publications. Voir si son interface peut être simplifiée (peut-être devenu redondant avec la cascade explicite de `match_or_create_publications`).
- [ ] Q4 du chantier METIER : `resolve_doi_conflict` wrapper côté application — utilisé ? simplifiable ? supprimable ?
- [ ] Mise à jour de `docs/pipeline.md` et `CLAUDE.md` si nécessaire (description des phases).

### Phase 4 — Validation pipeline complet

- [ ] Run complet du pipeline sur une base test, vérifier les tableaux résultants (counts publications, source_publications, distribution des matchings).
- [ ] Comparer aux runs précédents (avant chantier) sur les mêmes données — un certain delta est attendu (logique de matching DOI > NNT > HAL_ID alignée partout, plus de comportements divergents par source), mais il doit être interprétable.

## Questions ouvertes

- **Q1 — `matched_at` vs filtrage sur `publication_id IS NULL`** : à quel critère sélectionner les `source_publications` à passer dans la cascade en phase publications ? Si on filtre sur `publication_id IS NULL`, un re-run de la phase ne re-matche pas ceux déjà rattachés (acceptable si on assume que le rattachement ne bouge pas hors fusion explicite). Si on veut pouvoir re-matcher à la demande, il faut un mécanisme additionnel.

- **Q2 — Idempotence par source_id (« re-attach mono-source »)** : aujourd'hui, certains normalizers font un lookup `source_publications WHERE source='X' AND source_id=<id>` pour reprendre le `publication_id` d'un passage précédent. Avec la séparation, ce lookup disparaît côté normalize, mais la phase normalize doit toujours faire l'upsert (UPDATE si déjà vu, INSERT sinon) — c'est de l'idempotence d'écriture, pas de matching. À vérifier que c'est bien le cas dans tous les normalizers (déjà fait pour la plupart, présumément).

- **Q3 — Ordre dans la cascade unifiée** : DOI > NNT > HAL_ID > metadata (thèse). À confirmer en début de Phase 1. Alignement avec ce qui sort des décisions du chantier METIER.

- **Q4 — Performance de la phase publications** : aujourd'hui elle ne traite que les orphelins ; demain, tous les `source_publications` in-perimeter. Volume × cascade SQL × refresh. À surveiller, possiblement à batcher.

## Liens

- Chantier prérequis : `METIER_deduplication-fusion-publications.md` — primitives consommées par la cascade unifiée (`decide_publication_match`, `decide_doi_attribution`, `try_merge_by_doi` wrappé, `merge_publications_by_key`, `merge_source_rows`). Phases 0-3 + Phase 4 partielle (find_or_create migré) terminées et indépendantes ; les items Phase 4 restants (migration des 4 cascades dans les normalizers) deviennent caducs avec le présent chantier.
- Suite naturelle (hors-scope ici) : évolution de la logique de matching (cf. mémoire `project_dedup_publications_chantier`).
