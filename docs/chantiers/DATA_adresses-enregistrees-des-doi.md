# Chantier — Adresses enregistrées des DOI

## Contexte

`source_record_locations` range les copies par enregistrement source. `publication_copies` rend les copies d'une publication aux règles d'accès et de statut. Une copie d'ouverture inconnue compte comme une information : elle classe `closed` une publication sans copie ouverte.

**Adresse enregistrée d'un DOI.** Crossref la donne dans `resource.primary.URL`, DataCite dans `attributes.url`. Sur un échantillon de 15 DOI, elle est identique à celle de l'API des handles de doi.org. Crossref l'écrit comme localisation, d'ouverture inconnue. Les DOI des autres agences (mEDRA, KISTI, JaLC, Office des publications…) sont sans localisation éditeur.

**Adresse enregistrée qui désigne un PDF.** 136 adresses Crossref finissent par `.pdf`. Parmi les DOI du périmètre des autres agences, 11 aussi, dont 6 de publications `closed` ou `unknown`. Exemple : la publication 78490, DOI KISTI, est `closed` alors que son DOI mène à un PDF (`http://isyou.info/jowua/papers/jowua-v12n1-6.pdf`). 9 DOI du périmètre sont inconnus de doi.org.

**Publications du périmètre à DOI en `unknown`** : DataCite 317 sur 4 909, mEDRA 7, KISTI 3, Public 1. Les DOI DataCite sont absents d'Unpaywall.

## Décisions

- Une table `sources.dois` remplace `unpaywall`. Elle a une ligne par DOI de publication, avec les réponses des services externes : verdict d'Unpaywall et sa date, adresse enregistrée chez doi.org et sa date.
- La phase `oa_status` lit l'adresse enregistrée de chaque DOI dans l'API des handles de doi.org, toutes agences comprises. Aucun site d'éditeur n'est interrogé. Un DOI inconnu de doi.org reçoit une adresse nulle et datée, comme un DOI absent d'Unpaywall.
- Une adresse enregistrée dont le chemin finit par `.pdf` donne une copie ouverte de la publication, en version de l'éditeur, sans licence. Les autres adresses enregistrées donnent seulement une ligne de `sources.dois`.

## Phasage

### Phase 1 — Schéma

- [x] Migration : `sources.dois`, reprise des verdicts de `unpaywall`, suppression de `unpaywall` (8d7c2c4c0).
- [x] `tables.py`, snapshot du schéma, lectures et écritures déclarées du graphe (8d7c2c4c0).
- [x] Lecteurs de `unpaywall` basculés : phase `oa_status`, consolidation, scripts (8d7c2c4c0).

### Phase 2 — Résolution

- [x] Tâche de la phase `oa_status` : DOI jamais résolus ou périmés, délai et plafond par run réglables comme pour Unpaywall. Recalcul du statut des publications des DOI résolus (6d397fed7).

### Phase 3 — Copies

- [x] `publication_copies` : copie ouverte tirée d'une adresse enregistrée qui désigne un PDF.

### Phase 4 — Documentation

- [x] `docs/donnees/02-sources.md`, index des tables, fiches des sources, documentation de la phase `oa_status`.

## Questions ouvertes

- DOI DataCite en `unknown` : les enregistrements sources DataCite sont sans localisation. Le normaliseur DataCite pourrait écrire l'adresse enregistrée, avec l'ouverture tirée de `rightsList`, déjà lu pour la licence.
