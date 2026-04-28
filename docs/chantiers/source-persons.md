# Chantier — Repenser `source_persons`
Commencé le 2026-04-28

## Contexte

La table `source_persons` est aujourd'hui peuplée par tous les normalizers, indépendamment de l'utilité réelle. Pour les sources sans identifiant auteur stable (OpenAlex, WoS, CrossRef, et le cas HAL « pas de compte HAL identifié »), on synthétise un `source_id` artificiel pour respecter la contrainte `UNIQUE(source, source_id)`. Conséquence pratique : on crée une ligne `source_persons` par `source_authorships` dans ces cas, sans bénéfice net.

Ce doc audit l'usage existant et propose un découpage en chantier dédié.

## État actuel — résumé de l'audit

### Patterns d'écriture par source

| Source | `source_id` | Stable ? | Champs spécifiques exploités |
|---|---|---|---|
| HAL avec compte | `hal_person_id` | ✅ | `source_ids.hal_person_id`, `idhal`, `orcid`, `idref` |
| HAL sans compte | `nokey-<seq>` | ❌ synthétique | (aucun, just le nom) |
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

**Carte complète des lecteurs/écritures (post-validation)**

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
- [ ] CrossRef : idem (juste `orcid`)
- [ ] HAL : ne créer `source_persons` qu'avec un `hal_person_id` ; pour les comptes anonymes, identifiants sur `source_authorships.identifiers`
- [ ] ScanR : ne créer `source_persons` qu'avec un idref ; idem pour le reste
- [ ] Theses : ne créer `source_persons` qu'avec un PPN ; idem pour le reste

### Phase 3 — Adapter les lecteurs
- [ ] `fetch_unlinked_authorships()` : lit les identifiants depuis `source_authorships.identifiers` + JOIN `source_persons` seulement pour les sources éligibles
- [ ] `fetch_hal_account_to_person_map()` : reste inchangée (HAL avec compte continue d'alimenter `source_persons`)
- [ ] `person_profile()` : SQL HAL/WoS authors adapté pour lire `identifiers`
- [ ] `hal_duplicate_accounts()` : reste inchangée
- [ ] `repair_hal_nokey_source_persons.py` : devient inutile → suppression
- [x] ~~Réécrire admin authorships endpoint~~ : code mort, supprimé en phase 1.5

### Phase 4 — Purge des données legacy
- [ ] DELETE des `source_persons` orphelines (sources OA/WoS/CrossRef, HAL `nokey-*`, ScanR `scanr-*`, theses `nokey-*`)
- [ ] Suppression de la FK `source_authorships.source_person_id` ou nullable selon les cas restants
- [ ] Re-run du pipeline pour vérifier l'idempotence

### Phase 5 — Schema cleanup
- [ ] Rendre `source_authorships.source_person_id` nullable (pour les sources qui n'alimentent plus `source_persons`)
- [ ] Mettre à jour `schema.sql` et la doc (notamment `docs/sources.md`)

### Tests de non-régression à prévoir tout du long
- [ ] Compte de personnes canoniques avant/après stable
- [ ] Page personne (UI) montre les mêmes infos
- [ ] Admin HAL doublons fonctionne identiquement
- [ ] Étape 0 du pipeline persons propage correctement les `person_id` HAL
- [ ] Counts par source dans `source_persons` après migration matchent l'attendu (HAL=comptes identifiés uniquement, ScanR=idref-only, theses=PPN-only, autres=0)

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
Les phases 1 → 5 sont **indépendamment mergeable**. La phase 1 (ajout colonne + backfill) peut être déployée sans bouger les normalizers ; les sources basculent ensuite une à une.
