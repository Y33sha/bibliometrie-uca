# Chantier — Date de publication

## Contexte

Les enregistrements sources et les publications ont seulement une année (`publication_year`). Toutes les sources donnent une date plus précise, avec une précision variable :

| Source | Champ | Forme |
|---|---|---|
| HAL | `publicationDate_s` | année, mois ou jour |
| OpenAlex | `publication_date` | jour |
| Crossref | `issued` | année, mois ou jour ; `published-online` et `published-print` à part |
| DataCite | `dates` de type `Issued` | année ou jour ; `publicationYear` à défaut |
| ScanR | `publicationDate` | horodatage |
| WoS | `pub_info.coverdate` (« OCT 2024 »), `sortdate` (jour reconstitué), `early_access_date` | mois ou jour |
| theses.fr | `dateSoutenance` | jour |

### Mesures du 2026-10-28

Échantillon de 1 000 payloads du raw store par source.

- HAL : jour 56 %, année 31 %, mois 13 %.
- Crossref (`issued`) : jour 50 %, mois 26 %, année 24 %.
- DataCite : année 59 %, jour 22 %, aucune date `Issued` 17 %.
- OpenAlex : toujours un jour, le 1er janvier dans 23 % des cas.
- ScanR : toujours un jour, le 1er janvier dans 7 % des cas.
- HAL et Crossref donnent le 1er janvier dans moins de 1 % des cas. Le 1er janvier d'OpenAlex et de ScanR est donc probablement un bouche-trou pour une année seule.
- WoS : la forme des payloads varie, la mesure reste à refaire.

## Décisions

## Phasage

### Phase 1 — Mesures

- [ ] Dates d'OpenAlex et de ScanR au 1er janvier, confrontées aux autres sources d'une même publication.
- [ ] Écarts de date entre les sources d'une même publication. Crossref : date en ligne et date papier.
- [ ] Champs de date de WoS.

### Phase 2 — Schéma

- [ ] Date et précision (année, mois, jour) sur les enregistrements sources et sur les publications.

### Phase 3 — Normalisation

- [ ] Date de chaque source, avec sa précision. Jours fictifs ramenés à l'année.
- [ ] Remise en conformité du stock depuis le raw store.

### Phase 4 — Date de la publication

- [ ] Arbitrage entre les dates des enregistrements sources.

### Phase 5 — Usages

- [ ] Affichage de la date sur la fiche publication et dans les exports.

### Phase 6 — Documentation

- [ ] Mise à jour de la documentation.

## Questions ouvertes

- Date d'une publication : la plus ancienne, la plus précise, celle de la source prioritaire ; date en ligne ou date papier.
- `publication_year` : colonne gardée, ou déduite de la date.
- Date d'une thèse : date de soutenance.
