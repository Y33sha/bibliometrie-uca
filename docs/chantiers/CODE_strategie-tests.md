# Chantier — Stratégie de tests : dé-fictionnaliser, factoriser, parcimonie

Commencé le 2026-06-04

Issu d'un audit QA de la suite de tests (2 394 tests : 1 373 unitaires, 1 021 d'intégration). Trois problèmes indépendants, traitables séparément.

## Contexte

### Problème 1 — Le helper-fiction `find_or_create_for_tests`

`tests/integration/helpers/publications.py::find_or_create_for_tests` réimplémente une cascade match-or-create de publications **retirée du code prod** (commit `23aac706`). En prod, la décision de matching est désormais portée par `decide_publication_match` (décideur pur, `domain/publications/deduplication.py`) et orchestrée par `application/pipeline/publications/match_or_create_publications.process_document` (qui consomme des rows SQL via les bulk-link queries). Le helper, lui, pilote la cascade depuis une `Publication` construite à la main — un chemin qui n'existe plus en prod. Les tests qui en dépendent testent donc une fiction.

Méthode de tri retenue (rigoureuse, pas à l'œil) : **couverture différentielle** via `coverage` + `--cov-context=test`, qui associe chaque ligne prod aux tests qui la touchent. Un test-fiction qui couvre **0 ligne prod unique** est de la pure redondance (le comportement est déjà couvert par les décideurs unitaires + `test_match_or_create_queries.py` sur la vraie entrée) → suppressible. Un test qui couvre du vrai prod exclusif (`refresh_from_sources`, `find_by_nnt`, `repo.create`) est conservé mais re-seedé pour ne plus passer par la fiction. **Critère d'acceptation de chaque étape : re-run de la mesure montrant 0 ligne prod perdue.**

L'audit a révélé que les consommateurs sont de **deux natures** :

- **(a) Tests-cascade purs** : testent la décision de matching (même DOI → fusion, conflit chapter/book, priorité NNT). Suppressibles tels quels.
- **(b) Simulateurs de la phase pipeline** : utilisent la fiction comme substitut de **toute la phase « publications »** (`create_all_publications` lit les SP orphelines et crée les publications). Les remplacer par la vraie `process_document` bute sur un mur structurel (voir Problème 1-bis).

### Problème 1-bis — Les tests pipeline ne sèment pas de périmètre

La vraie phase prod ne crée une publication que pour les orphelins avec **≥1 `source_authorship` in_perimeter** (`fetch_orphan_in_perimeter_source_publications`). Or les tests d'idempotence et de reprocessing ne sèment aucun périmètre : ils lancent `normalize` mais pas la phase affiliations. Pire, les authorships OpenAlex n'y sont **même pas matérialisés** (constaté : `n_sa=0` sur les SP OpenAlex, alors que HAL en a). La fiction masquait ce trou en créant **inconditionnellement** (titre+année suffisent) — fabriquant donc des publications que prod ne créerait pas. Dé-fictionnaliser (b) impose de semer un périmètre réaliste dans ces tests, ce qui touche à la matérialisation des authorships, pas seulement au helper.

### Problème 2 — Mocks et builders dupliqués

Duplication confirmée, surtout dans `tests/unit/application/pipeline/normalize/` : `_FakeStagingQueries` **strictement identique** dans 3 fichiers (hal/openalex/theses), `_FakeQueries` quasi-identique dans 4, builders `StagingRow` dans 5. Côté intégration, des helpers d'INSERT (`_insert_publication` / `_insert_journal` / `_insert_person`) sont recopiés dans plusieurs `tests/integration/application/test_*_service.py`. Aucun `conftest.py` local au dossier `normalize/`, et `tests/integration/helpers/` est sous-utilisé.

### Problème 3 — Parcimonie des tests domain (lecture Cosmic Python)

Cosmic Python conseille d'être parcimonieux sur les tests unitaires du domain **quand les entités sont stables**, et dense **en phase de découverte**. Verdict de l'audit : **pas de sur-test global**. La densité sur `test_correction.py` (102 tests, 11 règles), `test_deduplication.py`, le parsing des sources (116 tests sur payloads réels) et le matching personnes (34 tests) est justifiée — ce sont des règles figées empiriquement, exactement la phase de découverte où la densité est recommandée. Le seul vrai gisement de redondance : la **normalisation des identifiants** (DOI, ORCID, IdHAL, RorId, IdRef), testée 8 à 13 fois chacune en tests séparés (`strip(https)`, `strip(http)`, `strip(bare)`…) là où un `@pytest.mark.parametrize` suffirait. C'est cosmétique, basse priorité.

## Décisions

1. **La couverture différentielle est l'arbitre.** On ne supprime un test-fiction qu'après avoir vérifié qu'il couvre 0 ligne prod unique ; on re-seede (pas supprime) tout test couvrant du vrai prod exclusif. Re-mesure obligatoire à chaque étape.
2. **Re-seeding via la vraie brique prod.** Remplacer la fiction par `repo.create` (méthode prod réelle, sans cascade) pour le simple besoin « avoir une ligne `publications` », et par la vraie `process_document` quand le test a besoin de la dédup réelle.
3. **Problème 1-bis est un sous-chantier à part.** Semer le périmètre dans les tests pipeline (insérer des `source_authorship` in_perimeter synthétiques par orphelin) est du **fixture**, pas de la réimplémentation de logique — légitime, dans l'esprit du workaround matview de `tests/integration/helpers/structures.py`. Mais il exhume le gap des authorships OA non matérialisés : à instruire avant, pas en passant.
4. **Garde-fou parcimonie.** Ne PAS couper en masse les tests `frozen`/`hashable`/`equality` des value objects : ceux utilisés comme clés de `dict`/`set` (identifiants dans le matching) sont des tests de **contrat**, pas de la machinerie dataclass. Tri au cas par cas, jamais au volume.

## Phasage

### Problème 1 — Dé-fictionnaliser, puis supprimer le helper

- [x] **`test_dedup_publications.py`** (commit `02f8779b`) : 21 tests-fiction supprimés (cascade DOI / conflit doc_type / NNT + 8 tautologiques sur un matching par titre inexistant), 14 tests conservés et re-seedés via `repo.create` (12 `refresh_from_sources` + 2 `find_by_nnt`). Mesure : 0 ligne prod perdue (publications.py 86 / aggregation 64 / publication_repository 145, inchangés).
- [x] **`test_scenarios.py::TestPublicationService`** (commit `2a12d46c`) — même sac mixte que test_dedup (pas « pur cascade ») : 6 tests-fiction supprimés (create, dédup DOI, 2 tautologiques titre, allow_create), 2 tests `refresh_from_sources` re-seedés via `repo.create` dont celui qui couvre seul la branche auto-merge `publications.py:155-178`. Classe renommée `TestRefreshFromSources`. Mesure suite complète : 0 ligne prod perdue.
- [ ] **`idempotence/_helpers.py::create_all_publications` + `test_reprocessing.py::_create_all_publications`** (nature b). Dépend du Problème 1-bis.
- [ ] **Supprimer `find_or_create_for_tests`** (et `tests/integration/helpers/publications.py`) une fois zéro caller. Vérifier qu'aucune ligne prod ne perd sa couverture.

### Problème 1-bis — Périmètre réaliste dans les tests pipeline

- [ ] Instruire le gap : pourquoi `run_normalize_oa` (harness des tests d'idempotence) ne matérialise pas de `source_authorships` alors que `run_normalize_hal` si. Trancher si c'est un bug du harness ou un comportement prod attendu.
- [ ] Helper de fixture « semer un périmètre » : insérer une `source_authorship` in_perimeter minimale par SP orpheline qui n'en a pas (colonnes NOT NULL à remplir, FK person éventuelle). Rend tous les orphelins de test éligibles à la création — équivalent fidèle de l'ancien `allow_create=True`, mais via la vraie phase.
- [ ] Réécrire `create_all_publications` pour piloter `process_document` par orphelin (queries réelles `PgPublicationsMatchOrCreateQueries`, `pub_repo` réel), sans cascade-fiction. SA-only (le branchement psycopg du helper est mort : tous les callers passent `sa_sync_conn`).
- [ ] Vérifier que les tests d'idempotence passent sous sémantique prod réelle (dédup DOI cross-source, non-création des orphelins hors-périmètre).

### Problème 2 — Factoriser mocks et builders (clôturé)

- [x] **Fixture `logger`** factorisée dans `tests/unit/application/pipeline/normalize/conftest.py` (commit `4995ea9e`) — elle était redéfinie à l'identique dans hal/openalex/theses/wos.
- [x] **Le reste laissé local, décision motivée.** `_FakeStagingQueries` (6 lignes, identique ×3) : l'arbo `tests/unit/` n'a pas de `__init__.py`, donc factoriser proprement demanderait soit du scaffolding `__init__.py`, soit des imports-depuis-conftest fragiles, pour un stub trivial instancié inline dans des helpers `_kwargs` — remède plus lourd que le mal. `_FakeQueries` : méthodes nommées par source (`upsert_hal_source_publication` vs `upsert_openalex_…`), une base unifiée serait de l'abstraction cérémonieuse. Les `_insert_*` d'intégration : la localité a une valeur en tests (chaque fichier se lit seul) et la duplication n'est que le reflet de la duplication prod (6 upserts `upsert_<source>_source_publication`, ~80 % identiques mais avec colonnes + règles de merge propres par source). Tuer la duplication à la racine = refactorer la prod, pas les tests (voir Questions ouvertes).

### Problème 3 — Parcimonie domain (clôturé)

- [x] Normalisation des identifiants paramétrée (commit `47e18e6a`) : DOI, ORCID, IdHAL, IdRef, NNT, HALId, RorId, HalCollection. Variantes `strip(https/http/préfixe nu)` + lowercase + version suffix + cas de rejet fusionnées en `@pytest.mark.parametrize`, rationale conservé en commentaire de ligne. Aucun cas perdu. Conservés : les tests de contrat des VO (frozen/hashable — DOI clé de set) et le cas subtil `.v` non terminal.

## Questions ouvertes

- **Problème 1-bis vaut-il l'investissement ?** Alternative à l'option « semer le périmètre » : acter que les simulateurs de phase (b) restent une simplification assumée et documentée, et ne dé-fictionnaliser que la nature (a). Le helper survivrait alors, mais avec un périmètre d'usage honnête (uniquement les tests d'idempotence/reprocessing, jamais les tests de décision). Tranche le compromis fidélité-vs-coût.
- **Le gap authorships OA** (Problème 1-bis, premier point) est peut-être un signal au-delà des tests : si le harness ne les matérialise pas par oubli, vérifier qu'un run prod réel les produit bien.
- **Duplication des 6 upserts `upsert_<source>_source_publication`** (piste prod, hors tests). Tous écrivent dans la table unique `source_publications` avec un tronc commun (~15 colonnes + `ON CONFLICT (source, source_id) DO UPDATE … COALESCE … updated_at`) dupliqué six fois, ne différant que par la source littérale, 1-3 colonnes propres (HAL `hal_collections` ; OpenAlex `cited_by_count`/`is_retracted` ; etc.) et leur règle de merge (array-agg, `GREATEST`). Candidat à un upsert unifié (tronc commun + sac de colonnes/merges source-spécifiques), avec l'arbitrage inverse : un générique perd les signatures typées explicites et conditionnalise les règles de merge. À auditer sur les 6 sources avant de trancher.
