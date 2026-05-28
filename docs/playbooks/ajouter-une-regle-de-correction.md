# Ajouter une règle de correction de métadonnée canonique

Procédure d'écriture, branchement et déploiement d'une règle dans `domain/publications/correction.py`.

Le chantier [METIER_metadata-correction](../chantiers/METIER_metadata-correction.md) explique le *pourquoi* (patron architectural, frontière correction vs détection-seulement, cascade par champ).
Ce playbook est le *comment*, écrit pour être réutilisé à chaque nouvelle règle.

## Quand utiliser ce playbook

À chaque ajout d'une règle déterministe (« si tel signal, alors corrige tel champ canonique vers telle valeur »).
Hors-scope : les patterns détectables mais non corrigibles automatiquement (cf. [METIER_metadata-correction § Frontière correction vs détection-seulement](../chantiers/METIER_metadata-correction.md#frontière-correction-vs-détection-seulement)).

## Points fixes de l'architecture

- **Source unique** : la règle vit dans `domain/publications/correction.py` (fonction pure, zéro I/O).
- **Audit** : chaque application réelle pose `publications.meta.<field>_corrected_by = <RULE_MEMBER>`.
- **Deux call-sites** :
  - `application/publications.py::apply_corrections` au refresh — sur chaque SP agrégée
  - `application/pipeline/publications/match_or_create_publications.py::process_document` à l'entrée dédup — sur l'orphelin
- **Cascade par champ** (ordre déterministe) : `journal_id` → `doc_type` → `oa_status`. Ajouter une nouvelle règle = ajouter une branche dans `_correct_<field>`. L'ordre intra-cascade traduit la spécificité du signal (cf. § 3 ci-dessous).

## Procédure pas-à-pas

### 1. Caractériser la règle

Avant d'ouvrir un fichier, expliciter (idéalement par écrit dans le commit ou un brouillon) :

- **Champ corrigé** (output) : `doc_type`, `journal_id`, `oa_status`, …
- **Inputs lus** : quels champs de `SourcePublicationWithJournalView` ? Mono-critère ou multi-critères ?
- **Condition** : whitelist (acte sur un set fini de valeurs d'input) ou inconditionnelle ? La whitelist est presque toujours plus défensive.
- **Origine de l'input** :
  - SP-intrinsèque (`title`, `urls`, `doc_type`, `doi`, …) → rien à câbler côté DTO.
  - Joint depuis une table déjà projetée (`journal_type`, `oa_model`, `apc_amount`) → idem.
  - Joint depuis une table **pas encore** projetée (publisher, doi_prefixes, …) → étendre `SourcePublicationWithJournalView` + sa projection SQL (cf. § 4).
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

#### 3.2 Branche dans la cascade

Dans la fonction `_correct_<field>` correspondante, ajouter la condition.

**Position dans la cascade** : par défaut **en fin**. La cascade renvoie sur le premier match, donc placer une règle plus tôt revient à lui donner priorité sur les suivantes.
La priorité reflète la **spécificité du signal** :

- URL spécifique (`theses.fr/`, `dumas.`) : plus spécifique → haut de cascade
- Type de revue admin-typé (`journal_type=media`) : moins spécifique → milieu
- Préfixe de titre générique (`additional file`) : moins spécifique → bas

Si tu hésites, audit + 1-2 cas réels qui croisent deux règles concurrentes te diront ce qui est plus informatif.

#### 3.3 Constantes locales

Pour les whitelists ou marqueurs textuels, déclarer des constantes module-level avec préfixe `_` :

```python
_ADDITIONAL_FILE_TITLE_PREFIX = "additional file"
_ADDITIONAL_FILE_DEMOTE_FROM = frozenset({"article"})
```

Commenter brièvement *pourquoi* le set est étroit (« `dataset` est déjà adéquat, on l'épargne »).

#### 3.4 Normalisation des inputs textuels

Pour les comparaisons sur `title`, `container_title`, etc. : passer par `domain.normalize.normalize_text` plutôt que `str.lower()` — c'est ce que fait `publications.title_normalized` côté DB, donc les conditions Python alignées avec un éventuel pré-filtrage SQL.

### 4. Étendre la projection si nécessaire (rare)

Si l'input nécessite un nouveau champ joint depuis une table pas encore projetée :

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

- **Règle SP-intrinsèque** (input non éditable) : one-shot dans [`interfaces/cli/oneshot/`](../../interfaces/cli/oneshot/), nommé d'après la règle. Pré-filtre SQL léger + loop `refresh_from_sources`, commit par batch. Modèle : [`refresh_publications_with_additional_file_title.py`](../../interfaces/cli/oneshot/refresh_publications_with_additional_file_title.py).
- **Règle admin-éditable** : si la règle débarque alors que des inputs ont déjà été posés en base sans hook (cas typique : `journal_type=media` typé avant l'existence de la règle), réutiliser [`maintenance/refresh_publications_for_journal_type.py`](../../interfaces/cli/maintenance/refresh_publications_for_journal_type.py). Cet outil est paramétrable et survit aux règles futures du même axe.

### 8. Documentation

- Cocher la règle dans [METIER_metadata-correction.md § Phase 4+](../chantiers/METIER_metadata-correction.md#phase-4--règles-suivantes-au-fil-de-leau) avec une ligne et le commit ref.
- Si la règle inaugure un nouveau **type de règle** (combinaison input/output non-encore-vue) : enrichir ce playbook avec un exemple concret en § Exemples ci-dessous.

## Exemples concrets

### Règle SP-intrinsèque mono-critère

**`THESES_FR_URL_TO_THESIS`** — URL theses.fr ⇒ `doc_type = thesis`.

- Input : `sp.urls`
- Output : `doc_type`
- Whitelist : aucune (la règle est inconditionnelle sur le signal URL)
- Hook admin : non (URL non éditable)
- Rattrapage : pas de script dédié, appliqué au full rerun pipeline
- Référence : [correction.py:_correct_doc_type](../../domain/publications/correction.py) (cas 1)

### Règle SP-intrinsèque multi-critères avec whitelist

**`TITLE_ADDITIONAL_FILE_TO_DATASET`** — titre `'additional file…'` + `doc_type ∈ {article, other}` ⇒ `doc_type = dataset`.

- Inputs : `sp.title` (normalisé via `normalize_text`) + `sp.doc_type`
- Whitelist : `_ADDITIONAL_FILE_APPLIES_TO = {"article", "other"}` — `dataset` est laissé tel quel (déjà adéquat) ; les autres types (`thesis`, `book_chapter`, …) sont épargnés (titre suspect mais on ne corrige pas aveuglément).
- Audit ayant motivé la whitelist : sur 274 publications matchant le titre, 186 sont `article` (erreur, vraie correction), 46 sont `other` (sémantiquement moins informatif que `dataset`, gain marginal), 42 sont déjà `dataset` (correctes). 100 % DataCite ⇒ pas besoin de croiser avec le DOI-RA.
- Hook admin : non
- Rattrapage : [`oneshot/refresh_publications_with_additional_file_title.py`](../../interfaces/cli/oneshot/refresh_publications_with_additional_file_title.py)
- Référence : [correction.py:_correct_doc_type](../../domain/publications/correction.py) (cas 4)

### Règle journal-jointe + admin-éditable

**`JOURNAL_TYPE_MEDIA_TO_MEDIA`** — `journal.journal_type = 'media'` ⇒ `doc_type = media`.

- Input : `sp.journal_type` (joint depuis `journals` via la projection `SourcePublicationWithJournalView`)
- Whitelist : aucune (inconditionnel sur le signal journal)
- Hook admin : oui — `journal_type` est éditable par l'admin. Service [`requalify_publications_for_journal`](../../application/journals.py), endpoint `GET /api/journals/{id}/type-change-impact`, requalification synchrone dans le `PUT`, modale frontend.
- Rattrapage : [`maintenance/refresh_publications_for_journal_type.py --journal-type media`](../../interfaces/cli/maintenance/refresh_publications_for_journal_type.py)
- Référence : [correction.py:_correct_doc_type](../../domain/publications/correction.py) (cas 3) + commits `59db89d9` + `16b98985` + `49d22cd7`

## Anti-patterns

- **Muter `source_publications` à l'ingestion** (ex. dans le normalizer) : viole le principe d'inviolabilité, casse l'auditabilité. La correction doit toujours être une *dérivation* dans `correction.py`. Cf. [feedback `source_publications inviolable`](../../docs/chantiers/METIER_metadata-correction.md).
- **Encoder la règle en SQL pur (vue, trigger, UPDATE one-shot non auditté)** : perd la trace `meta.X_corrected_by` et la réversibilité.
- **Cascade implicite** : deux règles qui touchent le même champ sans ordre explicite ⇒ comportement non-déterministe. L'ordre des branches dans `_correct_<field>` est la convention.
- **Hook admin sans service** : déclencher `refresh_from_sources` directement depuis le router. Le service propriétaire (`application/<table>.py`) reste l'unique point d'écriture côté pubs (cf. [feedback `Propriété des services sur les tables`](../../docs/chantiers/METIER_metadata-correction.md)).

## Limites du périmètre

Les patterns *détectables mais non corrigibles automatiquement* (ex. DOI préfixe d'éditeur A sur revue d'éditeur B — peut être un preprint légitime, peut être un faux) ne relèvent pas de ce playbook : ils nécessitent une décision humaine. À traiter dans un chantier dédié de revue manuelle des incohérences.
