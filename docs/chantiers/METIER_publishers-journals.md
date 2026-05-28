# Chantier — Publishers & Journals : typage, pipeline, cohérence, UI

Commencé le 2026-05-21

## Contexte

Plusieurs manques connexes sur la modélisation et l'exploitation des éditeurs / revues, identifiés à l'usage :

1. **Création précoce et dispersée dans le pipeline.** Les 5 normalizers (`normalize_hal`, `normalize_openalex`, `normalize_wos`, `normalize_scanr`, `normalize_crossref`) appellent chacun `find_or_create_publisher` et `find_or_create_journal`. Conséquences : mélange de responsabilités (le normalize fait à la fois du nettoyage et de la consolidation référentielle), création répétée alors qu'une déduplication consolidée en aval serait plus juste, difficulté à ajouter des contrôles de cohérence qui supposent une vue inter-sources.

2. **Typage des entités incomplet.**
   - `journals.journal_type` existe (text, default `'journal'`) mais peu exploité.
   - `publishers.publisher_type` n'existe pas (un `publisher_type` existe dans `apc_payments`, sans rapport avec la table `publishers` canonique).
   - Distinguer ces types ouvrirait la qualification éditoriale : éditeurs commerciaux vs sociétés savantes vs établissements d'enseignement vs repositories (Zenodo, figshare, …) ; revues vs proceedings vs médias (vulgarisation) vs repositories.

3. **DOAJ sous-exploité.** `enrich_journal_apc` peuple aujourd'hui `is_in_doaj` (booléen) et `apc_amount`. La richesse DOAJ (license, oa_model détaillé, country, publisher, sujets) n'est pas utilisée — alors qu'elle permettrait de contrôler `oa_status` des publications associées.

4. **Pas de contrôles de cohérence systématiques** entre DOI / journal / doc_type / oa_status / sujets. Plusieurs incohérences observées à l'usage : article + DOI de preprint dans une revue, doc_type `article` sur un journal_type `proceedings`, oa_status `gold` sur une revue subscription, sujets aberrants pour la revue.

5. **Pas de pages publiques** dédiées aux éditeurs et revues (admin seulement). Une exploration publique permettrait aussi de mettre en visibilité les incohérences détectées (Phase 4) et donnerait un point d'entrée pour les co-occurrences sujets ↔ revue.

## Décisions à trancher en amont

À arbitrer avant de poser la première brique. Plusieurs sont structurantes et conditionnent l'ordre des phases.

1. **Format de stockage des données brutes dans `source_publications`** (Phase 2) — **tranché** : tout dans `biblio` JSONB (extension de l'usage existant). Convention de clés à figer :
   - existantes : `volume`, `issue`, `pages`, `first_page`, `last_page`, `article_number`, `page`
   - nouvelles : `publisher` (text, nom brut), `journal` (object : `{title, issn, eissn, issnl, openalex_id}`)

2. **Liste de valeurs `publisher_type`** (Phase 1) — **tranché provisoirement** : `commercial`, `learned_society`, `academic_institution`, `repository`, `aggregator`, `unknown`. À affiner après inspection de DOAJ (Phase 3) — la richesse DOAJ pourrait suggérer des cas qu'on n'a pas anticipés.

3. **Liste de valeurs `journal_type`** — **tranché** : 6 valeurs déjà présentes dans le dropdown de la page admin (`admin/journals/+page.svelte`), à figer telles quelles :
   | value | label FR |
   |---|---|
   | `journal` | Revue |
   | `proceedings` | Proceedings |
   | `repository` | Archive/dépôt |
   | `book_series` | Série d'ouvrages |
   | `preprint_server` | Serveur de preprints |
   | `media` | Média |

   En base aujourd'hui : `journal` (18166), `repository` (2), `media` (2), `book_series` (2). `proceedings` et `preprint_server` prévus dans le dropdown mais jamais utilisés. **Centralisation côté frontend** : suite à la décision 4 (enum SQL), un endpoint `/api/journal-types` qui boucle sur l'enum SQL + mapping `{value, label_fr}` côté Python (compagnon Literal validé par le test de cohérence) — le frontend boucle, plus de hardcode des `<option>`.

4. **Forme du typage** — **tranché** : enum SQL (cohérent avec le reste du projet : `doc_type`, `source_type`, `oa_type`, `identifier_origin`, `identifier_status`). Deux enums à créer : `publisher_type` et `journal_type` (migration de `journals.journal_type` text → enum). Ajout d'une valeur = migration Alembic dédiée (ALTER TYPE ADD VALUE), pas un drame vu la fréquence.

   Liste Python si nécessaire (Literal côté `domain/`) : pattern projet = liste identique + test d'intégration vérifiant la cohérence Python ↔ DB via `enum_range`, cf. [`tests/integration/test_scenarios.py::TestSourcesEnum`](../../tests/integration/test_scenarios.py#L232).

5. **Attribution initiale du type** (publishers et journals existants en base) — **tranché** : principalement via DOAJ (Phase 3) qui devrait couvrir une grande part automatiquement ; reste = saisie manuelle via UI admin. Des scripts one-shot d'inférence (par exemple « type déduit du `doc_type` dominant des publis associées ») restent envisageables à la marge, à juger une fois DOAJ exploité.

6. **Détection des incohérences (Phase 4) : batch ou à la lecture ?** — **différé**. Décision prématurée à ce stade : le bon choix dépend du type d'incohérence. Le contrôle DOI ↔ journal est simple à repérer et peut tenir dans une vue/highlight UI ; le contrôle journal ↔ sujet est plus subtil et demandera probablement un calcul d'agrégat batch. À arbitrer règle par règle au démarrage de Phase 4, une fois Phase 2-3 livrées (l'infrastructure publishers/journals consolidée donnera une assise pour juger).

## Phases

Ordonnées par dépendance. Phase 2 est la plus invasive ; les Phases 1, 3, 5 peuvent en partie démarrer en parallèle si on souhaite paralléliser.

- **Phase 1 — Typage** : `publisher_type` (nouveau), `journal_type` (existant à exploiter). Schéma + attribution initiale + UI admin pour gérer.
- **Phase 2 — Refonte pipeline** : création publishers/journals déplacée des normalizers vers la phase `publications`. `resolve_doi_prefixes` suit. Les normalizers ne gardent plus que les données brutes.
- **Phase 3 — Enrichissement DOAJ** : étendre `enrich_journal_apc` (ou créer un module dédié) pour ramener la richesse DOAJ et croiser avec `oa_status` des publications.
- **Phase 4 — Contrôles de cohérence** : règles DOI ↔ journal, doc_type ↔ journal_type, oa_status ↔ journal_type, sujets ↔ revue. Vue admin + signalement.
- **Phase 5 — UI publique « Référentiels »** : pages éditeurs et revues (liste + détail), regroupées avec Sujets dans un dropdown menu « Référentiels ».

## Phase 1 — Typage publisher_type / journal_type

**Côté schéma (Alembic)** :
- [x] Créer l'enum SQL `publisher_type` (`commercial`, `learned_society`, `academic_institution`, `repository`, `aggregator`, `unknown`).
- [x] Créer l'enum SQL `journal_type` (`journal`, `proceedings`, `repository`, `book_series`, `preprint_server`, `media`).
- [x] `ALTER TABLE publishers ADD COLUMN publisher_type publisher_type NOT NULL DEFAULT 'unknown'`.
- [x] `ALTER COLUMN journals.journal_type TYPE journal_type USING journal_type::journal_type` (les 4 valeurs existantes en base sont déjà toutes dans la liste cible, pas de mapping nécessaire). Garder le default à `'journal'`.

**Côté domain + application** :
- [x] Constante Literal `PUBLISHER_TYPES` dans `domain/publishers/publisher.py`, `JOURNAL_TYPES` dans `domain/journals/journal.py`.
- [x] Test d'intégration `TestPublisherTypesEnum` / `TestJournalTypesEnum` vérifiant la cohérence Python ↔ DB via `enum_range`, sur le modèle de [`tests/integration/test_scenarios.py::TestSourcesEnum`](../../tests/integration/test_scenarios.py#L232).

**Côté API** :
- [x] Endpoints `/api/publisher-types` et `/api/journal-types` qui retournent `[{value, label_fr}]` à partir de l'enum SQL. Le mapping `{value → label_fr}` vit côté router (concern UI, pas domain).
- [x] Modèles Pydantic associés.

**Côté UI admin** :
- [x] `admin/publishers/+page.svelte` : ajouter un dropdown d'édition `publisher_type`, alimenté par `/api/publisher-types`.
- [x] `admin/journals/+page.svelte` : remplacer le dropdown `journal_type` hardcodé (6 `<option>`) par un boucle sur l'endpoint `/api/journal-types`.

L'attribution initiale est traitée hors Phase 1 :
- L'essentiel via DOAJ (Phase 3).
- Le reste, manuel via l'UI admin.
- D'éventuels scripts one-shot d'inférence (par exemple à partir du `doc_type` dominant des publis associées) restent à la discrétion de la user, hors-scope formel de la fiche.

**Sortie attendue** : schéma + UI prêts. Les `publisher_type` restent à `'unknown'` (default) en attendant Phase 3 ; les `journal_type` gardent leur valeur existante (`'journal'` pour la quasi-totalité).

## Phase 2 — Traçabilité brute via biblio (approche minimale)

**Décision** : ne pas refondre le pipeline. Garder le comportement actuel (les 5 normalizers continuent d'appeler `find_or_create_publisher` / `find_or_create_journal` et de poser `source_publications.journal_id`), **ajouter** `biblio.publisher` (text, nom brut) et `biblio.journal` (object : `{title, issn, eissn, issnl, openalex_id}`) en parallèle pour conserver la trace de ce que chaque source a renvoyé. Les divergences inter-sources restent détectables sans pré-agrégation destructive.

- [x] **Modifier les 5 normalizers** : à la création/mise à jour d'un `source_publication`, écrire `biblio.publisher` + `biblio.journal` selon la convention. Pas de modification d'ordonnancement, pas de migration de schéma. `source_publications.journal_id`, `container_title` et `resolve_doi_prefixes` restent en place avec leur producteur actuel.
- [x] **Tests** : couverture de l'écriture biblio dans chaque normalizer + non-régression des `find_or_create_*`.
- [ ] **Backfill** *(optionnel, différé)* : un réimport homogénéiserait `biblio` sur l'historique, mais les anciennes rows sans biblio ne cassent rien — les nouvelles rows portent l'info dès le prochain run. À juger plus tard, quand un usage concret émergera (probablement : outillage de détection des variants inter-sources sur le nom/ISSN d'un même journal — non spécifié à date).

**Sortie attendue** : traçabilité du brut acquise sans refonte pipeline. La critique « création précoce et dispersée dans normalize » du contexte est **volontairement non adressée** — option de refonte gardée ouverte si la traçabilité brute s'avère insuffisante à l'usage (chantier dédié à créer alors).

## Phase 3 — Enrichissement DOAJ

**Décisions tranchées** :
- **Source principale** : dump CSV public DOAJ (mensuel, pas de rate-limit). Extracteur API à venir pour un mode incrémental si besoin (différé).
- **Stockage** : colonne `journals.doaj_payload` (JSONB, payload brut) + `journals.doaj_imported_at` (timestamptz). Extraction des champs utiles en colonnes dédiées au fil des besoins Phase 4.
- **Module** : `enrich_journal_doaj` (nouveau). `enrich_journal_apc` reste fonctionnel mais est marqué legacy — sera retiré une fois le flux DOAJ stable et l'APC repompé depuis `doaj_payload`.
- **Flagging `is_in_doaj`** : CSV = source de vérité. Reset à FALSE pour tous les journals puis SET TRUE sur les ISSN matchés.

- [x] **Migration Alembic** : `journals.doaj_payload jsonb`, `journals.doaj_imported_at timestamptz` (révision `e5a3f7b8c2d4`).
- [x] **Script CLI d'import CSV** : lit `data/doaj_journalcsv_*.csv`, match par ISSN/eISSN cross-colonne contre `journals.issn`/`eissn`/`issnl`, bulk update `doaj_payload` + `doaj_imported_at` + `is_in_doaj`. Stats en fin de run (matchés / non matchés / rows DOAJ sans correspondance interne).
- [ ] **Extracteur API DOAJ** *(différé)* : pour rafraîchissement incrémental quotidien/hebdo. Le CSV mensuel suffit pour démarrer.
- [ ] **Croisement avec `oa_status`** : Phase 4c — `full_oa` ↔ revue DOAJ, `subscription` ↔ non-DOAJ.
- [ ] **Retirer `enrich_journal_apc`** *(différé)* : une fois `doaj_payload` exploité (APC + DOAJ flag) et stabilité confirmée.

**Sortie attendue** : `journals` enrichis avec le payload DOAJ brut, incohérences `oa_status` détectables (Phase 4c), prêt pour exploitation publishers / sujets / license au fil des besoins.

## Phase 4 — Contrôles de cohérence

Quatre familles de règles, à implémenter de manière indépendante.

- [ ] **4a. DOI ↔ journal** : le préfixe DOI (`doi_prefixes.publisher_id`) doit correspondre au publisher du journal de la publication. Tolérance pour les DOI green/gold sur la même publi (preprint sur archive + version éditeur sur la revue). Incohérence vraie : article + DOI dont le préfixe correspond à une autre revue. Affichage frontend à concevoir.
- [x] **4b. doc_type ↔ journal_type** : mapping `EXPECTED_DOC_TYPES_BY_JOURNAL_TYPE` dans [`domain/journals/expected.py`](../../domain/journals/expected.py). Surfacé sur le dashboard `/journals/[id]` : tag « Attendus » au-dessus du tableau + lignes inattendues en warning. Backend : `expected: bool` sur chaque `DocTypeCount` + `expected_doc_types: list[str]` au niveau réponse.
- [x] **4c. oa_status ↔ oa_model** : mapping `EXPECTED_OA_STATUSES_BY_OA_MODEL` (même structure, indexé sur `oa_model`). À raffiner ultérieurement avec les APC pour distinguer gold/diamond, et avec le DOAJ pour repérer les `subscription` qui auraient migré (Q ouverte : croiser avec DOAJ comme oracle).
- [ ] **4d. Sujets ↔ revue** : pour chaque revue, calculer la distribution des sujets de ses publis. Signaler les sujets aberrants (rarement vus dans la revue mais présents sur une publi donnée). Permet de remonter les sujets OpenAlex bruités (cf. TODO existant sur la qualité des sujets). Point le plus difficile, à concevoir.

Implémentation envisagée :
- Vue SQL ou queries d'agrégation accessibles depuis la page admin (lecture en temps réel).
- En complément, un job pipeline périodique qui logue les nouvelles incohérences dans un audit/snapshot (cohérent avec l'architecture observabilité Phase 2.2).
- UI : panneaux de revue manuelle pour chaque famille d'incohérence.

## Phase 5 — Pages publiques « Référentiels »

Routes publiques en anglais, cohérentes avec le reste du projet (`/laboratories`, `/persons`, `/publications`, `/subjects`).

- [x] **Refonte du menu** : dropdown « Référentiels » côté public avec Éditeurs + Revues + Sujets.
- [x] **Page `/publishers`** : recherche, facettes `publisher_type` / `country` / `is_predatory`, tri (nom / nb revues / nb publis), pagination.
- [x] **Page `/publishers/{id}`** : header métadonnées (nom, type, pays, préfixes DOI, openalex_id) + onglets Dashboard (distributions journal_type, doc_type, oa_status, sujets dominants) / Revues (tableau paginé du portfolio) / Publications (`PublicationsListView` filtré).
- [x] **Page `/journals`** : recherche, facettes `journal_type` / `is_in_doaj` / `oa_model`, tri (titre / publis / éditeur), pagination. Filtre `publisher` différé (demanderait un autocomplete).
- [x] **Page `/journals/{id}`** : header métadonnées + onglets Dashboard (distributions doc_type, oa_status, sujets dominants, données DOAJ) / Publications (`PublicationsListView` filtré). Charts et nuages de mots à venir quand l'usage validera ce qui mérite une visualisation. Incohérences détectées (Phase 4) viendront s'ancrer ici une fois les règles posées.
- [x] **Endpoint API publics** : revues (`/api/journals/{id}`, `/dashboard`, `/subjects`, `/oa-models`) + éditeurs (`/api/publishers/{id}`, `/dashboard`, `/subjects`, `/countries`).

## Questions ouvertes (au-delà des décisions à trancher en amont)

- **DOAJ : périmètre OA** : tous les journals OA ne sont pas dans DOAJ. Croiser aussi avec une liste de revues OA non-DOAJ (Sherpa, OpenAlex `oa_status` ?) pour ne pas faux-positiver les incohérences `oa_status` côté Phase 4c.

## Liens

- [`METIER_metadata-correction.md`](METIER_metadata-correction.md) — point unique de matérialisation des corrections cross-table ; les règles issues de la Phase 4 (cohérence éditoriale → correction `doc_type` / `oa_status`) y sont implémentées.
- [`METIER_doi-ra-datacite.md`](METIER_doi-ra-datacite.md) — table `doi_prefixes` utilisée pour l'attribution heuristique du `publisher_type` (Phase 1) et pour les contrôles DOI ↔ journal (Phase 4a).
- [`METIER_doc-types.md`](METIER_doc-types.md) — mapping `doc_type` ↔ `journal_type` utilisé en Phase 4b.
- TODO.md — l'item « création publishers et journals avant la phase publications » et plusieurs items connexes (`distinguer types d'entités`, `DOAJ pour contrôler oa_status`, `contrôler doc_type via DOI`, `Pages Éditeurs/Revues`) sont absorbés par cette fiche.

## A intégrer

* Toutes les revues contenant les mots "conference", "symposium", "proceedings", "lecture notes" sont de type "proceedings". (voir si exceptions type PNAS)
* Toutes les revues contenant le mot eBooks sont de type "collection de livres"
