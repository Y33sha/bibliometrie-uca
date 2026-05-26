# Chantier — Pipeline : phase `publishers_journals` (référentiels enrichis)

Commencé le 2026-05-26

## Contexte

L'enrichissement des entités `publishers` et `journals` est aujourd'hui dispersé, ce qui rend l'ajout de nouvelles sources frictionnel et la cohérence inter-sources opaque.

- **`normalize`** crée les entités via `find_or_create_publisher` / `find_or_create_journal` (volontairement gardé là par [METIER_publishers-journals.md](METIER_publishers-journals.md) Phase 2). À ne PAS toucher.
- **`resolve_doi_prefixes`** (entre normalize et affiliations) renseigne `doi_prefixes` (avec son `ra` et son `crossref_member_id`) et lie `publisher_id` quand le nom Crossref matche `publisher_name_forms`. C'est de l'enrichissement de référentiel — mal rangé en phase top-level isolée.
- **`enrich`** mélange `enrich_oa_status` (Unpaywall, **per-publication**) et `enrich_journal_apc` (OpenAlex Sources, **per-journal** : APC, `is_in_doaj` flag, `journal_type` depuis 2026-05-26). Le carpe-lapin nuit à la lisibilité.
- **Import DOAJ CSV** vit comme script CLI manuel (`interfaces/cli/imports/import_doaj_csv.py`). Bootstrap-style, pas branché au pipeline régulier.
- **Aucune source pour `publishers.country` ni `publishers.publisher_type`** — ces colonnes restent NULL / `'unknown'` faute de phase d'enrichissement, alors qu'OpenAlex Publishers fournit `country_codes` + `ids.ror` + `ids.wikidata` gratuitement et que ROR permet ensuite de dériver un `publisher_type`.

**Objectif** : consolider tout l'enrichissement référentiel dans une unique phase pipeline `publishers_journals`, positionnée entre `normalize` et `affiliations`. Garder `enrich_oa_status` (Unpaywall) à sa place — c'est per-publication, hors-scope.

## Décisions à trancher

1. **Position dans le pipeline** — **tranché** : entre `normalize` et `affiliations`, à la place exacte de `resolve_doi_prefixes` (qui devient un sub-step interne).

2. **Sort de `enrich_journal_apc`** — **tranché** : à garder dans la nouvelle phase. Branche déjà `journal_type` (chantier 2026-05-26) qui doit rester actif. Pour les montants APC : audit préalable de cohérence APC OpenAlex vs APC DOAJ (cf. Phase 7) avant toute décision de retrait.

3. **`parent_publisher` d'OpenAlex** — **tranché** : NON, hors scope cette fois. À reposer si l'usage le justifie (consolidation auto "BMC → Springer Nature" = fusion automatique = chantier à risque).

4. **DOAJ — API ou CSV** — **tranché** : extracteur API pour intégrer dans la phase pipeline. Le CSV reste pour bootstrap / catch-up massif occasionnel mais sort du workflow régulier.

5. **ROR / Wikidata — comment alimenter** — **tranché** : exclusivement via les `ids` retournés par OpenAlex Publishers (= identifiants déjà résolus par OpenAlex, fiables). **Pas de matching par nom** (trop fragile). Pour les publishers sans `openalex_id`, le ROR reste NULL et le typage reste manuel.

6. **Mapping ROR `types` → notre `publisher_type`** — **à figer à l'audit** : proposition de départ ci-dessous, à valider sur l'échantillon réel (Phase 3).
   | ROR | publisher_type |
   |---|---|
   | `Company` | `commercial` |
   | `Education` | `academic_institution` |
   | `Government` | `academic_institution` |
   | `Archive` | `repository` |
   | `Nonprofit` | _à arbitrer_ — PLOS et eLife sont Nonprofit mais sentent le commercial en pratique |
   | `Facility` / `Healthcare` / `Other` | NULL (skip) |

7. **Politique d'écrasement** — **tranché** : sur tous les sub-steps d'enrichissement, écraser uniquement quand la valeur actuelle est NULL ou égale au défaut DB (`'unknown'` pour `publisher_type`, `'journal'` pour `journal_type`). Préserver les valeurs admin explicites. Flag `--force` pour passer outre, comme sur le backfill journal_type.

## Phases

Ordre par dépendance. Les phases 2, 3, 4, 5 sont indépendantes une fois la phase 1 livrée.

- **Phase 1 — Refonte structurelle.** Créer la phase pipeline `publishers_journals`. Déplacer `resolve_doi_prefixes` et `enrich_journal_apc` dedans. `enrich_oa_status` (Unpaywall) reste dans la phase `enrich` (per-publication).
- **Phase 2 — OpenAlex Publishers.** Nouveau sub-step. Lit `publishers.openalex_id`, fetche `/api/publishers/{id}`, pose `country`, `ror`, `wikidata` (nouvelles colonnes / déjà existantes selon le cas).
- **Phase 3 — ROR → `publisher_type`.** Pour chaque publisher avec `ror` non-NULL, lookup ROR API → `types[0]` → mapping (cf. décision 6). Audit préalable de la distribution.
- **Phase 4 — DOAJ via API.** Extracteur DOAJ par ISSN. Stockage existant (`doaj_payload` JSONB, `doaj_imported_at`). Au passage : capturer l'URL de la fiche DOAJ du journal (typiquement `https://doaj.org/toc/{doaj_id}` ou équivalent à confirmer sur le payload API) pour le **lien depuis le badge DOAJ** (cf. Phase 6).
- **Phase 5 — Crossref Members (fallback `country`).** Pour les publishers sans `openalex_id` mais avec `crossref_member_id` posé par `doi_prefixes`, fetcher `/members/{id}` → parser `location` → ISO-2.
- **Phase 6 — Front : badge DOAJ → lien.** Substitue le badge passif par un lien vers `homepage_url` extrait du `doaj_payload` (Phase 4). Petit chantier UI.
- **Phase 7 — Audit APC OpenAlex vs DOAJ.** Comparer les montants sur les revues présentes dans les 2 sources. Décider si on garde l'APC OpenAlex, on bascule sur DOAJ uniquement, ou on stocke les deux.

## Phase 1 — Refonte structurelle

Livrée le 2026-05-26 (commit `d003bb9e`).

- [x] Créer `application/pipeline/publishers_journals/`.
- [x] Déplacer `application/pipeline/resolve_doi_prefixes.py` dedans.
- [x] Déplacer + renommer `enrich/enrich_journal_apc.py` → `publishers_journals/enrich_journals_from_openalex.py`. Fonction `run_enrich` renommée en `run_enrich_journals_from_openalex`.
- [x] Renommer la phase `enrich` (devenue misnomer) en `oa_status`. Module déplacé `enrich/enrich_oa_status.py` → `oa_status/run.py`. Fonction `run_enrich` → `run_enrich_oa_status`.
- [x] `run_pipeline.py` : registre PHASES mis à jour. `publishers_journals` remplace `resolve_doi_prefixes` au top-level ; `oa_status` remplace `enrich`. `phase_publishers_journals` orchestre les 2 sub-steps.
- [x] Adapter `application/pipeline/modes.py` : `run_enrich: bool` → `run_oa_status: bool` (gate phase Unpaywall). Ajout `run_journal_enrichment: bool` (gate le sub-step OpenAlex Sources dans `publishers_journals`). `resolve_doi_prefixes` tourne sans gate dans tous les modes (comportement préservé).
- [x] CLI entry-points synchronisés (`enrich_journal_apc.py` → `enrich_journals_from_openalex.py` ; imports updatés sur `enrich_oa_status.py` et `resolve_doi_prefixes.py`).
- [x] Imports synchronisés sur le oneshot `backfill_journal_types_from_openalex.py` et les tests (`test_enrich_oa_status_async.py`, `test_resolve_doi_prefixes.py`).
- [x] `pyproject.toml` : override mypy `application.pipeline.enrich.*` remplacé par les 2 nouveaux paths (tolérance JSON OpenAlex préservée).

## Phase 2 — OpenAlex Publishers

- [ ] **Migration Alembic** : ajouter `publishers.country` (déjà présent), `publishers.ror text` (nouveau, `UNIQUE NULLS NOT DISTINCT`), `publishers.wikidata text` (nouveau). Index optionnels sur ror / wikidata.
- [ ] **Sub-step `enrich_publishers_from_openalex`** : itère sur `publishers.openalex_id IS NOT NULL`, batch via filtre OpenAlex `openalex:|`. Écrit `country` (`country_codes[0]`), `ror` (`ids.ror` parsé), `wikidata` (`ids.wikidata` parsé). Politique d'écrasement standard (cf. décision 7).
- [ ] **Script oneshot** `interfaces/cli/oneshot/backfill_publishers_from_openalex.py` pour réinterroger l'historique (pattern reproductible depuis `backfill_journal_types_from_openalex.py`).
- [ ] **Audit avant écriture** : combien de publishers ont `openalex_id` non-NULL ? Si < 50%, brancher d'abord une étape de matching (un autre chantier).

## Phase 3 — ROR → publisher_type

- [ ] **Audit préalable** : tirer 50 publishers avec `ror`, fetcher leurs ROR records, classer la distribution `types[0]`. Décider du mapping définitif (notamment pour `Nonprofit`).
- [ ] **Sub-step `enrich_publishers_from_ror`** : itère sur `publishers.ror IS NOT NULL AND publisher_type IN ('unknown', NULL)`. Lookup ROR par batch (l'API ROR a un endpoint `/organizations/{id}`). Écrit `publisher_type` selon le mapping.
- [ ] Rate-limit ROR : à vérifier (l'API publique est limitée mais correcte). Polite usage.
- [ ] **Script oneshot** de backfill.

## Phase 4 — DOAJ via API

- [ ] **Extracteur API** : module `infrastructure/sources/doaj/`. Endpoint `https://doaj.org/api/journals/issn/{issn}` (un par requête, pas de bulk dispo).
- [ ] **Sub-step `enrich_journals_from_doaj`** : itère sur `journals.issn IS NOT NULL OR journals.eissn IS NOT NULL`. Throttle conformément à `DOAJ_DELAY`. Met à jour `doaj_payload` + `doaj_imported_at` + `is_in_doaj`.
- [ ] **Catch-up CSV** : `interfaces/cli/imports/import_doaj_csv.py` reste utilisable pour un dump complet rapide. Doc à mettre à jour pour expliquer les 2 modes.
- [ ] **Question ouverte** : fréquence de rafraîchissement (toutes les phases publishers_journals, ou un sous-flag) — DOAJ ne bouge pas si vite, refetch quotidien overkill.

## Phase 5 — Crossref Members (fallback country)

- [ ] **Sub-step `enrich_publishers_from_crossref_members`** : itère sur `publishers WHERE country IS NULL AND EXISTS (SELECT 1 FROM doi_prefixes WHERE publisher_id = publishers.id AND crossref_member_id IS NOT NULL)`. Fetcher `https://api.crossref.org/members/{id}`. Parser `location` (texte libre) → ISO-2 via une regex ou un parser dédié.
- [ ] **Petit utilitaire de parsing** `domain/publishers/crossref_location_parser.py` : tester sur un échantillon, prudence sur "United States" → US, "United Kingdom" → GB, etc. Cas dégénérés : skip si parsing échoue.

## Phase 6 — Front : badge DOAJ → lien vers la fiche DOAJ

- [ ] Une fois `doaj_payload` enrichi (Phase 4), exposer l'URL de la fiche DOAJ côté DTO `JournalDetailResponse` (et `JournalOut` ? à juger). L'URL pointe vers la page DOAJ du journal (ex. `https://doaj.org/toc/{doaj_id}`) — pas vers la homepage de la revue. Champ exact du payload à confirmer (probablement reconstruit depuis l'`id` DOAJ ; au pire l'ISSN suffit).
- [ ] Composant DOAJ badge cliquable : `<a href={url} target="_blank" rel="noopener">DOAJ</a>` au lieu de `<span>DOAJ</span>`. Style préservé.
- [ ] Pages concernées : `journals/[id]` (header), `JournalsListView` (cellule titre), `admin/journals` (tableau).

## Phase 7 — Audit APC OpenAlex vs DOAJ

- [ ] **Script d'audit** (oneshot) : `SELECT j.id, j.title, j.apc_amount, j.doaj_payload->>'APC amount', j.doaj_payload->>'APC currency' FROM journals WHERE j.apc_amount IS NOT NULL AND j.doaj_payload IS NOT NULL`. Comparer écart absolu et relatif. Reporter la distribution.
- [ ] **Décision à prendre selon résultats** : (a) garder OpenAlex comme source primaire APC, (b) basculer sur DOAJ, (c) garder les deux colonnes (`apc_amount_openalex`, `apc_amount_doaj`) et exposer les divergences en UI.
- [ ] Le sub-step OpenAlex Sources actuel (`enrich_journals_from_openalex`) écrit déjà APC dans `apc_amount` — adapter selon la décision.

## Phase 8  — Documentation
- [ ] **Documentation pipeline**: ajouter et documenter la phase publishers_journals.
- [ ] **Documentation sources**: ajouter les nouvelles sources moissonnées.

## Questions ouvertes

- **`parent_publisher` d'OpenAlex** : faut-il consolider automatiquement les filiales sous le parent ? Risque de fusion abusive (BMC ≠ Springer Nature en pratique éditoriale). À reposer si on observe des problèmes de hiérarchie à l'usage.
- **Sources `country` d'OpenAlex sur les journals** : OpenAlex Sources retourne aussi un `country_codes` pour les journals. Diverge parfois du publisher (revue éditée par filiale dans un pays différent). À exploiter ? Hors-scope cette fiche.
- **Wikidata** : on stocke l'identifiant via OpenAlex (Phase 2), mais on ne s'en sert pour rien dans cette fiche. Réserve : lookup Wikidata pour metadata supplémentaires (sujets d'édition, périodes d'activité) — utile pour un futur chantier d'analyse historique des éditeurs.
- **Mapping ROR `Nonprofit`** : à figer après audit Phase 3 (PLOS / eLife / Hindawi sont les cas litigieux).
- ~~**Modes pipeline**~~ — **tranché Phase 1** : `phase_publishers_journals` tourne dans tous les modes (comme `resolve_doi_prefixes` historiquement). Le sub-step `enrich_journals_from_openalex` est gated par `MODES[mode].run_journal_enrichment` (True en `full` uniquement, comme l'était `run_enrich` historiquement pour le journal_apc).

## Liens

- [METIER_publishers-journals.md](METIER_publishers-journals.md) — fiche d'origine (typage, biblio, DOAJ CSV, UI publique). Cette nouvelle fiche prolonge la décision Phase 2 « refonte gardée ouverte » côté **enrichissement** (l'entité-création reste où elle est).
- [METIER_doi-ra-datacite.md](METIER_doi-ra-datacite.md) — `doi_prefixes` consommé par Phase 5 (crossref_member_id).
- [METIER_doc-types.md](METIER_doc-types.md) — Phase 4b cohérence `doc_type` ↔ `journal_type`, alimentée indirectement par cette phase via `journal_type` correctement rempli.
