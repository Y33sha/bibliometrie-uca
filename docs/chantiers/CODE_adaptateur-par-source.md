# Chantier — Une source, un adaptateur

## Contexte

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

`SourceNormalizer` fait la boucle de la normalisation. Chaque source réécrit la séquence d'écriture : conteneurs, métadonnées, enregistrement source, contributions sources, `mark_done`.

Les identifiants d'un enregistrement source (identifiant, DOI, troncature des auteurs OpenAlex) se recalcule à chaque point d'entrée : moissonnage, recherche par DOI, recherche par personne, relecture. Les méthodes `insert` des six `DoiSearch` sont presque identiques.

`harvest` et `harvest_by_person` dupliquent le câblage des nœuds, la construction du client ScanR et la capture de `HarvestConfigError`.

## Décisions

- Chaque source expose un adaptateur dans `<source>/__init__.py` : client, extracteurs, recherche par DOI, relecture, normaliseur, empreinte, identité d'une notice, politiques.
- Les tables des phases et les nœuds du graphe se construisent depuis la liste des adaptateurs.
- La classe de base de la normalisation fait la séquence d'écriture. Une source fournit l'analyse d'une ligne de `staging`.
- La phase 3 se coordonne avec le chantier [Normalisation par lots](CODE_batch-normalize.md), qui réécrit le writer des contributions sources.

## Phasage

### Phase 1 — Adaptateur et registre

- [ ] Protocole de l'adaptateur, implémenté pour les sept sources.
- [ ] Tables des phases et réglages construits depuis les adaptateurs.
- [ ] `PERSON_SEARCHED_SOURCES` et les agences d'enregistrement tirés des adaptateurs.
- [ ] Test : chaque source du registre a un adaptateur complet.

### Phase 2 — Politiques de source

- [ ] Attributs de l'adaptateur à la place des littéraux des orchestrateurs.
- [ ] Câblage commun de `harvest` et de `harvest_by_person`.

### Phase 3 — Normalisation

- [ ] Séquence d'écriture dans la classe de base.

### Phase 4 — Identité et écriture dans `staging`

- [ ] Identifiants d'un enregistrement source fournis par l'adaptateur à tous les points d'entrée.
- [ ] Écriture commune dans `staging`, effacement des échecs compris.
- [ ] `upsert_staging` dans `StagingStore`, qui reçoit sa connexion à la construction.

### Phase 5 — Documentation

- [ ] Mise à jour de `docs/sources` et de `docs/pipeline`.

## Questions ouvertes

- Libellés des sources dans le frontend : servis par l'API, ou copiés sous un test de concordance.
