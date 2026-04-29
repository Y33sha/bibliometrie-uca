# Chantier — Sujets / mots-clés
Commencé le 2026-04-29

## Contexte

Les `keywords` (TEXT[]) et `topics` (JSONB) sont déjà extraits par tous les normalisateurs et stockés dans `source_publications`, mais :

- aucune table dédiée ne les structure ;
- l'API ne les expose pas (`SourcePublicationOut` les ignore, [detail.py](../../infrastructure/db/queries/publications/detail.py) ne les SELECT pas) ;
- le frontend ne les affiche nulle part ;
- aucune déduplication ni mise en relation inter-sources.

Objectif à terme : exploitation analytique — nuages de sujets par personne/structure, affichage des sujets sur la page publication, recherche par sujet via le champ de recherche existant.

## Hétérogénéité des sources (rappel de l'audit)

| Source     | Mots-clés libres                  | Termes contrôlés / hiérarchie                                | Langue dominante |
|------------|-----------------------------------|--------------------------------------------------------------|------------------|
| HAL        | `keyword_s` (texte libre)         | `domain_s` (domaines HAL, hiérarchie aplatie)                | FR/EN mêlés      |
| OpenAlex   | `keywords[]` (avec score)         | `topics` 5 niveaux : domain → field → subfield → topic       | EN               |
| WoS        | `keywords` (API)                  | `subjects` + `headings` (catégories WoS)                     | EN               |
| CrossRef   | `subject[]` (très générique)      | aucun (extraction `topics` non implémentée)                  | EN               |
| Theses.fr  | `sujets[].libelle`                | `discipline` + `sujetsRameau` (ontologie RAMEAU)             | FR               |
| ScanR      | dict multilingue (default/en/fr)  | `domains` ou `topics` (structure libre)                      | multi            |

## Décisions de modélisation (validées)

- **Q1** — Table unique `subjects` avec discriminant `kind ∈ {'free','concept'}`. On bascule vers deux tables séparées si l'usage révèle des frictions.
- **Q2** — Pas d'ontologie pivot. On garde chaque ontologie côte à côte ; on bascule vers OpenAlex comme pivot si un gain analytique clair apparaît.
- **Q3** — Cible : exploitation analytique (sujets par publi, nuages personne/structure, recherche par sujet).
- **Q4** — Pas de seuil de score à l'ingestion. On seuillera à l'usage si trop de bruit.

## Schéma cible

### Table `subjects`

Référentiel des sujets observés (libres ou conceptuels), tous types et toutes ontologies confondus.

```
id            SERIAL PK
kind          TEXT NOT NULL CHECK (kind IN ('free','concept'))
label         TEXT NOT NULL
language      TEXT NULL              -- ISO 639-1, NULL si non identifiable
ontology      TEXT NULL              -- NULL pour kind='free'
                                     -- 'openalex_topic' | 'openalex_keyword' (OA "keywords" sont semi-contrôlés)
                                     -- 'hal_domain' | 'wos_subject' | 'wos_heading'
                                     -- 'rameau' | 'theses_discipline' | 'scanr_domain'
ontology_id   TEXT NULL              -- identifiant stable dans l'ontologie (URI OpenAlex, code RAMEAU…)
parent_id     INT NULL REFS subjects -- hiérarchie interne (OpenAlex domain→field→subfield→topic, hal_domain)
level         INT NULL               -- profondeur dans la hiérarchie

UNIQUE (ontology, ontology_id) WHERE kind = 'concept'
UNIQUE (kind, lower(label), language) WHERE kind = 'free'
```

Notes :
- La déduplication des libres est faite sur `lower(label)` + langue ; on garde la casse originale du premier insert. Stratégie de déduplication plus fine (lemmatisation, accents) à arbitrer si bruit observé.
- Les concepts d'une même ontologie sont uniques par `(ontology, ontology_id)`. Pas de tentative de mapping inter-ontologies à ce stade.

### Table `publication_subjects`

Lien `publications` ↔ `subjects`, traçant la source d'origine de l'annotation.

```
publication_id  INT REFS publications ON DELETE CASCADE
subject_id      INT REFS subjects ON DELETE CASCADE
source          TEXT NOT NULL          -- 'hal' | 'openalex' | 'wos' | 'crossref' | 'theses' | 'scanr'
score           REAL NULL              -- score de pertinence si fourni par la source

PRIMARY KEY (publication_id, subject_id, source)
INDEX (subject_id)                     -- nuages : "publis par sujet"
INDEX (publication_id)                 -- détail publi : "sujets d'une publi"
```

La même publication peut être annotée par plusieurs sources avec le même sujet ; on garde une ligne par source pour préserver la traçabilité. L'agrégat (côté API) déduplique par `subject_id`.

## Phases

### Phase 1 — Modélisation et migration

- [x] Migration `014_subjects.sql` : tables `subjects` + `publication_subjects`, index uniques partiels, CHECK de cohérence kind/ontology.
- [x] Domain `domain/subject.py` : `SubjectKind` (Literal), constantes `ONTOLOGY_*`, helper `normalize_free_label`.
- [x] Queries SQL `infrastructure/db/queries/subjects.py` : `upsert_free_subject`, `upsert_concept_subject`, `link_publication_subject`, `clear_publication_subjects` (idempotence par source).
- [x] Tests unitaires `tests/unit/domain/test_subject.py` (8 tests) + tests d'intégration `tests/integration/infrastructure/db/queries/test_subjects.py` (12 tests).

### Phase 2 — Pipeline d'ingestion

Nouvelle phase `application/pipeline/subjects/` qui lit `source_publications.keywords` et `source_publications.topics` (déjà persistés, pas besoin de re-extraire) et alimente `subjects` + `publication_subjects`.

- [x] `subjects/ingest_hal.py` : `keywords` → libre `language=None` (HAL mêle FR/EN) ; `topics.hal_domains` → concept `hal_domain` (code = ontology_id).
- [x] `subjects/ingest_openalex.py` : `keywords` → libre `en` (l'extraction normalize_openalex perd le score actuellement) ; `topics` → 4 niveaux `openalex_topic` chaînés via `parent_id`, score uniquement sur le niveau le plus profond observé.
- [x] `subjects/ingest_wos.py` : `keywords` → libre EN ; `topics.subjects` → concept `wos_subject` ; `topics.headings` → concept `wos_heading`.
- [x] `subjects/ingest_crossref.py` : `keywords` → libre EN.
- [x] `subjects/ingest_theses.py` : `keywords` → libre FR ; `topics.discipline` → concept `theses_discipline` ; `topics.rameau` → concept `rameau`.
- [x] `subjects/ingest_scanr.py` : `keywords` → libre `language=None` (mélange perdu à la normalisation) ; `topics`/`domains` → concept `scanr_domain`.
- [x] Orchestrateur `subjects/run.py` + branchement dans `run_pipeline.py` (`--only subjects`, `--from subjects`, après `countries`).
- [x] Idempotence : `DELETE FROM publication_subjects WHERE source = X` au début de chaque source, puis ré-ingestion complète. Plus simple et robuste qu'un clear par publication.
- [x] Tests d'intégration `tests/integration/pipeline/test_subjects_ingest.py` (15 tests : ingestion par source, dédup, hiérarchie OA, score sur feuille, idempotence run, filtre par source, ignore source_pub orphelines).
- [x] Optimisations perf : `SubjectCache` partagé par source (évite les UPSERTs récurrents), `link_publication_subjects_bulk` via `executemany` (un round-trip pour les liens d'une publication), logs de progression toutes les 1000 publications. Pipeline complet 6 sources en ~125s.

Compromis pour la résolution de `ontology_id` :
- HAL : code stable (ex `info.eea`).
- OpenAlex : `lower(display_name)` faute d'ID extrait par normalize_openalex (à revoir si on étend la normalisation).
- WoS / Theses (rameau, discipline) / ScanR : `lower(label)` faute d'ID exposé par la source.

### Phase 3 — Combler CrossRef topics

L'audit a révélé que `topics` n'est pas extrait pour CrossRef. Vérifier si CrossRef expose des champs ontologiques exploitables (au-delà de `subject[]`) ; sinon documenter et clore.

- [ ] Audit ciblé du payload CrossRef.
- [ ] Si un champ existe : étendre `normalize_crossref.py` puis l'ajouter à `ingest_crossref.py`.

### Phase 4 — Exposition API + page publication

- [ ] Étendre la requête `detail.py` pour récupérer les sujets agrégés (déduplication par `subject_id`, agrégation des sources).
- [ ] Modèle `SubjectOut` dans [models.py](../../interfaces/api/models.py) ; ajouter `subjects: list[SubjectOut]` à `PublicationDetailResponse`.
- [ ] Page publication SvelteKit : section "Sujets", badges groupés par `kind` puis par `ontology`, label de la source au survol.

### Phase 5 — Agrégats personne et structure

Endpoints et UI pour les nuages de sujets.

- [ ] Endpoint `GET /api/persons/{id}/subjects?limit=N` : top sujets de la personne, agrégats par fréquence (et score moyen si disponible) sur ses authorships → publis → subjects.
- [ ] Endpoint `GET /api/structures/{id}/subjects?limit=N&perimeter=…` : idem, en respectant le périmètre UCA dual (restricted/wide).
- [ ] Composant frontend `SubjectsCloud.svelte` (badges pondérés ou nuage, à arbitrer avec Laura sur le rendu).
- [ ] Intégration dans pages personne et structure.

### Phase 6 — Recherche par sujet

- [ ] Étendre la recherche publications côté backend : le champ texte fouille aussi dans `subjects.label`.
- [ ] Index trigram sur `subjects.label` si la perf l'exige (à mesurer).
- [ ] Aucune nouvelle UI : la recherche existante absorbe les sujets transparente.

### Phase 7 — Tests de non-régression

À chaque phase, ajouter les tests pertinents (pattern `feedback_regression_tests`). En particulier :

- [ ] Tests d'ingestion par source (échantillons fixtures pour chaque source).
- [ ] Test d'idempotence : ingérer deux fois la même publi ne duplique pas les liens.
- [ ] Test API : la page publication renvoie des sujets dédupliqués.
- [ ] Test agrégat personne/structure : pondération correcte, périmètre UCA respecté.

## Risques et points ouverts

- **Volume** : la table `subjects` peut grossir vite côté libres (longue traîne, fautes, casse). À mesurer après Phase 2 sur le dataset complet.
- **Bruit des libres** : keywords mal accentués, variantes singulier/pluriel, langues mêlées. Pas de normalisation poussée en première approche ; déclencher si l'UX est dégradée.
- **Bruit OpenAlex topics bas niveau** : on ingère sans seuil ; à seuiller (Phase 5 ?) si les nuages deviennent illisibles.
- **Hiérarchie OpenAlex** : on stocke `parent_id` et `level`, mais on ne s'en sert pas tout de suite. À exposer en Phase 5 si pertinent (filtrer par niveau, regrouper).
- **CrossRef topics** : décision Phase 3 selon ce que l'API expose vraiment.
- **Recherche** : la fouille `LIKE/ILIKE` sur `subjects.label` peut être lente sans index. Trigram envisagé en Phase 6.
- **Migrer rétroactivement** : Phase 2 doit pouvoir tourner sur tout l'historique `source_publications` existant, pas seulement sur les nouvelles publis. Vérifier que le pipeline accepte ce mode.
- **Curation manuelle** : la phase d'ingestion fait `DELETE` total par source puis ré-INSERT. Toute édition manuelle des `subjects` ou `publication_subjects` serait écrasée au prochain run. À adresser avant d'introduire des outils de curation côté UI (séparation source/auto vs corrections, ou colonne `manually_edited` qui exclut du DELETE).

## Ordre d'attaque proposé

1. Phase 1 (modélisation + migration) — bloquant.
2. Phase 2 (ingestion pipeline) — débloque le reste.
3. Phase 4 (API + page publi) — premier livrable visible.
4. Phase 5 (nuages personne/structure) — gros gain UX.
5. Phase 6 (recherche) — petit gain, peu coûteux.
6. Phase 3 (CrossRef topics) — opportuniste, à caser quand le reste est stable.
7. Phase 7 — en parallèle de chaque phase, pas en bloc final.
