# Chantier — Revues divergentes selon les sources

## Contexte

Les enregistrements d'une même publication portent parfois des revues différentes selon leur source. Des échantillons examinés sur une base qui n'a reçu ni les fusions (phase 4) ni les règles sur les livres (phase 6) du chantier [Revues](DATA_revues-issn-et-doublons.md) montrent cinq causes :

- **Doublon de revues.** Hors ISSN et titre communs, ce sont surtout des titres abrégés à la manière d'INSPIRE (`Phys.Rev.Lett.`, `Eur.Phys.J.C`, `JINST`), portés par HAL et ScanR sans ISSN ni éditeur.
- **Livre ou chapitre.** La plateforme de l'éditeur (OpenAlex, ScanR) s'oppose au titre du livre (Crossref).
- **Titre de revue parasite.** Des copies d'articles sont déposées dans des entrepôts (DESY, GSI). Le normaliseur DataCite crée une revue à partir de leur titre de conteneur, volume compris : `Physical review / D D 99(1)`.
- **Revue erronée dans une source, ou niveau de collection différent.** *SSRN Electronic Journal* (ScanR) pour un article de *Journal of Development Economics*, *Microscopy Today* (HAL) pour un article de *Microscopy*.
- **Enregistrements réunis à tort dans une publication.** *Annals of Forest Science* et *Peer Community In Forest and Wood Sciences* (HAL, sans DOI).

Quand Crossref fournit une revue, la publication prend celle-là : Crossref passe avant toutes les autres sources qui en fournissent une.

## Phasage

### 1. Mesure

- [ ] Script d'audit versionné : classement des couples (publication, revue A, revue B) par cause, échantillons.
- [ ] Mesure en production.

### 2. Titres parasites

- [ ] Origine des titres parasites, surtout `unknown` : « 22 Seiten (2023). », « 1-26 (2021). », « Journal of high energy physics 2018(7) ».
- [ ] Correction dans les normaliseurs concernés, DataCite en tête.
- [ ] Nettoyage du stock.

### 3. Doublons restants

- [ ] Règle de fusion des titres abrégés, construite sur les cas réels.

### 4. Revue erronée dans une source

- [ ] Règle construite sur les cas réels : revue de Crossref, éditeur du préfixe DOI.

### 5. Enregistrements réunis à tort

- [ ] Examen des cas relevés.

## Questions ouvertes

- Revue erronée dans une source : aligner l'enregistrement sur la revue de Crossref, avec trace dans `raw_metadata`, ou le signaler dans l'administration ?
