# Chantier — Adresses enregistrées des DOI

## Contexte

`source_record_locations` range les copies par enregistrement source. `publication_copies` rend les copies d'une publication aux règles d'accès et de statut.

**Adresse enregistrée d'un DOI.** Crossref la donne dans `resource.primary.URL`, DataCite dans `attributes.url`. Sur un échantillon de 15 DOI, elle est identique à celle de l'API des handles de doi.org. Crossref l'écrit comme localisation, d'ouverture inconnue. Les DOI des autres agences (mEDRA, KISTI, JaLC, Office des publications…) sont sans localisation éditeur.

**Adresse enregistrée qui désigne un PDF.** 136 adresses Crossref finissent par `.pdf`. Parmi les DOI du périmètre des autres agences, 11 aussi, dont 6 de publications `closed` ou `unknown`. Exemple : la publication 78490, DOI KISTI, est `closed` alors que son DOI mène à un PDF (`http://isyou.info/jowua/papers/jowua-v12n1-6.pdf`). 9 DOI du périmètre sont inconnus de doi.org.

**Publications du périmètre à DOI en `unknown`** : DataCite 317 sur 4 909, mEDRA 7, KISTI 3, Public 1. Les DOI DataCite sont absents d'Unpaywall. Leurs 358 enregistrements DataCite ont une `rightsList` vide pour 165, une licence arXiv pour 67, une licence CC ou de logiciel libre sans niveau d'accès pour 45, un accès open access déclaré pour 6 ; 72 sont absents du raw store. 110 publications du périmètre en `unknown` ont un enregistrement DataCite d'arXiv (DOI `10.48550/arxiv.*`), sans identifiant arXiv, donc sans copie.

## Décisions

- Une table `sources.dois` remplace `unpaywall`. Elle a une ligne par DOI de publication, avec les réponses des services externes : verdict d'Unpaywall et sa date, adresse enregistrée chez doi.org et sa date.
- La phase `oa_status` lit l'adresse enregistrée de chaque DOI dans l'API des handles de doi.org, toutes agences comprises. Aucun site d'éditeur n'est interrogé. Un DOI inconnu de doi.org reçoit une adresse nulle et datée, comme un DOI absent d'Unpaywall.
- Une adresse enregistrée donne une copie ouverte de la publication, sans licence :
  - quand elle mène à arXiv, bioRxiv, medRxiv ou PubMed Central. Ces plateformes déclarent donner librement accès à tout leur contenu. La version de la copie est inconnue.
  - quand son chemin finit par `.pdf`. La copie est en version de l'éditeur.
- Seule une copie déclarée fermée compte comme information pour le statut : une copie d'ouverture inconnue laisse la publication `unknown`.
- Le normaliseur DataCite écrit seulement l'enregistrement source, sans localisation : `rightsList` déclare un niveau d'accès pour trop peu d'enregistrements.

## Phasage

### Phase 1 — Schéma

- [x] Migration : `sources.dois`, reprise des verdicts de `unpaywall`, suppression de `unpaywall` (8d7c2c4c0).
- [x] `tables.py`, snapshot du schéma, lectures et écritures déclarées du graphe (8d7c2c4c0).
- [x] Lecteurs de `unpaywall` basculés : phase `oa_status`, consolidation, scripts (8d7c2c4c0).

### Phase 2 — Résolution

- [x] Tâche de la phase `oa_status` : DOI jamais résolus ou périmés, délai et plafond par run réglables comme pour Unpaywall. Recalcul du statut des publications des DOI résolus (6d397fed7).

### Phase 3 — Copies

- [x] `publication_copies` : copie ouverte tirée d'une adresse enregistrée qui désigne un PDF (994767e00).
- [x] Plateformes en accès libre intégral dans la liste des plateformes connues, lues par la copie tirée d'une adresse enregistrée et par celle tirée d'un identifiant arXiv ou d'un PMCID (3ea277a5a).
- [x] Statut : seule une copie déclarée fermée informe (3ea277a5a).

### Phase 4 — Documentation

- [x] `docs/donnees/02-sources.md`, index des tables, fiches des sources, documentation de la phase `oa_status` (994767e00).
