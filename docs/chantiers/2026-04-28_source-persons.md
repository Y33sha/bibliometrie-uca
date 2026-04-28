# Chantier — Repenser `source_persons`
Commencé et terminé le 2026-04-28

## Contexte

La table `source_persons` est aujourd'hui peuplée par tous les normalizers, indépendamment de l'utilité réelle. Pour les sources sans identifiant auteur stable (OpenAlex, WoS, CrossRef, et le cas HAL « pas de compte HAL identifié »), on synthétise un `source_id` artificiel pour respecter la contrainte `UNIQUE(source, source_id)`. Conséquence pratique : on crée une ligne `source_persons` par `source_authorships` dans ces cas, sans bénéfice net.

Ce doc audite l'usage existant et propose un découpage en chantiers dédiés.

## État actuel — résumé de l'audit

### Patterns d'écriture par source

| Source | `source_id` | Stable ? | Champs spécifiques exploités |
|---|---|---|---|
| HAL avec compte | `hal_person_id` | ✅ | `source_ids.hal_person_id`, `idhal`, `orcid`, `idref` |
| HAL sans compte | `nokey-<seq>` | ❌ synthétique | (aucun, juste le nom) |
| ScanR avec idref | `idref` | ✅ | `idref`, `orcid` |
| ScanR sans idref | `scanr-<seq>` | ❌ synthétique | (aucun) |
| Theses avec PPN | `ppn` | ✅ | `idref` |
| Theses sans PPN | `nokey-<seq>` | ❌ synthétique | (aucun) |
| OpenAlex | `openalex_id` (par doc) | ⚠️ stable mais entité algorithmique non fiable | `orcid` (peu fiable) |
| WoS | `daisng_id` (par doc) | ⚠️ stable mais entité algorithmique non fiable | `orcid` (peu fiable), `source_ids.researcher_id` |
| CrossRef | `<DOI>:<position>` | ❌ synthétique 1:1 avec authorship | `orcid` (fiable, article-level) |

### Ce qui consomme réellement `source_persons`

- **`fetch_unlinked_authorships()`** (`infrastructure/db/queries/persons/create.py`) — JOIN avec `source_persons` pour récupérer `last_name`, `first_name`, `orcid`, `idref`, `source_ids`. C'est la requête la plus structurante.
- **Étape 0 du pipeline persons** — extraction de `source_ids->>'hal_person_id'` pour propager `person_id` aux authorships HAL d'un même compte.
- **Endpoints UI** : `person_profile()` affiche les comptes HAL liés (idhal, hal_person_id) ; `hal_duplicate_accounts()` admin pour la fusion manuelle de comptes HAL doublons.
- **CLI repair `repair_hal_nokey_source_persons.py`** — nettoyage des orphelins `nokey-*`.

### Ce qui ne consomme PAS `source_persons`

- Le matching de fond du pipeline `personnes` (étapes 1-3 de `create_persons_from_source_authorships.py`) repose sur `source_authorships.author_name_normalized`, `source_authorships.orcid` (note : OA met l'ORCID là directement), et `person_name_forms`. Les noms structurés `last_name`/`first_name` du `source_persons` sont consultés mais redondants avec ce qui est déjà stocké/calculé côté `source_authorships`.

### Bilan

`source_persons` est **réellement utile** pour :
1. **HAL avec compte HAL identifié** : porteur de `source_ids.hal_person_id` → propagation Étape 0 et UI doublons admin.
2. **ScanR avec idref** : porteur de l'idref stable, réutilisable pour matching cross-source.
3. **Theses avec PPN** : idem (PPN = idref).

`source_persons` est **un fardeau sans bénéfice** pour :
- OpenAlex, WoS, CrossRef (entités algorithmiques non fiables — l'ORCID est mieux placé sur l'authorship)
- HAL `nokey-*`, ScanR `scanr-<seq>`, Theses `nokey-*` (lignes synthétiques sans contenu spécifique au-delà du nom)

## Diagnostic

`source_persons` mélange deux rôles incompatibles :

- **Rôle « identité d'auteur côté source »** — pertinent quand la source maintient des comptes auteurs vraiment dédupliqués (HAL avec `hal_person_id`, ScanR avec idref, theses avec PPN). Permet de propager des relations cross-publi à partir d'un identifiant stable.
- **Rôle « copie carbone »** — quand la source n'a pas de notion de personne stable, on duplique le contenu de l'authorship dans `source_persons` juste pour respecter la contrainte d'unicité, sans bénéfice.

Le chantier consiste à **supprimer le rôle « copie carbone »** en gardant seulement le rôle « identité côté source » là où il a du sens.

## Options

### Option A — Suppression complète de `source_persons`

Tout migre vers `source_authorships` (`orcid` en colonne dédiée, `idref` / `hal_person_id` / `idhal` / `researcher_id` dans `source_data` jsonb).

**Pros** : schéma simplifié, aucune contorsion de synthétisation.

**Cons** :
- Perte de la propagation Étape 0 sous sa forme actuelle. Faisable autrement (via `source_authorships.source_data->>'hal_person_id'`) mais demande à réécrire les queries.
- L'admin UI doublons HAL doit aussi être réécrite.
- Migration des données existantes : ~150 k lignes à dispatcher.

### Option B — Restriction aux sources avec identité d'auteur stable

`source_persons` n'accueille plus que :
- HAL avec `hal_person_id` (les `nokey-*` actuels disparaissent)
- ScanR avec idref
- Theses avec PPN

Les autres normalizers (HAL sans compte, OA, WoS, CrossRef) cessent d'écrire dans `source_persons`. Les champs utiles (`orcid`) migrent sur `source_authorships`.

**Pros** :
- Conserve la sémantique « identité d'auteur côté source » dans son cas légitime.
- L'Étape 0 HAL et l'UI admin doublons restent inchangées.
- Suppression nette des contorsions de synthétisation.

**Cons** :
- Migration nécessaire mais plus ciblée que l'option A.
- Convention asymétrique entre sources (lisible si bien documentée).

### Option C — Statu quo + limitation côté CrossRef seulement

Ne rien changer aux sources existantes, juste convenir que CrossRef ne crée pas de `source_persons` (l'orcid va sur `source_authorships`).

**Pros** : changement minimal pour débloquer le chantier CrossRef.

**Cons** : laisse pourrir les autres cas synthétiques (HAL nokey, ScanR scanr-, etc.). Inégalité injustifiée entre OA/WoS (qui peuplent `source_persons` algorithmiquement) et CrossRef (qui ne le fait pas). Pas de gain architectural net.

## Décisions actées

1. **Option B** retenue — restriction de `source_persons` aux sources avec identifiant auteur stable (HAL+`hal_person_id`, ScanR+idref, theses+PPN).
2. **DELETE** des `source_persons` synthétiques existants après bascule.
3. **Stockage des identifiants normalisés** : nouvelle colonne `source_authorships.identifiers JSONB` dédiée, séparée de `source_data` qui reste pour les extras spécifiques par source.
   - Schéma type : `{"orcid": "0000-...", "idref": "...", "idhal": "...", "researcher_id": "..."}`
   - **Pourquoi pas réutiliser `source_data`** : la colonne est déjà occupée par ScanR (~79 k lignes : `affiliation_ids`, `detected_countries`) et par CrossRef (`affiliations`, `sequence`, `authenticated_orcid`). Mélanger « extras métier par source » et « identifiants normalisés cross-source » dans un même jsonb créerait de la confusion et compliquerait les queries de matching.
4. **Ordre de bascule** : indifférent — toutes les sources doivent être migrées avant de débloquer le chantier CrossRef.

## Phasage proposé

### Phase 0 — Validation ✅
- [x] Re-vérifier les lectures de `source_persons` (cf. liste ci-dessous)
- [x] Identifier d'éventuelles autres lectures côté frontend / API → **aucune** côté front/API directs ✅
- [x] Définir la stratégie de test de non-régression : snapshot avant migration (cf. ci-dessous)

**Carte complète des lectures/écritures (post-validation)**

| Composant | Type | Cas conservé après migration ? | Action |
|---|---|---|---|
| `fetch_unlinked_authorships` (`queries/persons/create.py`) | Read | partiel | Adapter pour lire `source_authorships.identifiers` au lieu du JOIN `source_persons` quand source non-éligible |
| `fetch_hal_account_to_person_map` (`queries/persons/create.py`) | Read | oui | Inchangé (HAL+hal_person_id conservé) |
| `person_profile` (`queries/persons/detail.py`) | Read | partiel | SQL HAL/WoS authors adapté pour `identifiers` |
| `hal_duplicate_accounts` (`queries/persons/admin.py`) | Read | oui | Inchangé |
| ~~`authorships_stats` / `authorships_facets` / `list_authorships` (`queries/authorships.py`)~~ | ~~Read~~ | ~~non~~ | **Supprimé** : code mort (page admin frontend disparue, endpoints non consommés). Phase 1.5 du chantier — fichiers `queries/authorships.py`, `routers/authorships.py`, `tests/.../test_authorships_queries.py` deletés ; classes Pydantic associées retirées de `interfaces/api/models.py` ; `include_router` retiré de `app.py`. |
| `link_authorship` dual-write (`person_repository/_authorships.py`) | Write | oui (HAL) | Inchangé |
| `add_identifier` dual-write (`person_repository/_identifiers.py`) | Write | oui (idhal sur HAL) | Inchangé |
| `merge_persons` (`person_repository/_core.py`) | Write | oui | Inchangé |
| `_SOURCE_CONFIG` (`application/persons.py`) | Config | partiel | Retirer entries OA/WoS/CrossRef (et HAL/ScanR/theses sans ID stable) |
| `repair_hal_nokey_source_persons.py` (CLI) | Write | non | Suppression (cas qui ne se produira plus) |
| `backfill_idhal_person_identifiers.py` (CLI) | Read | oui (HAL) | Inchangé |
| `merge_duplicate_theses.py` (CLI) | Read | partiel | Adapter — JOIN conditionnel selon présence PPN |
| `merge_person_duplicates_by_lab.py` (CLI) | Read | partiel | Compteurs HAL/OA à adapter (OA n'aura plus de `source_person_id`) |
| `deduplicate_hal_source_authorships.py` (CLI) | Read+Write | oui (HAL) | Restera utile pour les HAL+hal_person_id, à toiletter |
| `cleanup_wos_duplicate_authorships.py` (CLI) | Write | non | Devient obsolète |
| `domain/person.py::PersonSourceIds` | Model | oui | Inchangé (encore utilisé pour HAL `source_ids`) |

**Stratégie de test de non-régression**
- Avant migration : snapshot `pg_dump` des tables `persons`, `person_identifiers`, `source_authorships` (sur la base sandbox).
- Après chaque phase : compteurs comparatifs :
  - `SELECT count(*) FROM persons` → strictement stable (ne doit pas changer)
  - `SELECT source, count(*) FROM source_persons GROUP BY source` → drop attendu pour OA/WoS/CrossRef ; HAL/ScanR/theses doivent baisser proportionnellement aux `nokey-*`/`scanr-<seq>`/`nokey-*` synthétiques
  - `SELECT count(*) FROM source_authorships WHERE person_id IS NOT NULL` → strictement stable
  - `SELECT count(*) FROM person_identifiers WHERE status = 'confirmed'` → strictement stable
- Tests d'intégration impactés (cf. `tests/integration/`) à faire passer entre chaque phase.
- Smoke test UI : page personne, admin authorships, admin HAL doublons.

### Phase 1 — Préparer `source_authorships`
- [x] Migration SQL : [`010_add_identifiers_to_source_authorships.sql`](../../infrastructure/db/migrations/010_add_identifiers_to_source_authorships.sql) — `ALTER TABLE source_authorships ADD COLUMN identifiers jsonb`. Schema only, **pas de backfill dans la migration**.
- [x] Script de backfill : [`interfaces/cli/backfill_source_authorships_identifiers.py`](../../interfaces/cli/backfill_source_authorships_identifiers.py)
  - Cursor sur `sa.id` (clé primaire indexée), batches paramétrables (`--batch-size`, défaut 10 000)
  - Logs de progression + ETA par batch
  - Idempotent par défaut (skip rows où `identifiers IS NULL`), `--force` pour tout réécrire
  - `--dry-run` pour compter sans UPDATE
  - Mapping :
    - `sp.orcid` → `identifiers.orcid`
    - `sp.idref` → `identifiers.idref`
    - `sp.source_ids->>'idhal'` → `identifiers.idhal`
    - `sp.source_ids->>'hal_person_id'` → `identifiers.hal_person_id`
    - `sp.source_ids->>'researcher_id'` → `identifiers.researcher_id`
  - Rows où aucun identifiant n'est présent : `identifiers` reste NULL (via `jsonb_strip_nulls` + filtre `!= '{}'::jsonb`)
  - Reprise après KeyboardInterrupt : commit du dernier batch terminé
- [ ] Index GIN sur `identifiers` si les requêtes de matching cross-source en justifient le coût (à reconsidérer après les phases 2-3)
- [ ] Application : `python -m infrastructure.db.migrate` puis `python -m interfaces.cli.backfill_source_authorships_identifiers`

### Phase 1.5 — Préparation : nullable + suppression code mort ✅
- [x] Migration `011_source_person_id_nullable.sql` : `ALTER TABLE source_authorships ALTER COLUMN source_person_id DROP NOT NULL`. Prérequis pour les normalizers qui n'écriront plus de `source_persons`.
- [x] Suppression de l'endpoint admin authorships orphelin (cf. commit `f25f3b6`).

### Phase 2 — Réécriture des normalizers concernés
- [x] **OpenAlex** : `upsert_openalex_source_person` supprimé ; le normalizer met `source_person_id=NULL` et `identifiers={"orcid": ...}` sur les `source_authorships`. `fetch_unlinked_authorships` adapté en LEFT JOIN avec lecture de `sa_auth.identifiers->>'orcid'` et `sa_auth.raw_author_name` pour OA.
- [x] **WoS** : `upsert_wos_source_person` + `upsert_wos_source_persons_batch` + `fetch_wos_source_persons_with_daisng` supprimés ; `process_authorships` simplifié (plus de phase 1 batch source_persons). Identifiants WoS sur `source_authorships.identifiers` : `{"orcid": ..., "researcher_id": ...}`. Pivot des adresses sur `author_position` (au lieu de `source_person_id`). `fetch_unlinked_authorships` étend `oa_orcid`/`oa_full_name` aux WoS (CASE `IN ('openalex', 'wos')`). `fetch_linked_authorships_structured` passé en LEFT JOIN.
- [x] **CrossRef** : `insert_crossref_source_person` supprimé (port + queries) ; `process_authors` posté `source_person_id=NULL` avec `identifiers={"orcid": ...}`. Affiliations brutes restent sur `source_data` comme avant. `fetch_unlinked_authorships` étendu pour inclure CrossRef dans le CASE `IN ('openalex', 'wos', 'crossref')`.
- [x] **theses.fr** : `find_theses_source_person_by_name` + `insert_theses_source_person_new` supprimés. `upsert_source_author` retourne None sans PPN → la `source_authorships` est insérée avec `source_person_id=NULL` et `identifiers={"idref": ppn}` quand PPN. Migration 012 : contrainte UNIQUE relâchée à NULLS DISTINCT (= défaut SQL standard) pour permettre plusieurs `(pub, NULL, NULL)` rows = jurés/rapporteurs theses sans PPN sur une même thèse. Idempotence garantie par `clear_source_authorships_for_publication`, le `ON CONFLICT DO UPDATE` n'est qu'un filet jamais déclenché en pratique. Tests d'intégration adaptés.
- [x] **ScanR** : `find_scanr_source_person_by_name` + `insert_scanr_source_person_new` supprimés. `upsert_scanr_author` retourne None sans idref → la `source_authorships` est insérée avec `source_person_id=NULL` et `identifiers={"orcid": ..., "idref": ...}` (champs filtrés selon présence). Pas de migration supplémentaire nécessaire (ScanR pose toujours `author_position` non-null, pas de cas `(pub, NULL, NULL)`).
- [x] **HAL** : `find_hal_source_person_nokey` + `enrich_hal_source_person` + `insert_hal_source_person_new` supprimés. `upsert_hal_author` retourne None si pas de `hal_person_id` (= comptes HAL identifiés uniquement) ; le cas `0_<form_id>` (auteurs HAL sans compte mais avec form_id, ~154k rows existantes) ainsi que les `nokey-*` sont laissés tomber côté nouvelle écriture, leurs `source_authorships` se rabattent sur `source_person_id=NULL` + `identifiers` (orcid/idref/idhal/hal_person_id selon présence). `fetch_unlinked_authorships` ajusté avec `COALESCE(sa.orcid, sa_auth.identifiers->>'orcid')` et idem pour idref/idhal pour absorber les rows HAL post-phase-2 sans `source_persons`. Le dual-write côté `link_authorship` et `add_identifier` reste pertinent (ne se déclenche que quand `source_person_id` non-null et `hal_person_id` présent → cas légitime conservé).

### Phase 3 — Adapter les lecteurs ✅
- [x] `fetch_unlinked_authorships()` : LEFT JOIN sur `source_persons` + COALESCE(sa.orcid/idref/idhal, sa_auth.identifiers->>...) + CASE OA/WoS/CrossRef pour `oa_orcid`/`oa_full_name`. Adapté progressivement au fil des phases 2 OA, WoS, CrossRef et HAL.
- [x] `fetch_linked_authorships_structured()` : passé en LEFT JOIN (cf. phase 2 WoS) — le caller fait déjà le fallback `parse_raw_author_name`.
- [x] `fetch_hal_account_to_person_map()` : inchangée (HAL avec compte continue d'alimenter `source_persons`)
- [x] `person_profile()` : section WoS migrée au pattern OpenAlex (GROUP BY raw_author_name, ORCID via identifiers). HAL reste sur INNER JOIN source_persons → ne retourne désormais que les comptes HAL identifiés (sémantiquement « comptes HAL liés »).
- [x] `hal_duplicate_accounts()` : inchangée
- [x] `merge_duplicate_theses.py` : LEFT JOIN + fallback `parse_raw_author_name` pour les thèses sans PPN.
- [x] `merge_person_duplicates_by_lab.py` : compteur OA passe de `COUNT(DISTINCT source_person_id)` à `COUNT(DISTINCT raw_author_name)`. HAL reste sur source_person_id (= comptes).
- [x] `repair_hal_nokey_source_persons.py` : supprimé (cas qui ne se reproduira plus).
- [x] ~~Réécrire admin authorships endpoint~~ : code mort, supprimé en phase 1.5

### Phase 4 — Purge des données legacy ✅
- [x] Migration `013_source_authorships_source_person_id_set_null.sql` : passage de la FK `source_authorships.source_person_id` de `ON DELETE CASCADE` (qui aurait supprimé les authorships avec leurs source_persons) à `ON DELETE SET NULL`.
- [x] Script CLI `purge_legacy_source_persons.py` : DELETE en batches des source_persons synthétiques par catégorie (OA / WoS / CrossRef intégralité, HAL `0_<form_id>`+`nokey-*`, ScanR `scanr-*`, theses `nokey-*`). Vérification automatique de la FK avant purge. Idempotent. `--dry-run` pour estimer.
- [x] Re-run du pipeline OK : les normalizers ne créent plus de source_persons synthétiques, le code est cohérent.

### Phase 5 — Schema cleanup ✅
- [x] `source_authorships.source_person_id` déjà nullable (migration 011).
- [x] Suppression des fonctions `delete_*_orphan_*_source_persons` devenues redondantes avec la purge.
- [x] Suppression du CLI one-shot `cleanup_wos_duplicate_authorships.py` (redondant post-purge).
- [x] `schema.sql` régénéré automatiquement par `db/migrate.py`.
- [x] `docs/sources.md` mis à jour : tableau des sources complété (theses.fr + CrossRef ajoutés), section "Nature des entités auteurs" réécrite avec le nouveau rôle restreint de `source_persons` et la colonne `identifiers`.
- [x] `docs/pipeline.md` mis à jour : diagramme normalize, phases persons et authorships.

### Tests de non-régression — bilan a posteriori

- [ ] `SELECT source, count(*) FROM source_persons GROUP BY source` — doit matcher : HAL avec `hal_person_id` uniquement (~47k), ScanR avec idref uniquement, theses avec PPN uniquement, autres = 0.
- [ ] Pipeline `normalize` tourne sans erreur sur un run complet (smoke test).
- [ ] Page personne UI : spot-check sur une dizaine de personnes (la section "comptes HAL" reste visible pour les personnes UCA, la section "auteurs WoS" passe au pattern OA = group by raw_author_name).

## Lien avec les autres chantiers

### CrossRef (en cours)
Le chantier CrossRef est **bloqué tant que ce chantier n'est pas terminé** : la phase 1B du normalizer CrossRef écrit dans `source_persons` avec des clés `<DOI>:<position>` (pattern que cet audit identifie comme inutile). Une fois ce chantier terminé :
- Le normalizer CrossRef sera remanié pour ne plus écrire `source_persons`.
- L'ORCID CrossRef ira sur `source_authorships.identifiers->>'orcid'`.
- `insert_crossref_source_person` sera supprimé.
- Idem pour les phases 1B des autres normalizers algorithmiques.

### Pipeline `personnes`
La logique de matching de fond reste inchangée : elle s'appuie déjà sur `author_name_normalized` + `person_name_forms`. Seule l'Étape 0 (HAL accounts) dépend de `source_persons` — par construction, c'est le cas légitime qu'on conserve.

### Migration progressive
Les phases 1 → 5 sont **indépendamment mergeables**. La phase 1 (ajout colonne + backfill) peut être déployée sans bouger les normalizers ; les sources basculent ensuite une à une.
