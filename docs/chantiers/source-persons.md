# Chantier — Repenser `source_persons`

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

### Phase 0 — Validation
- [ ] Re-vérifier les lectures de `source_persons` listées dans l'audit (`fetch_unlinked_authorships`, `person_profile`, `hal_duplicate_accounts`, `repair_hal_nokey_source_persons.py`, `fetch_hal_account_to_person_map`)
- [ ] Identifier d'éventuelles autres lectures côté frontend / API
- [ ] Décider de la stratégie de test de non-régression (snapshot des `persons` et `authorships` avant migration)

### Phase 1 — Préparer `source_authorships`
- [ ] Migration SQL : `ALTER TABLE source_authorships ADD COLUMN identifiers jsonb`
- [ ] Backfill : pour chaque `source_authorships`, copier les champs identifiants de `source_persons` joint via `source_person_id` :
  - `orcid` → `identifiers.orcid`
  - `idref` → `identifiers.idref`
  - `source_ids->>'idhal'` → `identifiers.idhal`
  - `source_ids->>'hal_person_id'` → `identifiers.hal_person_id`
  - `source_ids->>'researcher_id'` (WoS) → `identifiers.researcher_id`
- [ ] Index GIN sur `identifiers` si les requêtes de matching cross-source en justifient le coût

### Phase 2 — Réécriture des normalizers concernés
- [ ] OpenAlex : ne plus écrire `source_persons`, mettre les identifiants directement sur `source_authorships.identifiers`
- [ ] WoS : idem (`orcid` + `researcher_id`)
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
