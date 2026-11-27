# Chantier — Identifiants d'une autre œuvre

## Contexte

Un enregistrement source cite souvent l'identifiant d'une autre source : un identifiant HAL chez OpenAlex ou ScanR, un DOI chez HAL. L'émetteur de l'identifiant est l'enregistrement source de la source qui l'attribue : HAL pour un identifiant HAL, theses.fr pour un NNT, Crossref ou DataCite pour un DOI. Quand l'identifiant désigne une autre œuvre, la réconciliation fusionne deux œuvres distinctes. Exemples :

- 116411 : le dépôt HAL d'un chapitre cite le DOI Zenodo d'une version du livre qui le contient. La règle de la forme secondaire DataCite prime sur la vérification ouvrage/chapitre : le chapitre garde le DOI, et rejoint le livre. C'est le seul cas parmi les 8 003 DOI à cible.
- 10708 : deux dépôts HAL distincts, une communication et un poster, citent le DOI d'une session de posters d'une revue. Ils sont réunis avec l'enregistrement Crossref de la session.

Règles en place :

- `DOI_D_UNE_AUTRE_OEUVRE` retire un DOI d'un enregistrement source sans nom d'auteur commun avec l'enregistrement Crossref du DOI, et de titre éloigné du sien (`distant_titles` : moins de 35 % de mots communs). Un enregistrement Crossref sans auteur individuel reste hors de la comparaison.
- Les règles de conteneur (ouvrage et chapitre, actes et communication, numéro et article, avis et article) reconnaissent le conteneur à son type de document.
- Aucune règle ne confronte un identifiant HAL ou un NNT à son émetteur.

### Mesures du 2026-11-27

Scripts dans `data/experiments/identifiants-autre-oeuvre/`. Paires classées dans `paires.csv`.

Identifiants actifs d'un enregistrement source, hors rôle `related`, face à leur émetteur (`paires_titres_eloignes.py`) :

| Identifiant, source de l'enregistrement source | Paires | Titres éloignés |
|---|---|---|
| DOI, OpenAlex | 66 644 | 1 175 |
| Identifiant HAL, ScanR | 62 381 | 388 |
| Identifiant HAL, OpenAlex | 62 159 | 683 |
| DOI, ScanR | 41 082 | 210 |
| DOI, HAL | 34 974 | 435 |
| DOI, WoS | 24 289 | 914 |
| NNT, OpenAlex | 3 736 | 779 |
| DOI, theses.fr | 3 066 | 276 |
| NNT, HAL | 2 822 | 273 |

- Les titres éloignés de WoS et des thèses sont surtout des traductions. WoS donne un titre anglais. Une thèse a un titre français et un titre anglais.
- 289 des 3 000 dépôts HAL d'un échantillon de payloads bruts ont plusieurs titres (`title_s`), le plus souvent l'original et sa traduction. La normalisation garde le premier. Ces titres secondaires expliquent environ 40 % des titres éloignés d'une paire avec un dépôt HAL : OpenAlex et ScanR reprennent le titre secondaire.
- La condition « aucun auteur commun » écarte la plupart des traductions, mais aussi des erreurs : le chapitre de 116411 a un auteur commun avec le livre.

Paires d'une même publication avec un dépôt HAL, aux titres éloignés de tous les titres du dépôt, par pagination du dépôt face à l'autre enregistrement source :

| Pagination | Paires | Contenu |
|---|---|---|
| Même première page | 218 | Surtout la même œuvre : chapitre ou article Cairn titré du nom de sa partie ou de sa rubrique chez Crossref ; traduction absente des titres HAL |
| Dépôt HAL compris dans l'autre | 27 | Conteneurs : rubrique de comptes rendus, partie d'ouvrage |
| Paginations disjointes | 23 | Œuvres distinctes : chapitre « Introduction » cité avec les identifiants HAL d'autres chapitres |
| Pagination absente | 446 | Indéterminé ; les enregistrements ScanR sont sans pagination |
| Titre Crossref réduit au DOI | 7 | Même œuvre |

- Les DOI Cairn sont au moins 45 des 218 paires de même première page.
- Un conteneur typé comme son contenu échappe aux règles de conteneur : rubrique ou session typée article par Crossref, partie d'ouvrage typée chapitre.
- 32 enregistrements sources OpenAlex ou ScanR contiennent les identifiants de plusieurs dépôts HAL aux titres éloignés du leur, pour 73 dépôts. Le plus gros réunit 7 dépôts.

## Décisions

- WoS est hors du chantier : l'abonnement prend fin.
- Les thèses ont une règle propre.

## Phasage

### Phase 1 — Mesures complémentaires

- [ ] Pagination des paires ScanR : celle de l'enregistrement Crossref du même DOI.
- [ ] Revue d'un échantillon par classe de pagination.
- [ ] DOI cités par OpenAlex : 139 paires d'une même publication, surtout des DOI de fichiers d'un jeu de données DataCite.
- [ ] Rubriques Cairn de comptes rendus de même première page que leur premier compte rendu.

### Phase 2 — Titres secondaires

- [ ] Stockage des titres secondaires des dépôts HAL (`title_s`) et des thèses.

### Phase 3 — Règles

- [ ] Identifiant d'une autre œuvre : identifiant HAL, DOI Crossref ou DataCite, face à l'émetteur. Signaux : titres éloignés de tous les titres de l'émetteur, pagination comprise dans celle de l'autre ou disjointe.
- [ ] Thèses.
- [ ] Titre Crossref réduit au DOI, hors comparaison.
- [ ] Forme secondaire DataCite : vérification ouvrage/chapitre (116411).
- [ ] Effet sur le stock : publications scindées, revue d'un échantillon.

### Phase 4 — Documentation

- [ ] Mise à jour de la documentation : correction des métadonnées, réconciliation.

## Questions ouvertes

- Mesure de la distance des titres : part de mots communs (`distant_titles`) ou distance de Jaro-Winkler.
- Contenu d'une rubrique ou d'une session : son seul DOI est celui du conteneur.
