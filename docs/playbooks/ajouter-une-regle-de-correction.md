# Ajouter une règle de correction de métadonnée canonique

Procédure d'écriture, branchement et déploiement d'une règle dans `domain/publications/correction.py`.

Le chantier [METIER_metadata-correction](../chantiers/METIER_metadata-correction.md) explique le *pourquoi* (patron architectural, frontière correction vs détection-seulement, cascade par champ).
Ce playbook est le *comment*, écrit pour être réutilisé à chaque nouvelle règle.

## Quand utiliser ce playbook

À chaque ajout d'une règle déterministe (« si tel signal, alors corrige tel champ canonique vers telle valeur »).
Hors-scope : les patterns détectables mais non corrigibles automatiquement (cf. [METIER_metadata-correction § Frontière correction vs détection-seulement](../chantiers/METIER_metadata-correction.md#frontière-correction-vs-détection-seulement)).

## Points fixes de l'architecture

- **Source unique** : la règle vit dans `domain/publications/correction.py` (fonction pure, zéro I/O), comme entrée du dict `_RULES`.
- **Forme déclarative** : une règle = `{applies_to: {prédicats AND-és}, applies_correction: {champ: valeur cible}}`. Le moteur `_check_predicate` interprète chaque prédicat selon le TypedDict `_AppliesTo`. Pour une règle qui rentre dans les prédicats listés (`doc_type`, `journal_type`, `url_contains`, `title_prefix_normalized`, `title_regex`), on n'écrit que cette entrée — pas de logique supplémentaire.
- **Audit** : chaque application réelle pose `publications.meta.<field>_corrected_by = <RULE_MEMBER>`.
- **Deux call-sites** :
  - `application/publications.py::apply_corrections` au refresh — sur chaque `source_publication` agrégée
  - `application/pipeline/publications/match_or_create_publications.py::process_document` à l'entrée dédup — sur l'orphelin
- **Cascade par champ** (ordre des dépendances) : `journal_id` → `doc_type` → `oa_status`. `_correct_field(sp, "<field>")` parcourt `_RULES` dans l'ordre d'insertion et retourne la première règle qui (a) corrige le champ demandé et (b) dont tous les prédicats matchent. L'ordre intra-cascade traduit la spécificité du signal (cf. § 3 ci-dessous).

## Procédure pas-à-pas

### 1. Caractériser la règle

Avant d'ouvrir un fichier, expliciter (idéalement par écrit dans le commit ou un brouillon) :

- **Champ corrigé** (output) : `doc_type`, `journal_id`, `oa_status`, …
- **Inputs lus** : quels champs de `SourcePublicationWithJournalView` ? Mono-critère ou multi-critères ?
- **Condition** : whitelist (acte sur un set fini de valeurs d'input) ou inconditionnelle ? La whitelist est presque toujours plus défensive.
- **Origine de l'input** :
  - Intrinsèque à la publication (`title`, `urls`, `doc_type`, `doi`, …) → rien à câbler côté DTO.
  - Joint depuis une table déjà projetée (`journal_type`, `oa_model`, `apc_amount`) → idem.
  - Joint depuis une table **hors projection actuelle** (publisher, doi_prefixes, …) → étendre `SourcePublicationWithJournalView` + sa projection SQL (cf. § 4).
- **Input admin-éditable ?** Détermine s'il faut un hook (cf. § 6).
- **Output qui change le routage de la dédup ?** `doc_type=thesis` et `doc_type=proceedings` ont des branches dédiées dans `match_or_create.process_document` (matching par titre/année). Toute règle qui produit l'une de ces valeurs doit être vérifiée à l'entrée dédup, pas seulement au refresh — c'est déjà le cas via le double call-site, mais il faut tester explicitement le scénario.

### 2. Audit avant de coder

SQL préliminaire pour mesurer l'ampleur et confirmer la déterminance.
Au minimum : croiser la condition d'input avec le champ corrigé actuel, repérer les cas ambigus.

Exemple (règle `TITLE_ADDITIONAL_FILE_TO_OTHER`) :

```sql
SELECT doc_type::text, count(*) FROM publications
WHERE title_normalized LIKE 'additional file%' GROUP BY 1;
```

Si l'audit révèle un faux-positif probable (un cas légitime qui matche la condition mais ne devrait pas être corrigé), durcir la condition (whitelist plus étroite, signal additionnel).

### 3. Implémentation

#### 3.1 Member de l'enum

Dans [`domain/publications/correction.py`](../../domain/publications/correction.py), ajouter un member à `MetadataCorrectionRule`.
Convention de nommage : `INPUT_CONDITION_TO_OUTPUT` (ex. `THESES_FR_URL_TO_THESIS`, `JOURNAL_TYPE_MEDIA_TO_MEDIA`, `TITLE_ADDITIONAL_FILE_TO_OTHER`).

#### 3.2 Entrée dans `_RULES`

Ajouter une entrée au dict `_RULES`, mappant le member créé à `{applies_to, applies_correction}`. Exemple :

```python
MetadataCorrectionRule.TITLE_ADDITIONAL_FILE_TO_DATASET: {
    "applies_to": {
        "doc_type": frozenset({"article", "other"}),
        "title_prefix_normalized": ("additional file",),
    },
    "applies_correction": {"doc_type": "dataset"},
},
```

Prédicats supportés dans `applies_to` (cf. TypedDict `_AppliesTo`) :

| clé | valeur | sémantique |
|---|---|---|
| `doc_type` | `str` ou `frozenset[str]` | équivalence ou appartenance, comparaison case-insensitive |
| `journal_type` | `str` | équivalence sur `sp.journal_type` |
| `url_contains` | `str` | substring présente dans au moins une `sp.urls` |
| `title_prefix_normalized` | `tuple[str, ...]` | `normalize_text(sp.title)` commence par un des préfixes |
| `title_regex` | `re.Pattern[str]` | `pattern.search(sp.title)` matche |

Si la règle a besoin d'un prédicat absent de la liste ci-dessus, étendre `_AppliesTo` + ajouter la branche correspondante dans `_check_predicate`. Préférer un prédicat réutilisable (qui capturera d'autres règles du même axe) à un prédicat sur-spécialisé à une seule règle.

#### 3.3 Position dans le dict (priorité)

`_RULES` est un dict ordonné : l'ordre d'insertion = la priorité de la cascade. `_correct_field` renvoie sur le premier match, donc placer une règle plus tôt lui donne priorité sur les suivantes.

#### 3.4 Constantes locales

Pour les patterns (regex, tuples de préfixes) ou whitelists réutilisées par plusieurs règles, déclarer en module-level avec préfixe `_`, juste au-dessus du dict `_RULES`. Commenter brièvement *pourquoi* le set/pattern a la forme choisie (« set ciblé plutôt que `'supplementary '` large pour éviter les faux positifs »).

Les whitelists triviales (`frozenset({"article", "book_chapter"})`) qui ne sont utilisées qu'une fois peuvent rester inline dans le dict — pas de constante de cérémonie.

#### 3.5 Champ corrigeable absent de `_AppliesCorrection`

Pour une règle qui corrige un champ absent de `_AppliesCorrection` (`oa_status`, `journal_id`…) : ajouter la clé dans `_AppliesCorrection`, puis brancher le champ dans `effective_metadata` :

```python
return CorrectedFields(
    doc_type=_correct_field(sp, "doc_type"),
    oa_status=_correct_field(sp, "oa_status"),
)
```

`_correct_field` est paramétrique sur le champ — aucune logique additionnelle.

### 4. Étendre la projection si nécessaire (rare)

Si l'input nécessite un champ joint depuis une table hors projection actuelle :

1. Ajouter le champ à `SourcePublicationWithJournalView` ([domain/source_publications/views.py](../../domain/source_publications/views.py)).
2. Ajouter le champ dans `_SourcePublicationViewRow` ([infrastructure/repositories/publication_repository.py](../../infrastructure/repositories/publication_repository.py)) + le JOIN dans `get_source_publications`.
3. Côté match_or_create : ajouter le champ à `SourcePublicationRow` + `fetch_orphan_in_perimeter_source_publications` + `_view_from_row` (cf. [match_or_create_publications.py](../../application/pipeline/publications/match_or_create_publications.py)).

Alternative écartée : threader un repo dans toutes les signatures (refresh + match_or_create + merges). Beaucoup plus invasif sans bénéfice métier. Cf. décision tranchée dans [METIER_metadata-correction § Phase 3](../chantiers/METIER_metadata-correction.md#phase-3--première-règle-admin-sensible--introduction-des-hooks).

### 5. Tests

Dans [`tests/unit/domain/publications/test_correction.py`](../../tests/unit/domain/publications/test_correction.py), créer une classe `TestNomDeLaRègle` couvrant a minima :

- **Cas positif** : input matche → correction posée avec la bonne valeur et le bon member.
- **Cas no-op** : input matche mais la valeur courante est déjà la cible → `effective_metadata(...).doc_type is None`.
- **Cas négatif** : input ne matche pas → no-op.
- **Robustesse de la condition** : variations attendues du signal (case-sensitivity, espaces, accents, etc.).
- **Interaction cascade** : combinaison avec une règle plus prioritaire → la plus prioritaire gagne.

Si la règle change le `doc_type` vers une valeur qui route la dédup (`thesis`, `proceedings`) : ajouter un test d'intégration sur `match_or_create.process_document` qui vérifie que le matching utilise la valeur corrigée.

### 6. Hooks admin (conditionnel — seulement si input admin-éditable)

Si la règle consomme un champ que l'admin peut modifier en base via l'UI (`journal.journal_type`, `publisher.publisher_type`, `journal.oa_model`, …), il faut :

1. **Service de requalification** dans `application/<table>.py`, modèle [`requalify_publications_for_journal`](../../application/journals.py) (mode `dry_run` pour le preview, mode apply qui rejoue `refresh_from_sources` sur chaque pub impactée + audit `<table>.type_requalified`).
2. **Repo** : `PublicationRepository.find_ids_by_<key>` (lecture de `publications` par le repo publications, pas par celui de la table source — discipline ISP).
3. **Endpoints API** :
   - `GET /api/<table>/{id}/<field>-change-impact?new_<field>=X` → `{count: N}` (preview, appelle le service en `dry_run=True`).
   - `PUT /api/<table>/{id}` détecte le changement et déclenche la requalification synchrone dans la même transaction.
4. **Modèles Pydantic** dédiés dans `interfaces/api/models/<table>.py` (jamais `body: dict`).
5. **Frontend** : appel preview au save, modale de confirmation. **Message générique** sur le nombre de publications recalculées — ne pas promettre une valeur cible, l'agrégation finale dépend de toutes les sources de chaque publication, pas seulement de l'input modifié.

### 7. Rattrapage du stock

Sauf si on prévoit un full rerun imminent du pipeline, écrire un script ciblé pour reclasser le stock existant.

- **Règle intrinsèque aux métadonnées de la publication** (input non éditable) : one-shot dans [`interfaces/cli/oneshot/`](../../interfaces/cli/oneshot/), nommé d'après la règle. Pré-filtre SQL léger + loop `refresh_from_sources`, commit par batch. Modèle : [`refresh_publications_with_additional_file_title.py`](../../interfaces/cli/oneshot/refresh_publications_with_additional_file_title.py).
- **Règle admin-éditable** : si la règle débarque alors que des inputs ont déjà été posés en base sans hook (cas typique : `journal_type=media` typé avant l'existence de la règle), réutiliser [`maintenance/refresh_publications_for_journal_type.py`](../../interfaces/cli/maintenance/refresh_publications_for_journal_type.py). Cet outil est paramétrable et survit aux règles futures du même axe.

### 8. Documentation

Le catalogue des règles actives est le dict `_RULES` (entrées + commentaire de motivation inline au-dessus de chaque entrée). Pas de duplication dans une fiche séparée.

- Si la règle illustre une combinaison input/output non couverte par les exemples ci-dessous : compléter le § Exemples avec un cas concret.

## Exemples concrets

### Règle SP-intrinsèque mono-critère

**`THESES_FR_URL_TO_THESIS`** — URL theses.fr ⇒ `doc_type = thesis`.

- Input : `sp.urls`
- Output : `doc_type`
- Whitelist : aucune (la règle est inconditionnelle sur le signal URL)
- Hook admin : non (URL non éditable)
- Rattrapage : pas de script dédié, appliqué au full rerun pipeline
- Référence : [`correction.py` — entrée `THESES_FR_URL_TO_THESIS`](../../domain/publications/correction.py)

### Règle SP-intrinsèque multi-critères avec whitelist + set de signaux

**`TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET`** — titre dans `_SUPPLEMENTARY_CONTENT_TITLE_PREFIXES` (additional file, supplementary material/data/info/file/dataset, data from) + `doc_type ∈ {article, other}` ⇒ `doc_type = dataset`.

- Inputs : `sp.title` (via le prédicat `title_prefix_normalized`, qui normalise en interne) + `sp.doc_type`
- Whitelist : `frozenset({"article", "other"})` inline dans l'entrée — `dataset` est laissé tel quel (déjà adéquat) ; les autres types (`thesis`, `book_chapter`, …) sont épargnés (titre suspect mais on ne corrige pas aveuglément).
- Set de préfixes plutôt qu'un préfixe unique : pattern récurrent (fichiers complémentaires exposés par DataCite/Dryad/Zenodo/IFREMER comme entités à part entière). Le set est **ciblé**, pas large : on ne prend pas `'supplementary '` brut pour éviter de matcher par accident un vrai article du type "Supplementary roles of X". Ajouter un préfixe à `_SUPPLEMENTARY_CONTENT_TITLE_PREFIXES` est de la maintenance courante, pas un chantier dédié.
- Audit ayant motivé la whitelist : 274 "additional file" (186 article + 46 other à reclasser, 42 dataset no-op) + 22 "supplementary …" + 7 "data from …" non-dataset. 100 % DataCite sur les cas observés ⇒ pas besoin de croiser avec le DOI-RA.
- Hook admin : non
- Rattrapage : [`oneshot/refresh_publications_with_supplementary_content_title.py`](../../interfaces/cli/oneshot/refresh_publications_with_supplementary_content_title.py) — le pré-filtre SQL mirror la liste `_SUPPLEMENTARY_CONTENT_TITLE_PREFIXES`.
- Référence : [`correction.py` — entrée `TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET`](../../domain/publications/correction.py)

### Règle journal-jointe + admin-éditable

**`JOURNAL_TYPE_MEDIA_TO_MEDIA`** — `journal.journal_type = 'media'` ⇒ `doc_type = media`.

- Input : `sp.journal_type` (joint depuis `journals` via la projection `SourcePublicationWithJournalView`)
- Whitelist : aucune (inconditionnel sur le signal journal)
- Hook admin : oui — `journal_type` est éditable par l'admin. Service [`requalify_publications_for_journal`](../../application/journals.py), endpoint `GET /api/journals/{id}/type-change-impact`, requalification synchrone dans le `PUT`, modale frontend.
- Rattrapage : [`maintenance/refresh_publications_for_journal_type.py --journal-type media`](../../interfaces/cli/maintenance/refresh_publications_for_journal_type.py)
- Référence : [`correction.py` — entrée `JOURNAL_TYPE_MEDIA_TO_MEDIA`](../../domain/publications/correction.py)

## Anti-patterns

- **Muter `source_publications` à l'ingestion** (ex. dans le normalizer) : viole le principe d'inviolabilité, casse l'auditabilité. La correction doit toujours être une *dérivation* dans `correction.py`. Cf. [feedback `source_publications inviolable`](../../docs/chantiers/METIER_metadata-correction.md).
- **Encoder la règle en SQL pur (vue, trigger, UPDATE one-shot non auditté)** : perd la trace `meta.X_corrected_by` et la réversibilité.
- **Cascade implicite** : deux règles qui touchent le même champ sans ordre explicite ⇒ comportement non-déterministe. L'ordre des entrées dans `_RULES` est la convention.
- **Hook admin sans service** : déclencher `refresh_from_sources` directement depuis le router. Le service propriétaire (`application/<table>.py`) reste l'unique point d'écriture côté pubs (cf. [feedback `Propriété des services sur les tables`](../../docs/chantiers/METIER_metadata-correction.md)).

## Limites du périmètre

Les patterns *détectables mais non corrigibles automatiquement* (ex. DOI préfixe d'éditeur A sur revue d'éditeur B — peut être un preprint légitime, peut être un faux) ne relèvent pas de ce playbook : ils nécessitent une décision humaine. À traiter dans un chantier dédié de revue manuelle des incohérences.
