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

## Phase 2 — Refonte pipeline (création dans la phase `publications`)

**Coût élevé** : touche les 5 normalizers + une nouvelle étape pipeline + une migration de données. À séquencer en plusieurs commits.

- [ ] **Modifier les 5 normalizers** : retirer les appels à `find_or_create_publisher` et `find_or_create_journal`. Écrire les données brutes dans `biblio` selon la convention figée (`publisher`, `journal`). Aucune migration de schéma nécessaire.
- [ ] **Nouvelle étape dans la phase `publications`** : pour chaque publication consolidée, agrège `biblio.publisher` / `biblio.journal` des `source_publications` inter-sources, dédoublonne, crée/met à jour le `publisher_id` et le `journal_id` de `publications`. Algorithme à concevoir (priorité source, fusion noms, etc.).
- [ ] **Déplacer `resolve_doi_prefixes`** : aujourd'hui après normalize, devra venir avant la nouvelle étape de création publisher/journal (qui peut s'appuyer sur le préfixe DOI pour le rattachement publisher).
- [ ] **Backfill** : script one-shot qui repopule `biblio.publisher` / `biblio.journal` sur les `source_publications` existantes (depuis le raw_store si dispo, sinon en repassant le normalizer).
- [ ] **Tests** : couverture des cas dédoublonnage cross-source (même journal écrit différemment selon HAL/OA/WoS).

**Sortie attendue** : normalize redevient un module de pure traduction (raw API → schéma source canonique), la phase publications devient le seul producteur de référentiels.

## Phase 3 — Enrichissement DOAJ

- [ ] **Inventaire des champs DOAJ utiles** au-delà de `is_in_doaj` : license, oa_start_year, publisher, country, sujets, persistent_id_url. Décider lesquels intégrer.
- [ ] **Décision : étendre `enrich_journal_apc` ou créer `enrich_journal_doaj`** ?
- [ ] **Schéma** : ajouter colonnes `journals.license`, `journals.oa_start_year`, etc. — ou stocker en `notes` JSONB.
- [ ] **Croisement avec `oa_status`** : si une publi est marquée `gold` mais le journal n'est pas dans DOAJ (ni autre liste OA), signaler. Inversement : publi marquée `subscription` dans une revue DOAJ ?
- [ ] **Rafraîchissement** : périodicité (mensuel ? trimestriel ?) — à arbitrer (Phase 3 ou phase ultérieure).

**Sortie attendue** : `journals` enrichis, les incohérences `oa_status` sont détectables.

## Phase 4 — Contrôles de cohérence

Quatre familles de règles, à implémenter de manière indépendante.

- [ ] **4a. DOI ↔ journal** : le préfixe DOI (`doi_prefixes.publisher_id`) doit correspondre au publisher du journal de la publication. Tolérance pour les DOI green/gold sur la même publi (preprint sur archive + version éditeur sur la revue). Incohérence vraie : article + DOI dont le préfixe correspond à une autre revue.
- [ ] **4b. doc_type ↔ journal_type** : mapping attendu (`article` → `journal`, `conference_paper` → `proceedings`, `chapter` → `book_series`, `preprint` → `preprint_repository`, etc.). Signaler les écarts.
- [ ] **4c. oa_status ↔ journal_type / DOAJ** : `full_oa` ↔ revue DOAJ ; `subscription` ↔ revue non-DOAJ. Tolérer `green` partout.
- [ ] **4d. Sujets ↔ revue** : pour chaque revue, calculer la distribution des sujets de ses publis. Signaler les sujets aberrants (rarement vus dans la revue mais présents sur une publi donnée). Permet de remonter les sujets OpenAlex bruités (cf. TODO existant sur la qualité des sujets).

Implémentation envisagée :
- Vue SQL ou queries d'agrégation accessibles depuis la page admin (lecture en temps réel).
- En complément, un job pipeline périodique qui logue les nouvelles incohérences dans un audit/snapshot (cohérent avec l'architecture observabilité Phase 2.2).
- UI : panneaux de revue manuelle pour chaque famille d'incohérence.

## Phase 5 — Pages publiques « Référentiels »

- [ ] **Refonte du menu** : regrouper Éditeurs / Revues / Sujets dans un dropdown unique « Référentiels » pour éviter la surcharge du menu principal.
- [ ] **Page `/editeurs`** : liste paginée, facettes `publisher_type`, `country`, `is_predatory`. Tri par nb de publis, alphabétique.
- [ ] **Page `/editeurs/{id}`** : détail (description, type, pays, indicateurs), liste de publis (paginée, facettes existantes), liste de revues affiliées.
- [ ] **Page `/revues`** : liste paginée, facettes `journal_type`, `is_in_doaj`, `oa_model`, publisher.
- [ ] **Page `/revues/{id}`** : détail (titre, ISSN, publisher, type, oa_model, APC, indicateurs), liste de publis, sujets dominants (réutilise infrastructure Phase 2 chantier subjects), incohérences détectées (Phase 4) si admin connecté.
- [ ] **Endpoint API publics** correspondants (`/api/publishers/*`, `/api/journals/*`), modèles Pydantic.

## Questions ouvertes (au-delà des décisions à trancher en amont)

- **Ordre Phase 1 vs Phase 2** : faut-il typer (Phase 1) avant de refondre le pipeline (Phase 2) ? L'attribution heuristique du `publisher_type` (Phase 1) repose sur `doi_prefixes`, qui est déjà disponible — donc Phase 1 indépendante. Mais si Phase 2 réécrit la création publisher/journal, autant intégrer le typage dans le nouveau flux. → Compromis possible : Phase 1 traite uniquement le typage des **publishers/journals existants** (statique), Phase 2 ajoute la pose du type dans le nouveau flux (dynamique).
- **Fusion d'un publisher avec un autre lors de la migration data Phase 2** : si la refonte révèle des doublons, on les fusionne ? On signale ? L'admin gère manuellement ?
- **Rétro-compatibilité API** : si on bouge `journal_id` côté pipeline et qu'on change la sémantique des colonnes brutes, certains endpoints peuvent retourner des données légèrement différentes le temps de la transition.
- **DOAJ : périmètre OA** : tous les journals OA ne sont pas dans DOAJ. Croiser aussi avec une liste de revues OA non-DOAJ (Sherpa, OpenAlex `oa_status` ?) pour ne pas faux-positiver les incohérences `oa_status` côté Phase 4c.

## Liens

- [`METIER_doi-ra-datacite.md`](METIER_doi-ra-datacite.md) — table `doi_prefixes` utilisée pour l'attribution heuristique du `publisher_type` (Phase 1) et pour les contrôles DOI ↔ journal (Phase 4a).
- [`METIER_doc-types.md`](METIER_doc-types.md) — mapping `doc_type` ↔ `journal_type` utilisé en Phase 4b.
- TODO.md — l'item « création publishers et journals avant la phase publications » et plusieurs items connexes (`distinguer types d'entités`, `DOAJ pour contrôler oa_status`, `contrôler doc_type via DOI`, `Pages Éditeurs/Revues`) sont absorbés par cette fiche.
