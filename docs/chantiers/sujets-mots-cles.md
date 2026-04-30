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

### Phase 3 — Combler CrossRef topics — clos sans suite (2026-04-30)

Audit réalisé sur 100 DOIs aléatoires CrossRef-sourcés via `interfaces/cli/audit_crossref_topics.py` (one-shot, conservé pour ré-audit éventuel) :

- `subject` est présent 100/100 fois mais **toujours vide** (`[]`). CrossRef a désactivé ce champ pour raisons de qualité et conserve la clé pour compatibilité.
- Aucun autre champ ontologique dans le payload : pas de `topic`/`topics`, `keyword`/`keywords`, `concept`, `categories`, `discipline`, `tag`, `subject-category`, `scheme`. L'inventaire des clés top-level est limité aux métadonnées de publication (titre, auteurs, références, dates, ISSN, journal, funders…).

Conclusion : rien à extraire au-delà de ce que tente déjà `normalize_crossref.py` (qui produit du vide). On garde l'extraction `subject` pour redémarrage automatique si CrossRef réactive la donnée, et on conserve le script d'audit pour ré-évaluation périodique.

- [x] Audit ciblé du payload CrossRef → champ vide / pas d'alternative.
- [x] Décision : pas d'extension de `normalize_crossref.py` ni d'`ingest_crossref.py`.

### Phase 4 — Exposition API + page publication

- [x] Étendre `detail.py` : `get_publication_subjects` (GROUP BY subject, agrège les sources). 4 tests intégration.
- [x] Modèle `SubjectOut` dans [models.py](../../interfaces/api/models.py) ; ajout `subjects: list[SubjectOut]` à `PublicationDetailResponse`.
- [x] Composant `SubjectsBlock.svelte` : 3 niveaux plats sans sous-titres (général en chips gris, précis en cartouche bleu, libres en cartouche jaune), tooltip = source(s).
- [x] Référentiel `domain/hal_domains.py` (393 entrées générées via `interfaces/cli/refresh_hal_domain_labels.py` depuis l'API CCSD) + helpers `hal_domain_label`, `hal_domain_path`. `ingest_hal` strippe le préfixe `<level>.` Solr (`0.phys` → `phys`) et utilise le label CCSD.
- [x] Libres : `language=None` partout (au lieu de 'en'/'fr'/None selon source) pour permettre la déduplication inter-sources sur `lower(label)` seul.

### Phase 5 — Page sujets + co-occurrences

- [x] **5a Backend** : migration `015_subject_cooccurrences.sql` (colonne `subjects.usage_count`, table `subject_cooccurrences (a, b, count)` avec PK `(a, b)` et CHECK `a < b`). Phase pipeline `cooccurrences` (entre `subjects` et `enrich`) qui recalcule `usage_count` puis TRUNCATE+INSERT `subject_cooccurrences` avec seuil `count >= 2` par défaut. Routes API `GET /api/subjects` (liste paginée + recherche), `GET /api/subjects/{id}` (détail + voisins). Pipeline complet 6 sources + cooccurrences en ~18s.
- [x] **5b Page liste** : route `/subjects` SvelteKit, recherche debounced 300ms, filtre `min_count` (défaut 3), pagination 50/page, badge ontologies. Lien "Sujets" dans la nav.
- [x] **5d Refonte schéma** : un sujet = un libellé canonique (clé d'unicité = `lower(label)`). Migrations `016` puis `017` :
    - `kind`, `ontology`, `ontology_id` retirés au profit d'un JSONB `ontologies` agrégeant les annotations multi-sources : `{"openalex_topic": {"codes": [...], "level": int|null, "parent": str|null}, "hal_domain": {"codes": [...]}, ...}`.
    - `level` et `parent_id` retirés du top-level (ontology-dépendants) : absorbés dans le JSONB par ontologie. `parent` est désormais un libellé string (pas un FK Postgres).
    - Un libre = `ontologies = {}`.
    - `upsert_subject` fait merge JSONB enrichi : union des `codes` par ontologie, premier non-null gagne pour `level`/`parent`.
    - `SubjectCache` court-circuite si la demande `(codes, level, parent)` est déjà couverte (gros gain perf).
    - 5641 sujets après dédup vs 179031 avant (~×30 réduction des doublons UI).
- [x] **5c Page graphe** : route `/subjects/[id]` avec `vis-network` (force-directed). Nœuds en `shape: "text"` (sans cercle/cadre, alignés visuellement avec `SubjectsCloud`), couleur stable par hash d'id sur la palette commune, taille de police adaptative au range observé (18-38, log10 du `usage_count`), centre agrandi de +6px. Arêtes longueur log de la spécificité côté voisin (`cooc/usage_neighbor`) — les ubiquitous restent visibles mais relégués à la périphérie sans filtrage dur. Désactivation de la physique après stabilisation (drag manuel possible). Clic sur voisin → recentre. Sous le titre : badges des ontologies concernées ou "Mot-clé libre".
- [x] **5e Onglet Publications associées** : composant `<PublicationsListView>` extrait depuis `/publications/+page.svelte` (qui devient un wrapper léger), réutilisé sur `/subjects/[id]?tab=publications` avec filtre `subject_id` fixe. Filtre `subject_id` ajouté à `/api/publications`. Le composant prend des props pour le mode autonome vs filtré-par-contexte (apiKey, externalFilters, urlSync, basePath, showFilterBanner). Migration de `/laboratories/[id]` et `/persons/[id]` vers le composant : suivi dans [docs/chantiers/dry-publications-tables.md](dry-publications-tables.md).

### Phase 6 — Nuages de sujets sur dashboards

Endpoints et UI pour les nuages de sujets sur les pages structure et personne.

- [x] Endpoint `GET /api/laboratories/{id}/subjects?limit=N` : top sujets des publis du labo, exclusion des `peer_review`/`memoir`/`ongoing_thesis`, retour `SubjectFrequency[]` (id, label, count). Tests d'intégration `test_laboratories.py::TestGetLaboratorySubjects`.
- [x] Composant `SubjectsCloud.svelte` : SVG + d3-cloud, palette de 6 couleurs stable par hash d'id, font 11-32px (log10), texte horizontal uniquement, hauteur ratio 0.22 (compacte), `<a>` SVG natifs vers `/subjects/{id}`. Resize-observer pour relayout.
- [x] Intégration dashboard `/laboratories/[id]` : nuage en haut du dashboard, top 30 sujets, exclut peer_review/memoir/thèses-en-cours.
- [ ] Endpoint `GET /api/persons/{id}/subjects?limit=N` : top sujets de la personne, agrégats par fréquence sur ses authorships → publis → subjects. **Bloqué** par l'absence d'un dashboard `/persons/[id]` : à reprendre quand ce dashboard existera (l'API et l'intégration UI seront triviales en s'inspirant de la version labo).

### Phase 7 — Recherche par sujet

- [x] Étendre la recherche publications côté backend : le champ texte fouille aussi dans `subjects.label` via EXISTS sur `publication_subjects → subjects` (OR sur le titre). 3 tests d'intégration `test_publications_list.py::TestSearch` (titre, sujet, accents).
- [x] Aucune nouvelle UI : la recherche existante absorbe les sujets de façon transparente.
- [x] Prioriser les matchs sur titre devant les matchs via sujet (CASE en tête de l'ORDER BY, n'affecte que la liste paginée — pas COUNT, pas l'export). Test `test_title_match_ranks_before_subject_only_match`.
- [x] Index trigram sur `subjects.label` (migration `018`) : index `subjects_label_norm_trgm_idx` en GIN trigram sur `normalize_name_form(label)` (fonction SQL IMMUTABLE déjà présente dans le schéma, équivalente à `normalize_text` côté Python — ce qui unifie la normalisation côté `publications.title_normalized` et côté sujets).
- [x] Côté requête : la recherche sur titre passe désormais par `p.title_normalized ILIKE %s` (touche `idx_pub_title_trgm` existant) et le pattern est lui-même normalisé via `normalize_text` côté Python pour rester aligné des deux côtés.

### Phase 8 — Tests de non-régression — couverte (audit final 2026-04-30)

À chaque phase, les tests pertinents ont été ajoutés au fil de l'eau (pattern `feedback_regression_tests`). Audit final :

- [x] **Tests d'ingestion par source** — `tests/integration/pipeline/test_subjects_ingest.py` (15 tests, 6 sources : HAL, OpenAlex, WoS, CrossRef, Theses, ScanR).
- [x] **Idempotence** : la duplication des liens est interdite par la PK `publication_subjects(publication_id, subject_id, source)` (constraint DB), confirmée fonctionnellement par `test_subjects_ingest.py::TestRunOrchestrator::test_clears_and_reingests` + `test_cooccurrences.py` (recompute appelé 2x).
- [x] **Page publi : sujets dédupliqués** — `test_publications_detail.py::TestGetPublicationSubjects` (4 tests dont `test_dedup_aggregates_sources` et `test_orders_concepts_before_free`).
- [x] **Agrégat structure** : `test_laboratories.py::TestGetLaboratorySubjects` (top par fréquence + exclusion peer_review/memoir/ongoing_thesis ; périmètre via `_setup_perimeter`).
- [ ] Agrégat personne — sans objet tant que le dashboard `/persons/[id]` n'existe pas (cf Phase 6).

Tests "bonus" présents au-delà du périmètre Phase 8 :

- `test_subjects.py::TestUpsertSubject` (10 tests : merge JSONB, casse, dédup whitespace, idempotence, level/parent par ontologie) ;
- `test_subjects.py::TestLinkAndClear` (5 tests sur `publication_subjects`) ;
- `test_subjects_lookup.py` (liste/voisins/recherche par label) ;
- `test_publications_list.py::TestSearch` (4 tests : matching titre, matching sujet, accents, priorisation titre>sujet).

## Pistes pour la suite

### Hiérarchie a posteriori des sujets

Constat (avr 2026) : on ingère plat sans hiérarchie *a priori*. La distinction
"général / précis" côté UI s'appuie sur des heuristiques par ontologie (OpenAlex
level 0, HAL top-level, WoS heading) qui restent grossières. Pour aller plus
loin, deux pistes (à explorer, ne pas suringénier) :

- **Option co-occurrences** : compter les apparitions de chaque sujet et leurs
  co-occurrences dans les publis. Un sujet rare qui apparaît systématiquement
  avec un sujet fréquent est probablement son fils. Prérequis minimal : colonne
  `usage_count` sur `subjects` (ou vue matérialisée). Co-occurrences via une
  table dédiée ou query à la demande.
- **Option vocabulaire normé** : mapper nos sujets vers un référentiel
  hiérarchique existant (MeSH, OpenAlex topics complet, …). Hiérarchie clé en
  main mais matching label imparfait pour les libres spécialisés. Couverture
  partielle assumée.

À arbitrer plus tard, quand le besoin sera plus clair (probablement Phase 5
quand on construira les nuages personne/structure).

## Risques et points ouverts

- **Volume** : la table `subjects` peut grossir vite côté libres (longue traîne, fautes, casse). À mesurer après Phase 2 sur le dataset complet.
- **Bruit des libres** : keywords mal accentués, variantes singulier/pluriel, langues mêlées. Pas de normalisation poussée en première approche ; déclencher si l'UX est dégradée.
- **Bruit OpenAlex topics bas niveau** : on ingère sans seuil ; à seuiller (Phase 5 ?) si les nuages deviennent illisibles.
- **Hiérarchie OpenAlex** : on stocke `parent_id` et `level`, mais on ne s'en sert pas tout de suite. À exposer en Phase 5 si pertinent (filtrer par niveau, regrouper).
- **CrossRef topics** : décision Phase 3 selon ce que l'API expose vraiment.
- **Recherche** : la fouille `LIKE/ILIKE` sur `subjects.label` peut être lente sans index. Trigram envisagé en Phase 6.
- **Migrer rétroactivement** : Phase 2 doit pouvoir tourner sur tout l'historique `source_publications` existant, pas seulement sur les nouvelles publis. Vérifier que le pipeline accepte ce mode.
- **Curation manuelle** : la phase d'ingestion fait `DELETE` total par source puis ré-INSERT. Toute édition manuelle des `subjects` ou `publication_subjects` serait écrasée au prochain run. À adresser avant d'introduire des outils de curation côté UI (séparation source/auto vs corrections, ou colonne `manually_edited` qui exclut du DELETE).
- **Bug HAL — keywords sans parenthèses** : le champ Solr `keyword_s` de HAL est analysé/normalisé côté serveur et perd les parenthèses (et la ponctuation `[]`, `,`, etc. selon les analyseurs Solr). Exemple : "Particle tracking detectors (Solid-state detectors)" → "Particle tracking detectors Solid-state detectors". Le TEI XML (`label_xml`, déjà récupéré pour les ORCID) préserve les keywords tels quels via `<term xml:lang="…">`. Fix prévu : ajouter `parse_tei_keywords(label_xml)` dans `normalize_hal.py`, fallback sur `keyword_s` si TEI absent. Demande une re-normalisation HAL pour propager (dépend d'un re-fetch complet HAL puisque le `raw_data` du staging est vidé après normalize). À traiter quand on planifiera une repasse HAL complète.
- **Langue explicite des libres** : actuellement `language=null` pour tous les `kind='free'` afin de permettre la déduplication inter-sources sur `lower(label)` seul. On perd l'info de langue quand elle est explicite (HAL `en_keyword_s` / `fr_keyword_s`, theses systématiquement fr, OpenAlex/WoS/CrossRef ~en). Pour la conserver, deux pistes : (a) revenir au pattern `(lower(label), language)` avec convention 'en'/'fr'/null par source — implique des doublons artificiels à gérer aux frontières ; (b) ajouter une colonne `detected_languages text[]` qui agrège les langues observées sans entrer dans la dédup. À traiter avec le fix parenthèses HAL (même fichier `normalize_hal.py` impacté, et même besoin de repasse HAL pour propager).
- **Hiérarchie OpenAlex écrasée par 15 doublons de `display_name`** : notre code utilise `lower(display_name)` comme `ontology_id`, donc les rares cas où OpenAlex a deux entités distinctes avec le même libellé sont fusionnés silencieusement à l'ingestion. Cas observés (avr 2026) sur 4783 entités OpenAlex : 6 paires topic/topic, 8 paires subfield/subfield, 1 paire field/domain (`Social Sciences`). Conséquence : `usage_count` gonflé (somme de deux niveaux) et `parent_id` ne pointe que vers un parent. Fix : basculer sur les IDs OpenAlex stables (ex `T10138`) à la place de `lower(display_name)`. Implique : (1) étendre `extract_topics` dans `normalize_openalex.py` pour conserver les IDs ; (2) re-fetch OpenAlex puisque le `raw_data` du staging est vidé ; (3) migration des `ontology_id` existants. À planifier en même temps qu'une repasse OpenAlex complète.

## État du chantier (2026-04-30) — terminé

- Phases 1, 2, 3, 4, 5, 7, 8 entièrement faites. Phase 3 close sans suite après audit (CrossRef n'expose plus de sujets exploitables) ; Phase 8 confirmée couverte par les tests écrits au fil des phases.
- Phase 6 : nuage labo livré ; nuage personne en attente du dashboard `/persons/[id]` (non bloquant — reprise triviale en s'inspirant de la version labo lorsque ce dashboard existera).

Points ouverts résiduels (hors chantier) : repasse HAL pour le bug parenthèses, repasse OpenAlex pour passer aux IDs stables, langues explicites des libres, curation manuelle (cf. § Risques).

## Ordre d'attaque historique

1. Phase 1 (modélisation + migration) — bloquant.
2. Phase 2 (ingestion pipeline) — débloque le reste.
3. Phase 4 (API + page publi) — premier livrable visible.
4. Phase 5 (page sujets + co-occurrences + graphe) — gros livrable UX.
5. Phase 6 (nuages dashboards) — gain UX dashboard.
6. Phase 7 (recherche) — petit gain, peu coûteux.
7. Phase 3 (CrossRef topics) — opportuniste, à caser quand le reste est stable.
8. Phase 8 — en parallèle de chaque phase, pas en bloc final.
