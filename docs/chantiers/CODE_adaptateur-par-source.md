# Chantier — Une source, un adaptateur

## Contexte

### Déclaration d'une source

Ajouter une source touche une quinzaine de tables et de listes :

- le registre `domain/sources/registry.py` : `Source`, `SOURCE_LABELS`, `HARVESTED_SOURCES`, `DOI_SEARCHABLE_SOURCES`, `SOURCE_PRIORITY`, `STRUCTURE_API_SOURCES` ;
- `PERSON_SEARCHED_SOURCES` dans `pipeline/graph.py`, les sources du mode `full` dans `pipeline/runtime/modes.py` ;
- une table par phase ou par réglage : `harvest`, `harvest_by_person`, `fetch_missing`, `fetch_stale`, `normalize`, `change_detection`, `api_params`, `config` ;
- la copie de `SOURCE_LABELS` dans le frontend (`$lib/sources.ts`).

Des tests vérifient les tables de `harvest` et de `normalize`. Une source absente d'une autre table lève `KeyError` à l'exécution.

Les politiques de source sont des littéraux dans les orchestrateurs :

- WoS sur option : `modes.py`, `harvest.py`, `signals.py` ;
- theses.fr hors fenêtre d'années : `theses/harvest.py`, `common/harvest.py`, `fetch_stale.py`, `delete_source_records_out_of_window.py` ;
- mode `daily` réduit à HAL : `modes.py` et `harvest.py` ;
- agence d'enregistrement de Crossref et de DataCite : `fetch_missing.py` et `graph.py`.

`harvest` et `harvest_by_person` dupliquent le câblage des nœuds, la construction du client ScanR et la capture de `HarvestConfigError`.

### Recherche et écriture dans `staging`

La boucle « chercher un identifiant, écrire le résultat dans `staging` » existe en cinq copies : `common/fetch_missing.py`, `common/fetch_stale.py`, `hal/fetch_missing.py`, `theses/fetch_missing.py`, `openalex/fetch_truncated.py`. Chacune range elle-même les trois issues : trouvé, introuvable, indisponible. Les méthodes `insert` des six `DoiSearch` sont presque identiques. `oa_status.py` (Unpaywall) et `enrich_journals_from_openalex.py` ont leur propre boucle réseau.

Les identifiants d'un enregistrement source (identifiant, DOI, troncature des auteurs OpenAlex) se recalculent à chaque point d'entrée : moissonnage, recherche par DOI, recherche par personne, relecture.

### Débit, circuit-breaker et réessais

Trois mécanismes règlent le débit d'une source :

- une pause par worker après chaque requête : `request_delay_s` des `DoiSearch`, `HAL_DELAY`, `THESES_DELAY` ;
- le `Throttle` synchrone de WoS ;
- `RequestPace`, un rythme commun à tous les workers, employé par le Sudoc seulement.

Avec une pause par worker, le débit dépend du temps de réponse. Les réglages de WoS sont répétés dans `wos/fetch_missing.py` et `wos/fetch_stale.py`.

Le circuit-breaker circule par deux canaux. `access_source` le pose dans une ContextVar, que lisent les clients HTTP et `run_fetch_pool`. L'exécuteur des nœuds le passe aussi en argument, jusqu'aux callbacks `breaker_tripped=` des moissonneurs.

`http_retry.py` contient deux copies de la boucle de réessai, synchrone et asynchrone. À l'épuisement des réessais, la synchrone lève `SourceUnavailableError`, l'asynchrone l'erreur d'origine.

### Normalisation

`SourceNormalizer` fait la boucle de la normalisation. Chaque source réécrit la séquence d'écriture : conteneurs, métadonnées, enregistrement source, contributions sources, `mark_done`.

## Décisions

- Chaque source expose un adaptateur dans `<source>/__init__.py` : client, extracteurs, recherche par DOI, relecture, normaliseur, empreinte, identité d'une notice, budget de débit, politiques.
- Les tables des phases et les nœuds du graphe se construisent depuis la liste des adaptateurs.
- Une boucle de recherche commune range les trois issues. Les cinq canaux la paramètrent. L'adaptateur lui fournit l'identité d'une notice.
- Le débit de chaque source est un budget en requêtes par seconde, appliqué par `RequestPace` dans la boucle commune.
- La ContextVar est le seul canal du circuit-breaker. Toute requête s'exécute sous le breaker d'une source.
- Une fonction sans I/O classe chaque tentative. Deux enveloppes, synchrone et asynchrone, l'exécutent. L'épuisement des réessais lève `SourceUnavailableError`, quelle qu'en soit la cause.
- La classe de base de la normalisation fait la séquence d'écriture. Une source fournit l'analyse d'une ligne de `staging`.
- La phase 7 se coordonne avec le chantier [Normalisation par lots](CODE_batch-normalize.md), qui réécrit le writer des contributions sources.

## Phasage

### Phase 1 — Circuit-breaker

- [x] Paramètre `breaker` retiré des nœuds et des callbacks des moissonneurs. b9b9aa2cc

### Phase 2 — Réessais

- [ ] Classement des tentatives et ses deux enveloppes, avec une seule issue à l'épuisement.
- [ ] Scripts hors pipeline sous le breaker de leur source.

### Phase 3 — Adaptateur et registre

- [ ] Protocole de l'adaptateur, implémenté pour les sept sources.
- [ ] Tables des phases et réglages construits depuis les adaptateurs.
- [ ] `PERSON_SEARCHED_SOURCES` et les agences d'enregistrement tirés des adaptateurs.
- [ ] Test : chaque source du registre a un adaptateur complet.

### Phase 4 — Boucle de recherche commune et écriture dans `staging`

- [ ] Débit réel de chaque source mesuré sur un run, avant la boucle commune.
- [ ] Identifiants d'un enregistrement source fournis par l'adaptateur à tous les points d'entrée.
- [ ] Boucle commune et écriture des trois issues, pour les cinq canaux, effacement des échecs compris.
- [ ] `upsert_staging` dans `StagingStore`, qui reçoit sa connexion à la construction.

### Phase 5 — Débit

- [ ] Budget de débit de chaque source dans son adaptateur.
- [ ] `RequestPace` à la place des pauses par worker et du `Throttle`.
- [ ] Débit réel de chaque source mesuré sur un run, comparé à la mesure de la phase 4.

### Phase 6 — Politiques de source

- [ ] Attributs de l'adaptateur à la place des littéraux des orchestrateurs.
- [ ] Câblage commun de `harvest` et de `harvest_by_person`.

### Phase 7 — Normalisation

- [ ] Séquence d'écriture dans la classe de base.

### Phase 8 — Documentation

- [ ] Mise à jour de `docs/sources` et de `docs/pipeline`.

## Questions ouvertes

- Libellés des sources dans le frontend : servis par l'API, ou copiés sous un test de concordance.
- Budget de débit des sources sans seuil publié : HAL, theses.fr, ScanR.
