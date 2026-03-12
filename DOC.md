# Bibliométrie UCA — Documentation technique

## Présentation

Application d'analyse bibliométrique pour l'**Université Clermont Auvergne** (UCA). Elle collecte les publications scientifiques 2022-2026 depuis les APIs HAL, OpenAlex et Web of Science, les déduplique, résout les affiliations par structure (laboratoires, tutelles, partenaires), et fournit des tableaux de bord pour l'analyse par éditeur, revue, statut Open Access, et labo.

**Stack** : Python 3, PostgreSQL, FastAPI (backend), SvelteKit avec Svelte 5 (frontend).

---

## Arborescence du projet

```
publisher-stats/
├── analysis/                    # Scripts d'analyse ad hoc
├── config/
│   └── settings.py              # Connexions API, années, collections HAL, WoS
├── data/                        # Fichiers de données (exports RH, etc.)
├── db/
│   ├── connection.py            # get_connection() centralisé
│   ├── seed_structures.py       # Peuplement structures, relations, formes de noms
│   └── migrations/              # Migrations séquentielles (001 à 020+)
├── extraction/
│   ├── openalex/extract_openalex.py   # API OpenAlex → staging_openalex
│   ├── openalex/cross_import_openalex.py  # Import croisé : DOI HAL/WoS absents → OpenAlex
│   ├── hal/extract_hal.py             # API HAL → staging_hal
│   └── wos/
│       ├── extract_wos.py             # API WoS Expanded → staging_wos
│       └── scrape_wos.py              # Parsing fichiers WoS tab-delimited → staging_wos
├── processing/
│   ├── normalize_openalex.py    # staging → openalex_documents/authors/authorships
│   ├── normalize_hal.py         # staging → hal_documents/authors/authorships
│   ├── normalize_wos.py         # staging → wos_documents/authors/authorships
│   ├── fetch_missing_hal.py     # Récupère les HAL manquants découverts via OpenAlex
│   ├── populate_addresses.py    # Extrait les adresses depuis openalex_authorships
│   ├── resolve_addresses.py     # Résout adresses → structures (via name_forms)
│   ├── populate_uca_flags.sql   # Calcule is_uca et structure_ids
│   ├── populate_hal_struct_ids.py  # Extrait/matche les structures HAL
│   ├── enrich_hal_structures.py # Enrichit hal_structures depuis l'API ref/structure
│   ├── enrich_oa_unpaywall.py   # Enrichit le statut OA via Unpaywall
│   ├── create_persons_from_authorships.py  # Création automatique des personnes (5 passes)
│   ├── rebuild_authorships.py   # Reconstruit la table authorships (vérité) depuis les sources
│   └── merge_lab_duplicates.py  # Fusion interactive des homonymes par labo
├── frontend/                    # Application SvelteKit (Svelte 5)
│   └── src/routes/              # Pages : publications, persons, laboratories, admin, stats
├── webapp/
│   └── app.py                   # Serveur FastAPI (API + SPA statique)
└── requirements.txt
```

---

## Schéma de la base de données

### Architecture

Le schéma repose sur la **séparation stricte des sources**. Chaque source (HAL, OpenAlex, WoS) a ses propres tables pour les documents, auteurs et authorships. Les entités canoniques (tables de vérité) sont construites par déduplication et mapping, jamais par insertion directe depuis les sources.

Voir `ARCHITECTURE.md` pour les principes détaillés et `schema_target_v2.sql` pour le DDL complet.

### Types énumérés

| Enum | Valeurs |
|------|---------|
| `source_type` | `hal`, `openalex`, `wos` |
| `doc_type` | `article`, `conference_paper`, `book`, `book_chapter`, `thesis`, `preprint`, `review`, `editorial`, `report`, `other` |
| `oa_type` | `gold`, `hybrid`, `bronze`, `green`, `closed`, `unknown` |
| `structure_type` | `universite`, `onr`, `chu`, `ecole`, `labo`, `equipe`, `site`, `autre` |

### Tables de vérité

#### `structures` — Référentiel institutionnel
Toutes les structures : UCA, laboratoires, tutelles (CNRS, INRAE…), partenaires (CHU, INP, VetAgro Sup…).
- `code` : identifiant court stable (`uca`, `cnrs`, `lpc`, `ip`).
- `type` : `universite`, `onr`, `chu`, `ecole`, `labo`, `equipe`, `site`, `autre`.
- `ror_id`, `rnsr_id` : identifiants externes (optionnels).
- `hal_collection` : collection HAL associée (labos uniquement).

#### `structure_relations` — Hiérarchie, tutelles et partenariats
Relations entre structures.
- `relation_type` : `TEXT` libre. Valeurs utilisées :
  - `est_tutelle_de` : `parent_id` (UCA) est tutelle de `child_id` (labo). Définit le **périmètre restreint**.
  - `est_partenaire_de` : `parent_id` (CHU, INP…) est partenaire de `child_id` (UCA). Définit le **périmètre large** (avec le restreint).

#### `name_forms` — Formes de noms des structures
Formes textuelles utilisées pour détecter les structures dans les adresses d'affiliation.
- `form_text` / `form_normalized` : forme brute et normalisée.
- `is_regex` : si TRUE, `form_text` est une expression régulière.
- `requires_context_of` : JSONB, optionnel. Si présent, la forme ne matche que si une forme d'une des structures contextuelles est aussi détectée dans l'adresse (ex : la forme courte « IP » ne matche que si une tutelle comme « CNRS » est aussi présente).

#### `persons` — Référentiel des individus
Alimenté par les exports RH et par le script `create_persons_from_authorships.py` (création automatique depuis les authorships). Ne contient aucun identifiant bibliométrique directement.
- `last_name`, `first_name` : nom affiché.
- `last_name_normalized`, `first_name_normalized` : formes normalisées pour la déduplication.

#### `persons_rh` — Données RH (table satellite)
Données issues des exports RH, liées à `persons` via `person_id`.
- `structure_id` : rattachement institutionnel principal (FK → `structures`).
- `department_name`, `role_title` : informations administratives.
- `start_date`, `end_date` : période de rattachement.
- Cascade ON DELETE depuis `persons`.

#### `person_identifiers` — Identifiants certifiants
ORCID, idHAL, ResearcherID, etc. Chaque identifiant (`id_type` + `id_value`) pointe vers une seule personne (UNIQUE). Une personne peut avoir plusieurs identifiants.
- `source` : provenance (`hr`, `hal`, `openalex`, `manual`).

#### `publishers` / `journals` — Référentiel bibliographique
Non dupliqué par source — une seule entrée par éditeur/revue. Alignement par `openalex_id` ou ISSN-L.

#### `publications` — Publications unifiées
Table centrale. Chaque ligne = 1 publication unique, potentiellement issue de plusieurs sources.
- `doi` : pivot principal de dédoublonnage (contrainte UNIQUE).
- `title_normalized` : fallback pour les publications sans DOI.
- `oa_status` : statut OA résolu (peut venir d'OpenAlex, d'Unpaywall, ou de HAL).

#### `authorships` — Table de vérité personne × publication
Construite par `rebuild_authorships.py` depuis les authorships source. Relie personnes, publications et structures.
- `person_id` : peut être NULL si la personne n'est pas encore identifiée.
- `structure_ids INT[]` : structures du périmètre large (UCA + labos tutellés + partenaires).
- `is_uca` : TRUE si au moins une structure du périmètre restreint (UCA + labos tutellés).
- `hal_authorship_id`, `openalex_authorship_id`, `wos_authorship_id` : FK vers les authorships source (peuplés par `rebuild_authorships.py`).
- `author_position`, `is_corresponding` : propagés depuis les sources.
- `excluded` : lien erroné (homonyme, etc.).
- Contrainte d'unicité sur `(publication_id, person_id)`.

**Important** : `rebuild_authorships.py` crée les lignes (INSERT des paires `publication_id, person_id`) et peuple les FK/métadonnées. Les flags `is_uca` et `structure_ids` sont ensuite peuplés par `create_persons_from_authorships.py` (étape 4 de propagation) ou par `populate_uca_flags.sql` (étape 4).

### Tables source — HAL

#### `staging_hal`
Import brut de l'API HAL. `raw_data` (JSONB) contient la réponse API complète. `collection` est la collection d'origine de la requête. `processed` passe à TRUE après normalisation. Le staging n'est jamais modifié après import.

#### `hal_structures`
Référentiel des structures HAL, peuplé depuis l'API `ref/structure`.
- `hal_struct_id` : identifiant numérique HAL (UNIQUE, pas PK).
- `parent_ids` : hiérarchie (tableau d'entiers).
- `structure_id` (FK → `structures`) : mapping vers le référentiel.

#### `hal_authors`
Un enregistrement = un identifiant auteur dans HAL.
- `hal_person_id` : numérique HAL (UNIQUE mais nullable).
- `idhal`, `orcid` : données source observées.
- `person_id` : FK vers `persons` (NULL si non résolu ou non fiable).
- `is_reliable` : FALSE si cet identifiant recouvre plusieurs personnes réelles.

#### `hal_documents`
Un enregistrement = un document HAL.
- `halid` : identifiant HAL (UNIQUE).
- `collections TEXT[]` : collections HAL contenant ce document.
- `publication_id` : FK vers la publication canonique.

#### `hal_authorships`
Relation document × auteur dans HAL.
- `hal_struct_ids INT[]` : identifiants hal_struct_id affiliés (données brutes).
- `structure_ids INT[]` : structures UCA résolues (via `hal_structures.structure_id`).
- `is_uca` : TRUE si `structure_ids` contient au moins une structure du périmètre UCA.

### Tables source — OpenAlex

Architecture identique à HAL, adaptée aux spécificités d'OpenAlex.

#### `openalex_institutions`
Pendant de `hal_structures`. `ror_id` permet l'alignement automatique avec `structures.ror_id`.

#### `openalex_authors`
Un enregistrement = un auteur OpenAlex, identifié par `openalex_id` (UNIQUE). `is_reliable` important car OpenAlex fusionne parfois des homonymes.

#### `openalex_documents`
Même logique que `hal_documents`. Pas de champ `collections` (concept HAL).

#### `openalex_authorships`
- `raw_affiliation` : affiliation brute (source des adresses).
- `openalex_institution_ids TEXT[]` : institutions OpenAlex détectées.
- `structure_ids INT[]` / `is_uca` : résolution UCA (via les adresses et `address_structures`).

### Tables source — WoS

Architecture identique à HAL et OpenAlex, adaptée aux spécificités du Web of Science.

#### `wos_authors`
Un enregistrement = un auteur WoS, identifié par `wos_id` (ResearcherID, si disponible). `orcid` extrait des données brutes. `person_id` : FK vers `persons`.

#### `wos_documents`
Un enregistrement = un document WoS, identifié par `ut` (WoS UID, UNIQUE). `publication_id` : FK vers la publication canonique.

#### `wos_authorships`
Relation document × auteur dans WoS.
- `raw_affiliation` : affiliation brute.
- `structure_ids INT[]` / `is_uca` : résolution UCA (via les adresses et `address_structures`).
- `is_corresponding` : TRUE si auteur correspondant.

#### `wos_authorship_addresses`
Table de liaison authorship WoS ↔ adresse (même modèle que `openalex_authorship_addresses`).

### Adresses d'affiliation (source-agnostique)

#### `addresses`
Chaque adresse brute unique rencontrée. Le champ `review_status` est un vestige obsolète ; la source de vérité pour la validation est désormais `address_structures.is_confirmed`.

#### `address_structures`
Lien adresse → structure détectée, avec traçabilité.
- `matched_form_id` : IS NOT NULL = détection automatique (via `resolve_addresses.py`). IS NULL = assignation manuelle.
- `is_confirmed` (BOOLEAN, DEFAULT NULL) : statut de revue par structure. `TRUE` = lien confirmé, `FALSE` = lien rejeté, `NULL` = non examiné. Chaque lien adresse↔structure est confirmé/rejeté indépendamment.

#### `openalex_authorship_addresses`
Table de liaison authorship OpenAlex ↔ adresse. Chaque source qui fournit des adresses a sa propre table de liaison (WoS à créer quand disponible).

### Vue `publication_sources`
Vue (pas table) qui consolide les liens publication → source en combinant les FK `publication_id` de `hal_documents`, `openalex_documents` et `wos_documents`.

### Tables de staging
Zones de transit brutes. Chaque source a sa propre table.
- `staging_openalex` : clé unique `openalex_id`.
- `staging_hal` : clé unique `halid`, champ `collection`.
- `staging_wos` : clé unique `ut` (WoS UID), champs `doi` et `raw_data` (JSONB). Peuplé par l'API WoS Expanded (`extract_wos.py`) ou par parsing de fichiers tab-delimited téléchargés manuellement (`scrape_wos.py --parse-only`).
- `processed` : flag pour le traitement incrémental.

---

## Workflow complet

### Étape 0 — Données de référence

```bash
python3 db/seed_structures.py       # Peuple structures, relations, formes de noms
```

Peuple la table `structures` (UCA, labos, tutelles, partenaires), `structure_relations` (hiérarchie et tutelles), et `name_forms` (formes de noms pour la détection automatique). Idempotent.

### Étape 1 — Extraction

```bash
python3 extraction/openalex/extract_openalex.py    # API OpenAlex → staging_openalex
python3 extraction/hal/extract_hal.py              # API HAL → staging_hal
python3 extraction/wos/extract_wos.py              # API WoS → staging_wos (si API disponible)
python3 extraction/wos/scrape_wos.py --parse-only  # Ou : parsing de fichiers WoS téléchargés manuellement
```

**OpenAlex** : interroge l'API par année avec le filtre `authorships.institutions.lineage` sur l'ID UCA (`i198244214`). Résultats bruts en JSONB. ~20 000 works.

**HAL** : deux passes. D'abord par collection labo pour tagger chaque work avec sa/ses collection(s), puis via le portail global `clermont-univ` pour attraper les works qui ne sont dans aucune collection. ~22 000 works.

**WoS** : interroge l'API WoS Expanded par année avec le champ OG (Organization-Enhanced). Alternative : télécharger les fichiers Full Record tab-delimited depuis l'interface web WoS, puis les parser avec `scrape_wos.py --parse-only`.

Les scripts sont idempotents : les doublons (même `openalex_id`, `halid` ou `ut`) sont ignorés.

### Étape 2 — Normalisation

```bash
python3 processing/normalize_openalex.py    # ⬅ en premier
python3 processing/normalize_hal.py
python3 processing/normalize_wos.py
```

**Ordre important** : OpenAlex d'abord car ses métadonnées journal/éditeur sont plus structurées. HAL enrichit ensuite sans écraser les champs déjà corrects. WoS en dernier.

**normalize_openalex.py** produit :
- `publishers` / `journals` : éditeurs et revues (tables de vérité partagées).
- `publications` : dédoublonnage par DOI, puis titre normalisé + année.
- `openalex_documents` : un par work, lié à `publications` et `staging_openalex`.
- `openalex_authors` : un par auteur OpenAlex, dédupliqué par `openalex_id`.
- `openalex_institutions` : institutions extraites des authorships.
- `openalex_authorships` : un par document × auteur, avec `raw_affiliation` et `openalex_institution_ids[]`.

**normalize_hal.py** produit :
- `publishers` / `journals` / `publications` : enrichissement (DOI manquants, collections, doc_type, journal). HAL a priorité sur le doc_type et le journal quand la primary_location OpenAlex pointe vers HAL.
- `hal_documents` : un par halid, avec `collections[]` agrégées.
- `hal_authors` : un par `hal_person_id`, avec idhal extrait de `authFullNameIdHal_fs`.
- `hal_authorships` : un par document × auteur, avec `hal_struct_ids[]` bruts (pas encore résolus en `structure_ids`).

**Détection des primary_location HAL** : quand un work OpenAlex a sa primary_location pointant vers HAL, les métadonnées journal/éditeur d'OpenAlex sont ignorées (souvent fausses — ex : repository SPIRE affiché comme source).

**Exclusion des repositories** : les sources de type `repository` dans OpenAlex (SPIRE, Zenodo, arXiv…) ne génèrent pas d'entrées dans `journals` et `publishers`.

**Résolution des conflits (normalisation HAL)** :
- `journal_id` : HAL a priorité.
- `doc_type` : HAL a priorité (écrase le type OA souvent incorrect quand primary_location = HAL).
- `oa_status` : `unknown` ou `closed` peut passer à `green` si HAL a un fichier en texte intégral.

### Étape 2b — Récupération des HAL manquants (optionnel)

```bash
python3 processing/fetch_missing_hal.py --stats     # statistiques
python3 processing/fetch_missing_hal.py --dry-run   # lister sans télécharger
python3 processing/fetch_missing_hal.py              # télécharger et insérer en staging
python3 processing/normalize_hal.py                  # puis renormaliser
```

Certains works OpenAlex pointent vers un halId qui n'est pas dans notre staging (ni portail UCA, ni collection labo). Ce script les récupère via l'API HAL et les insère dans `staging_hal` avec `collection = NULL` (hors périmètre UCA).

### Étape 2c — Enrichissement structures HAL

```bash
python3 processing/populate_hal_struct_ids.py extract   # extrait les structures depuis le staging
python3 processing/enrich_hal_structures.py             # enrichit depuis l'API ref/structure
python3 processing/enrich_hal_structures.py --crawl     # remonte l'arbre des parents
python3 processing/populate_hal_struct_ids.py match      # matche hal_structures → structures
python3 processing/populate_hal_struct_ids.py apply      # écrit structure_id sur hal_structures
```

### Étape 3 — Adresses et affiliations

```bash
python3 processing/populate_addresses.py      # Extrait les adresses distinctes
python3 processing/resolve_addresses.py       # Résout adresses → structures
```

#### 3a. `populate_addresses.py`
- Parcourt les `raw_affiliation` de `openalex_authorships` et `wos_authorships`.
- Split les chaînes composites (séparateur ` | `).
- Déduplique par `raw_text` → table `addresses`.
- Crée les liens `openalex_authorship_addresses` et `wos_authorship_addresses`.
- Options : `--source openalex`, `--source wos`, ou les deux par défaut.

#### 3b. `resolve_addresses.py`
- Pour chaque adresse sans détection automatique, cherche les formes de noms actives dans `name_forms`.
- Si match → insère dans `address_structures` avec `matched_form_id` pour traçabilité.
- Les formes ayant un `requires_context_of` ne matchent que si une forme d'une structure contexte (typiquement une tutelle) est aussi détectée dans l'adresse.
- Options : `--reset` (supprime les affiliations auto), `--rerun` (reset + relance complète), `--stats`.

### Étape 3c — Calcul des flags UCA (authorships source)

```bash
psql -d publisher_stats -f db/populate_uca_flags.sql
```

Calcule `is_uca` et `structure_ids` sur les **authorships source** (HAL, OpenAlex, WoS). Utilise deux périmètres :

- **Périmètre restreint** (→ `is_uca`) : UCA + labos tutellés (relation `est_tutelle_de`).
- **Périmètre large** (→ `structure_ids`) : restreint + partenaires CHU, INP, VetAgro Sup… (relation `est_partenaire_de`).

Détail des étapes :
1. **HAL mapping** : mappe `hal_authorships.hal_struct_ids[]` → `structure_ids[]` via `hal_structures.structure_id`.
2. **HAL is_uca** : flag les authorships ayant au moins une structure du périmètre restreint.
3. **OpenAlex** : calcule `is_uca` (périmètre restreint) et `structure_ids` (périmètre large) via `openalex_authorship_addresses` → `address_structures`.
3b. **WoS** : idem via `wos_authorship_addresses` → `address_structures`.
4. **Propagation vers authorships (vérité)** : propage depuis les 3 sources par matching `(publication_id, person_id)`, en fusionnant les `structure_ids`. **Requiert que les `person_id` soient déjà résolus** (étape 3d).

> **Note** : l'étape 4 est aussi exécutée par `create_persons_from_authorships.py` et par `rebuild_authorships.py` n'exécute pas cette étape. Voir « Pipeline complet » ci-dessous.

### Étape 3d — Création des personnes

```bash
python3 processing/create_persons_from_authorships.py   # Création automatique (5 passes + propagation)
python3 processing/merge_lab_duplicates.py               # Fusion des homonymes par labo
```

Le script `create_persons_from_authorships.py` crée les entrées `persons` depuis les authorships UCA non encore rattachés, en 5 passes :
1. Regroupement par ORCID
1b. Rattachement aux personnes existantes par nom strict + co-publication
2. Regroupement par nom strict + co-publication entre auteurs restants
3. Singletons (authorship UCA isolée → une personne)
3b. Cross-link — rattache les auteurs non-UCA homonymes sur les mêmes publications

Puis **étape 4** : propage `is_uca` et `structure_ids` vers la table `authorships` (même logique que `populate_uca_flags.sql` étape 4).

Le script `merge_lab_duplicates.py` détecte et fusionne interactivement les doublons (homonymes et interversions nom/prénom) au sein de chaque laboratoire.

### Étape 3e — Reconstruction de la table authorships

```bash
python3 processing/rebuild_authorships.py```

Reconstruit la table de vérité `authorships` :
1. **INSERT** des paires `(publication_id, person_id)` manquantes depuis les 3 sources.
2. **FK** : peuple `hal_authorship_id`, `openalex_authorship_id`, `wos_authorship_id`.
3. **author_position** : prend la première valeur non-null (HAL > OpenAlex > WoS).
4. **is_corresponding** : depuis WoS.

**Ne propage pas `is_uca` ni `structure_ids`**. Après un rebuild, relancer `populate_uca_flags.sql` ou `create_persons_from_authorships.py` pour recalculer les flags.

### Pipeline complet (récapitulatif)

L'ordre des opérations est crucial. Le pipeline complet depuis zéro :

```
1.  seed_structures.py               # Référentiel structures
2.  extract_*.py                      # Extraction des 3 sources
3.  normalize_openalex.py             # Normalisation OpenAlex (en premier)
4.  normalize_hal.py                  # Normalisation HAL
5.  normalize_wos.py                  # Normalisation WoS
6.  fetch_missing_hal.py              # HAL manquants via OpenAlex (optionnel)
7.  cross_import_openalex.py          # DOI HAL/WoS absents → OpenAlex + normalize_openalex
8.  cross_import_hal.py               # DOI OA/WoS absents → HAL + normalize_hal
9.  populate_hal_struct_ids.py        # Structures HAL
10. enrich_hal_structures.py          # Enrichissement structures HAL
11. populate_addresses.py             # Extraction adresses (OpenAlex + WoS)
12. resolve_addresses.py              # Résolution adresses → structures
13. populate_uca_flags.sql            # Flags UCA sur authorships source (étapes 1-3b)
14. create_persons_from_authorships.py  # Personnes + propagation (étape 4)
15. rebuild_authorships.py    # INSERT authorships manquants + FK
16. populate_uca_flags.sql            # Re-propagation étape 4 (les nouveaux authorships)
17. enrich_oa_unpaywall.py            # Statut OA via Unpaywall (écrase sauf diamond)
```

> **Problème connu** : les étapes 14 et 16 font toutes les deux la propagation étape 4, mais sur des ensembles différents. L'étape 14 propage uniquement les authorships qui existaient déjà. L'étape 15 crée de nouveaux authorships (notamment pour les publications WoS-only). L'étape 16 repropage pour couvrir ces nouveaux authorships. **Ce pipeline est à simplifier** — idéalement, `rebuild_authorships.py` devrait intégrer la propagation `is_uca`.

### Étape 4 — Enrichissement OA (optionnel)

```bash
python3 processing/enrich_oa_unpaywall.py    # Résout les statuts OA inconnus via Unpaywall
```

Pour les publications ayant un DOI, interroge l'API Unpaywall (gratuite, ~8 req/s). Écrase `publications.oa_status` avec la valeur Unpaywall, **sauf** : ne remplace jamais `diamond` par `gold` (Unpaywall ne connaît pas le diamond OA).

### Étape 5 — Revue manuelle

Via l'interface web. L'opératrice examine les liens adresse→structure :
- Filtre par statut (`is_confirmed` : à examiner / confirmé / rejeté).
- Filtre par structure, par texte (contient / ne contient pas).
- Confirme ou rejette chaque lien adresse↔structure indépendamment (`is_confirmed = TRUE/FALSE/NULL`).
- Actions en lot possibles (sélection multiple + action batch).
- Assignation manuelle de structures à une adresse (page feedback).

La propagation vers `openalex_authorships.is_uca` et `authorships.is_uca` est **partiellement automatique** : chaque action de review déclenche un recalcul temps réel des flags UCA pour les authorships **OpenAlex** affectés (via `propagate_uca_for_addresses()`). Les authorships **HAL** ne sont pas recalculés en temps réel — voir la section "Points d'attention".

---

## Interface web (SvelteKit)

Le frontend est une SPA SvelteKit (Svelte 5 avec runes) servie en statique par FastAPI.

### Pages publiques

| URL | Description |
|-----|-------------|
| `/stats` | Dashboard statistiques — navigation éditeurs → revues → labos, graphiques OA par année |
| `/publications` | Liste des publications — filtres à facettes dynamiques (année, labo, source, type, voie OA, éditeur, revue) |
| `/publications/{id}` | Détail d'une publication — métadonnées, sources, auteurs (table de vérité + sources HAL/OpenAlex) |
| `/persons` | Annuaire des personnes — stats de liaison, filtres |
| `/persons/{id}` | Détail d'une personne — publications avec filtres à facettes, identifiants, auteurs liés |
| `/laboratories` | Liste des laboratoires avec statistiques |
| `/laboratories/{id}` | Détail d'un laboratoire — publications, personnes, statistiques OA |

### Pages admin (authentification requise)

| URL | Description |
|-----|-------------|
| `/admin/persons` | Gestion des personnes — liaison auteurs, fusion, identifiants |
| `/admin/authorships` | Signatures — auteurs source avec détail des authorships et résolution |
| `/admin/addresses` | Revue des adresses — validation manuelle UCA / non-UCA |
| `/admin/feedback` | Boucle de rétroaction — faux positifs/négatifs de la détection de formes |
| `/admin/structures` | Gestion des structures et formes de noms |

### API endpoints principaux

| Endpoint | Description |
|----------|-------------|
| `GET /api/addresses` | Liste paginée des adresses (filtres: status, search, search_mode, lab_id, uca_filter) |
| `POST /api/addresses/{id}/review` | Confirmer/rejeter un lien adresse↔structure (`is_confirmed`) — propage is_uca OpenAlex en temps réel |
| `POST /api/addresses/batch-review` | Action batch sur plusieurs adresses — propage is_uca OpenAlex en temps réel |
| `POST /api/addresses/{id}/assign-structure` | Assignation manuelle d'une structure — propage is_uca |
| `DELETE /api/addresses/{id}/assign-structure` | Supprime une assignation manuelle — propage is_uca |
| `GET /api/addresses/{id}/publications` | Publications liées à une adresse |
| `GET /api/publications` | Liste paginée (filtres: search, year, lab_id, publisher_id, journal_id, oa_status, source_filter, doc_type, sort) |
| `GET /api/pub-stats/publishers` | Stats par éditeur avec ventilation OA |
| `GET /api/pub-stats/journals` | Stats par revue avec ventilation OA |
| `GET /api/pub-stats/by-year` | Publications par année avec ventilation OA |
| `GET /api/pub-stats/summary` | Résumé global |
| `GET /api/pub-stats/labs` | Stats par laboratoire avec ventilation OA |
| `GET /api/persons` | Liste des personnes avec stats de liaison |
| `GET /api/persons/{id}/candidates` | Auteurs candidats pour liaison |
| `POST /api/persons/{id}/link` | Lier un auteur source à une personne |
| `DELETE /api/persons/{id}/link/{source}/{author_id}` | Délier un auteur |
| `GET /api/authorships` | Signatures (auteurs HAL + OpenAlex unifiés) |
| `GET /api/authors/{source}/{id}/details` | Détail d'un auteur source (authorships, structures) |
| `GET /api/laboratories` | Liste des labos (structures de type labo) |
| `GET /api/feedback/stats` | Statistiques de qualité de la détection automatique |
| `POST /api/feedback/rerun` | Relance resolve_addresses --rerun |

### Serveur

```bash
# Développement
python3 webapp/app.py                              # http://localhost:8003
cd frontend && npm run build                       # build SvelteKit → frontend/build/

# Production
pm2 start "uvicorn webapp.app:app --host 0.0.0.0 --port 8003" --name publisher-stats-api
pm2 restart publisher-stats-api
```

---

## Configuration

### `config/settings.py`

- `DB` : connexion PostgreSQL (dbname, user, host, port).
- `OPENALEX` : email (polite pool), institution_id, années, débit.
- `HAL` : portail global, collections par labo, années, débit.

---

## Chiffres clés (base complète)

| Indicateur | Volume |
|------------|--------|
| Publications staging OpenAlex | ~20 500 |
| Publications staging HAL | ~22 000 |
| Publications staging WoS | ~16 000 |
| Publications unifiées | ~35 000 |
| Publications WoS-only (hors HAL et OA) | ~2 300 |
| Adresses distinctes | ~30 000 |
| Structures | ~150 (labos UCA + tutelles + partenaires) |

---

## Maintenance

### Backup quotidien

Script cron : `~/scripts/pg_backup.sh` (planifié à 12h30).
Garde les 10 derniers dumps par base, rotation par nombre.

```bash
# Restauration
gunzip -c ~/backups/pg/publisher_stats_YYYY-MM-DD_HHMM.sql.gz | psql publisher_stats
```

### Ajout d'une nouvelle année

1. Ajouter l'année dans `settings.py` (OPENALEX.years, HAL.years et WOS.years).
2. Relancer les extractions (3 sources).
3. Relancer la normalisation (traitement incrémental via `processed = FALSE`).
4. Relancer le pipeline complet : populate_addresses → resolve_addresses → populate_uca_flags → create_persons → rebuild_authorships → populate_uca_flags.

### Ajout d'un nouveau labo

1. Ajouter l'entrée dans `seed_structures.py` (structure, relations, formes de noms).
2. Ajouter la collection HAL dans `settings.py`.
3. `python3 db/seed_structures.py` (idempotent).
4. Relancer `resolve_addresses.py --rerun` + `populate_uca_flags.sql`.

---

## Points d'attention

### Propagation `is_uca` : temps réel vs batch

La propagation du flag `is_uca` sur les authorships fonctionne différemment selon la source :

| Source | Mécanisme | Déclencheur |
|--------|-----------|-------------|
| **OpenAlex** | Temps réel (`propagate_uca_for_addresses()` dans `app.py`) | Chaque review, batch-review, assign-structure, delete-structure |
| **WoS** | Temps réel (même mécanisme) | Idem |
| **HAL** | Batch uniquement (`populate_uca_flags.sql`) | Exécution manuelle |
| **Authorships (vérité)** | Batch uniquement (`populate_uca_flags.sql` étape 4, ou `create_persons_from_authorships.py` étape 4) | Exécution manuelle |

**Conséquence** : après une session de review d'adresses, les compteurs de la page Authorships reflètent immédiatement les changements OpenAlex/WoS, mais les authorships HAL restent inchangés jusqu'au prochain `psql -d publisher_stats -f db/populate_uca_flags.sql`. La table de vérité `authorships` n'est mise à jour que par le batch.

### Modification du périmètre UCA

Deux périmètres coexistent :
- **Périmètre restreint** (→ `is_uca`) : UCA + structures liées par `est_tutelle_de` (labos UCA).
- **Périmètre large** (→ `structure_ids`) : restreint + partenaires liés par `est_partenaire_de` (CHU, INP, VetAgro Sup…). La relation `est_partenaire_de` a UCA en `child_id` et le partenaire en `parent_id`.

Si le périmètre change (ajout ou retrait d'un laboratoire, d'une tutelle, d'un partenaire) :

1. **Relancer** `psql -d publisher_stats -f db/populate_uca_flags.sql` — recalcule `is_uca` pour HAL, OpenAlex, WoS et authorships.
2. **Relancer** `resolve_addresses.py --rerun` si de nouvelles formes de noms ont été ajoutées.
3. Les reviews existantes (`address_structures.is_confirmed`) ne sont **pas** invalidées automatiquement — un lien confirmé pour une structure retirée du périmètre reste confirmé dans la table, mais ne contribue plus au calcul `is_uca`.

### `addresses.review_status` — champ obsolète

Le champ `addresses.review_status` (valeurs : `'pending'`, `'valid'`, `'false_positive'`) est un vestige de la v1. **Aucun code ne le lit ni ne l'écrit**. La source de vérité est `address_structures.is_confirmed` (par structure). La colonne peut être supprimée sans impact :

```sql
ALTER TABLE addresses DROP COLUMN review_status;
```

### `resolve_addresses.py` — comportement de l'ON CONFLICT

Quand `resolve_addresses.py` détecte un lien adresse→structure qui existe déjà dans `address_structures`, la clause ON CONFLICT **ne fait rien** si le lien a été confirmé (`is_confirmed IS NOT NULL`) ou s'il a déjà un `matched_form_id`. Cela empêche l'auto-détection d'écraser une décision manuelle. En revanche, un lien non examiné sans détection automatique sera mis à jour avec le `matched_form_id` trouvé.

### Authorships HAL sans identifiant fiable

Certains `hal_authors` ont `is_reliable = FALSE` (un même identifiant HAL couvre plusieurs personnes réelles — cas d'homonymes non désambiguïsés côté HAL). Ces auteurs ne sont **pas** liés automatiquement à une personne. Ils apparaissent dans la page Authorships mais sans `person_id`, et leur résolution nécessite une intervention manuelle via la page Personnes.

### Truncation des authorships OpenAlex

L'API OpenAlex tronque la liste des auteurs à 100 par publication. Les mega-papers (>100 auteurs) ont donc une liste incomplète. Les authorships manquants ne sont ni dans `openalex_authorships` ni dans `authorships`. Un re-fetch individuel de ces publications est prévu (voir TODO §2).

### Publications HAL sans publication canonique

Certaines `hal_documents` ont `publication_id IS NULL` malgré un DOI présent. Cela peut arriver si le DOI n'a pas été trouvé dans `publications` au moment de la normalisation (ordre de traitement, DOI mal formaté, etc.). Ces publications HAL existent dans la base mais ne sont pas visibles dans les pages qui requêtent `publications`. Voir TODO §3.

---

## Axes de développement

### Axe 1 — Import croisé entre sources

Des DOI présents dans une source peuvent être absents d'une autre. Le script `cross_import_openalex.py` interroge l'API OpenAlex pour les DOI HAL/WoS absents du staging OpenAlex :

```bash
python3 extraction/openalex/cross_import_openalex.py --dry-run    # compter
python3 extraction/openalex/cross_import_openalex.py               # importer
python3 processing/normalize_openalex.py                            # puis normaliser
```

Ordres de grandeur : ~3 000 DOI HAL-only, ~2 200 DOI WoS-only absents d'OpenAlex.

Un script équivalent pour HAL (import croisé vers HAL) est envisagé. L'import croisé vers WoS n'est pas possible (API non disponible en écriture).

### Axe 2 — Enrichissement du référentiel personnes

- Lien avec le référentiel IdRef (ABES) pour les auteurs de thèses et HDR.
- Détection de doublons améliorée.

### Autres évolutions envisagées

- **Estimation APC** : croisement avec les données OpenAPC et DPCG.
- **Contrôle des signatures institutionnelles** : vérification de conformité (présence des tutelles requises, formes normalisées) avec reporting par labo.
- **Fusion de publications** : déduplication manuelle des publications sans DOI commun.
- **Filtre auteur correspondant UCA** : sur les pages Publications, Laboratoire et Statistiques.

---

## TODO

1. Publis HAL > 2000 auteurs : `python3 processing/normalize_hal.py --max-authors 5000` (mega-papers actuellement skippés).
2. Re-fetch publis OpenAlex avec exactement 100 authorships (truncation API) : re-fetch individuellement pour obtenir la liste complète.
3. Vérifier publis HAL avec DOI non reliées à une publication :
```sql
SELECT hd.halid, hd.doi, hd.title, hd.pub_year
FROM hal_documents hd
WHERE hd.publication_id IS NULL
  AND hd.doi IS NOT NULL
ORDER BY hd.pub_year DESC;
```
4. Mettre de l'ordre dans le dossier processing (scripts obsolètes à supprimer).
5. **Simplifier le pipeline** : `rebuild_authorships.py` devrait intégrer la propagation `is_uca`/`structure_ids` pour éviter de devoir relancer `populate_uca_flags.sql` deux fois. Idéalement un seul script « reconstruit tout » après la création des personnes.
6. Import croisé HAL : script similaire à `cross_import_openalex.py` pour récupérer sur HAL les DOI OpenAlex/WoS absents.
