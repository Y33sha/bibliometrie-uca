# Ajouter une règle de correction de métadonnée canonique

Procédure d'écriture, branchement et déploiement d'une règle dans `domain/source_publications/correction.py`.

Ce playbook est le *comment*, écrit pour être réutilisé à chaque nouvelle règle.

## Modèle : corrections persistées sur la source_publication

Une correction est une règle déterministe « si tel signal, alors le champ canonique vaut telle valeur ». La phase `metadata_correction` calcule l'effective de chaque `source_publication` et l'écrit **en place** dans ses colonnes typées, le brut source écrasé étant conservé dans le sidecar `raw_metadata`. Le matching et l'agrégation lisent ensuite des colonnes corrigées, sans recalcul.

- **Source unique** : la règle vit dans [`domain/source_publications/correction.py`](../../domain/source_publications/correction.py) (fonction pure, zéro I/O), comme entrée du dict `_RULES`. `effective_metadata(view)` parcourt la cascade et renvoie un `CorrectedFields` (valeur corrigée + règle d'origine par champ).
- **Forme déclarative** : une règle = `{applies_to: {prédicats AND-és}, applies_correction: {champ: valeur cible}}`. Le moteur `_check_predicate` interprète chaque prédicat selon le TypedDict `_AppliesTo`. Une règle qui rentre dans les prédicats listés n'est *que* cette entrée — pas de logique supplémentaire.
- **Réversibilité** : la sous-étape unaire ([`correct_unary.py`](../../application/pipeline/metadata_correction/correct_unary.py)) reconstruit le brut depuis `raw_metadata`, **mappe** le `doc_type` source vers le canonique (`map_doc_type`), applique `effective_metadata`, écrit l'effective dans les colonnes et stashe le brut écrasé sous `raw_metadata.<champ>` avec sa provenance `corrected_by` (le membre `MetadataCorrectionRule`, ou le marqueur `DOC_TYPE_MAP` quand seul le mapping a changé la valeur).
- **Idempotence** : la correction repart toujours du **brut reconstruit**, jamais de la valeur déjà corrigée. Un re-normalize qui réécrit le brut, ou un changement de `journal_type` qui (dé)clenche une règle, est rattrapé au run suivant sans état à entretenir.
- **Cascade par champ** (ordre des dépendances) : `journal_id` → `doc_type` → `oa_status`. `_correct_field(sp, "<field>")` parcourt `_RULES` dans l'ordre d'insertion et retourne la première règle qui (a) corrige le champ demandé et (b) dont tous les prédicats matchent. L'ordre intra-cascade traduit la spécificité du signal (signaux forts d'abord : URL > `journal_type` > titre).
- **Mutation de clé ⇒ réconciliation** : persister une correction qui change `doc_type`, `external_ids` ou `doi` pose `keys_dirty` sur la SP — `doc_type` entre dans le token `metadata_block`, le `doi` est un token. La phase `publications` re-réconcilie ces SP au run suivant.

## Quand utiliser ce playbook

À chaque ajout d'une règle déterministe corrigeant un champ canonique vers une valeur fixe.

Hors-scope : les patterns détectables mais non corrigibles automatiquement (un DOI à préfixe d'éditeur A sur une revue d'éditeur B — preprint légitime ou faux ?). Ils demandent une décision humaine, pas une règle.

## Procédure pas-à-pas

### 1. Caractériser la règle

Avant d'ouvrir un fichier, expliciter :

- **Champ corrigé** (output) : `doc_type`, `journal_id`, `oa_status`.
- **Inputs lus** : quels champs de `SourcePublicationWithJournalView` ? Mono- ou multi-critères ?
- **Condition** : whitelist (sur un set fini de valeurs d'input) ou inconditionnelle ? La whitelist est presque toujours plus défensive — elle épargne les types-référents (`thesis`, `book`, …).
- **Origine de l'input** :
  - intrinsèque à la SP (`title`, `urls`, `doc_type`, `doi`) → rien à câbler ;
  - joint depuis `journals`, déjà projeté (`journal_type`, `oa_model`, `apc_amount`) → idem ;
  - joint depuis une table **hors projection** → étendre la vue (cf. § 4).
- **Input admin-éditable ?** Détermine s'il faut un hook (cf. § 6).
- **Output qui change le clustering ?** Une correction de `doc_type` change le token `metadata_block` de la SP : tester que le rapprochement utilise la valeur corrigée (la persistance pose `keys_dirty`, la réconciliation suit).

### 2. Audit avant de coder

SQL préliminaire pour mesurer l'ampleur et confirmer la déterminance. Au minimum : croiser la condition d'input avec le champ corrigé actuel, repérer les cas ambigus.

```sql
SELECT doc_type::text, count(*) FROM publications
WHERE title_normalized LIKE 'additional file%' GROUP BY 1;
```

Si l'audit révèle un faux positif probable (un cas légitime qui matche mais ne devrait pas être corrigé), durcir la condition (whitelist plus étroite, signal additionnel).

### 3. Implémentation

#### 3.1 Membre de l'enum

Dans `correction.py`, ajouter un membre à `MetadataCorrectionRule`. Convention : `INPUT_CONDITION_TO_OUTPUT` (`THESES_FR_URL_TO_THESIS`, `JOURNAL_TYPE_MEDIA_TO_MEDIA`, `TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET`). Le membre est la provenance inscrite dans `raw_metadata.<champ>.corrected_by`.

#### 3.2 Entrée dans `_RULES`

```python
MetadataCorrectionRule.TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET: {
    "applies_to": {
        "doc_type": frozenset({"article", "other"}),
        "title_prefix_normalized": _SUPPLEMENTARY_CONTENT_TITLE_PREFIXES,
    },
    "applies_correction": {"doc_type": "dataset"},
},
```

Prédicats supportés dans `applies_to` (cf. TypedDict `_AppliesTo`) :

| clé | valeur | sémantique |
|---|---|---|
| `doc_type` | `str` ou `frozenset[str]` | équivalence ou appartenance, case-insensitive |
| `journal_type` | `str` | équivalence sur `sp.journal_type` (joint depuis `journals`) |
| `url_contains` | `str` | substring présente dans au moins une `sp.urls` |
| `doi_contains` | `str` | substring présente dans `sp.doi` (DOI en minuscules) |
| `title_prefix_normalized` | `tuple[str, ...]` | `normalize_text(sp.title)` commence par un des préfixes |
| `title_regex` | `re.Pattern[str]` | `pattern.search(sp.title)` matche |
| `journal_id_present` | `bool` | `(sp.journal_id is not None)` vaut la valeur attendue |

Si la règle a besoin d'un prédicat absent : étendre `_AppliesTo` + ajouter la branche dans `_check_predicate`. Préférer un prédicat réutilisable (qui capturera d'autres règles du même axe) à un prédicat sur-spécialisé.

#### 3.3 Position dans le dict (priorité)

`_RULES` est un dict ordonné : l'ordre d'insertion = la priorité. `_correct_field` renvoie sur le premier match. Placer une règle plus tôt lui donne priorité.

#### 3.4 Constantes locales

Patterns (regex, tuples de préfixes) réutilisés : déclarés en module-level avec préfixe `_`, juste au-dessus de `_RULES`, commentés sur *pourquoi* cette forme (« set ciblé plutôt que `'supplementary '` large pour éviter les faux positifs »). Les whitelists triviales utilisées une seule fois restent inline.

#### 3.5 Champ corrigé absent de `_AppliesCorrection`

Pour corriger un champ absent de `_AppliesCorrection` (`oa_status`, `journal_id`) : ajouter la clé au TypedDict, puis le champ dans `effective_metadata` :

```python
return CorrectedFields(
    doc_type=_correct_field(sp, "doc_type"),
    oa_status=_correct_field(sp, "oa_status"),
)
```

`_correct_field` est paramétrique sur le champ — aucune logique additionnelle. La sous-étape unaire stashe et persiste le champ ajouté en l'inscrivant dans `_UNARY_FIELDS` ([`correct_unary.py`](../../application/pipeline/metadata_correction/correct_unary.py)).

### 4. Étendre la projection si nécessaire (rare)

Si l'input vient d'une table hors projection :

1. champ ajouté à `SourcePublicationWithJournalView` ([`views.py`](../../domain/source_publications/views.py)) ;
2. projeté dans la requête `fetch_for_unary_correction` ([`metadata_correction.py`](../../infrastructure/queries/pipeline/metadata_correction.py)) + le port `SourcePublicationForCorrection` ([`metadata_correction`](../../application/ports/pipeline/metadata_correction.py)) ;
3. reporté dans `_view_from_row` (`correct_unary.py`).

Alternative écartée : threader un repo dans toutes les signatures. Beaucoup plus invasif sans bénéfice métier — la vue (champs joints à la lecture) garde `effective_metadata` pure.

### 5. Tests

Dans [`tests/unit/domain/source_publications/test_correction.py`](../../tests/unit/domain/source_publications/test_correction.py), une classe `TestNomDeLaRègle` :

- **Cas positif** : input matche → `effective_metadata` pose la correction avec la bonne valeur et le bon membre.
- **Cas no-op** : input matche mais la valeur courante est déjà la cible → champ `None`.
- **Cas négatif** : input ne matche pas → no-op.
- **Robustesse** : variations attendues du signal (casse, espaces, accents).
- **Interaction cascade** : combinaison avec une règle plus prioritaire → la prioritaire gagne.

### 6. Hooks admin (conditionnel — seulement si input admin-éditable)

Si la règle consomme un champ que l'admin modifie en base via l'UI (`journal.journal_type`, `journal.oa_model`) :

1. **Recompute des corrections** : `correct_for_journal` (`correct_unary.py`) recompute et persiste les corrections des SP du journal, à enchaîner avec `refresh_from_sources` des publications impactées.
2. **Service de requalification** dans `application/<table>.py`, modèle [`requalify_publications_for_journal`](../../application/journals.py) (mode `dry_run` pour le preview, mode apply qui recompute + refresh + audit).
3. **Repo** : `PublicationRepository.find_ids_by_<key>` (lecture de `publications` par le repo publications — discipline ISP).
4. **Endpoints API** : `GET /api/<table>/{id}/<field>-change-impact?new_<field>=X` → `{count: N}` (preview, `dry_run=True`) ; `PUT /api/<table>/{id}` détecte le changement et déclenche la requalification synchrone dans la même transaction.
5. **Modèles Pydantic** dédiés dans `interfaces/api/models/<table>.py` (jamais `body: dict`).
6. **Frontend** : appel preview au save, modale de confirmation, **message générique** sur le nombre de publications recalculées (l'agrégation finale dépend de toutes les sources, pas seulement de l'input modifié).

### 7. Rattrapage du stock

Une règle ajoutée à `_RULES` ne s'applique qu'aux SP retraitées. Pour l'appliquer au stock :

- **Règle intrinsèque ou journal-jointe** : rejouer la phase `metadata_correction` (`run_pipeline.py --only metadata_correction`) — la sous-étape unaire recalcule l'effective de chaque SP depuis le brut, pose la correction, et marque `keys_dirty` si elle change `doc_type`/`doi`/`external_ids`. Enchaîner `run_pipeline.py --only publications` pour réconcilier les SP re-dirtiées et rafraîchir leurs publications.
- **Sous-ensemble ciblé** : [`redirty_publications --where "<condition>"`](../../interfaces/cli/maintenance/redirty_publications.py) restreint la réconciliation aux SP visées, après le recompute de correction.

### 8. Documentation

Le catalogue des règles actives est le dict `_RULES` lui-même (entrées + commentaire de motivation inline au-dessus de chaque entrée). Pas de duplication dans une fiche séparée. Si la règle illustre une combinaison input/output non couverte ci-dessous, compléter le § Exemples.

## Corrections relationnelles (cluster)

Les règles `_RULES` décident d'une SP **seule**. Certaines corrections demandent de regarder le **groupe de SP partageant une clé** : quand ce groupe réunit des œuvres distinctes, la clé partagée est erronée et doit être nullée sur le mauvais côté, sinon le matching les fusionnerait à tort.

La décision est dans `detect_erroneous_key_holders` (`correction.py`) — pure, **agnostique de la clé** (elle raisonne sur les `doc_type` du groupe). La sous-étape [`correct_by_cluster.py`](../../application/pipeline/metadata_correction/correct_by_cluster.py) regroupe par DOI brut, demande au domaine quels DOI sont erronés, nulle le DOI fautif et stashe le brut sous la provenance `DistinctMergeCase`. Cas couverts : ouvrage + chapitre au même DOI (le chapitre perd le DOI) ; chapitres de titres réellement distincts au même DOI (le DOI de l'ouvrage hôte, recopié à tort — tous le perdent).

Pour une nouvelle correction relationnelle : ajouter un membre `DistinctMergeCase` (l'énoncé métier dans son commentaire) + la branche de détection dans `detect_erroneous_key_holders`, et regrouper sur la clé voulue côté sous-étape cluster.

## Exemples concrets

### Règle SP-intrinsèque mono-critère

**`THESES_FR_URL_TO_THESIS`** — URL theses.fr (sans `journal_id`) ⇒ `doc_type = thesis`.

- Input : `sp.urls` + `journal_id_present: False` (une SP theses.fr *avec* journal est un article publié, traité par `THESIS_WITH_JOURNAL_TO_ARTICLE`).
- Hook admin : non (URL non éditable).
- Référence : [`correction.py` — entrée `THESES_FR_URL_TO_THESIS`](../../domain/source_publications/correction.py)

### Règle SP-intrinsèque multi-critères avec whitelist + set de signaux

**`TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET`** — titre dans `_SUPPLEMENTARY_CONTENT_TITLE_PREFIXES` + `doc_type ∈ {article, other}` ⇒ `dataset`.

- Set de préfixes ciblé (pas `'supplementary '` brut, qui matcherait « Supplementary roles of X »). `dataset` exclu (no-op naturel) ; types-référents épargnés.
- Référence : [`correction.py` — entrée `TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET`](../../domain/source_publications/correction.py)

### Règle journal-jointe + admin-éditable

**`JOURNAL_TYPE_MEDIA_TO_MEDIA`** — `journal.journal_type = 'media'` ⇒ `doc_type = media`.

- Input : `sp.journal_type` (joint via `SourcePublicationWithJournalView`).
- Hook admin : oui — service [`requalify_publications_for_journal`](../../application/journals.py), endpoint `GET /api/journals/{id}/type-change-impact`, requalification synchrone dans le `PUT`, modale frontend.
- Référence : [`correction.py` — entrée `JOURNAL_TYPE_MEDIA_TO_MEDIA`](../../domain/source_publications/correction.py)

## Anti-patterns

- **Muter `source_publications` à l'ingestion** (dans le normalizer) : casse l'auditabilité et la réversibilité. La correction est une dérivation dans `correction.py`, persistée par la phase `metadata_correction` qui conserve le brut dans `raw_metadata`.
- **Encoder la règle en SQL pur** (vue, trigger, UPDATE non audité) : perd la trace `raw_metadata.<champ>.corrected_by` et le brut réversible.
- **Cascade implicite** : deux règles touchant le même champ sans ordre explicite → non-déterministe. L'ordre des entrées dans `_RULES` est la convention.
- **Hook admin sans service** : déclencher `refresh_from_sources` depuis le router. Le service propriétaire (`application/<table>.py`) reste l'unique point d'écriture côté pubs.

## Limites du périmètre

Les patterns *détectables mais non corrigibles automatiquement* (DOI préfixe d'éditeur incohérent — preprint légitime ou faux) demandent une décision humaine, hors de ce playbook : revue manuelle des incohérences.
