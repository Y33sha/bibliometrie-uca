# Chantier — Financements

## Contexte

Le modèle de données ne décrit pas les financements des publications. `SourceExtra.FUNDER` est déclaré sans être écrit.

Le modèle CERIF Core d'euroCRIS sépare trois notions :

- le financeur, une organisation (Organisation Unit), identifiée par son ROR ou son DOI du Funder Registry de Crossref ;
- le financement (Funding), une ressource fournie par un financeur, qui couvre des activités et des projets ;
- la déclaration (Acknowledgement Statement), qui atteste le lien entre un financement et une contribution.

Transposé ici, une publication déclare des financeurs, avec ou sans numéro de financement. Le numéro identifie un financement chez son financeur : code ANR, numéro de convention européenne. Aucune source ne donne de montant.

## Données des sources

| Source | Données | Identifiant du financeur | Moissonnage |
|---|---|---|---|
| HAL | Projets ANR et européens des référentiels HAL : code, acronyme, titre, programme, année. Texte libre `funding_s` | Référentiel HAL | Champs absents de la liste demandée |
| OpenAlex | `funders` ; `awards` : numéro, financeur, titre pour 38 % | Identifiant OpenAlex, ROR pour 93 % des mentions | Champs absents de `select` |
| Crossref | `funder` : nom, numéros | DOI du Funder Registry pour 77 % des mentions | Moissonné, non lu |
| DataCite | `fundingReferences` : financeur, numéro, titre | DOI du Funder Registry ou ROR, parfois | Moissonné, non lu |
| WoS | Export tabulé : `FU` (financeur et numéros), `FP` (nom normalisé par WoS), `FX` (texte). API : `fund_ack` | Nom seul | Moissonné, non lu |
| ScanR | `projects` : projets du référentiel ScanR (ANR, PIA, Horizon 2020). Remerciements structurés : financeurs, programmes, numéros, infrastructures | Wikidata | Moissonné, non lu |

theses.fr et INSPIRE-HEP ne donnent aucun financement.

## Mesures du 2026-11-17

Échantillon : 4 000 publications du périmètre, de 2017 à 2026, tirées au hasard. HAL et OpenAlex sont interrogés par leur API, les autres sources lues dans les fichiers bruts.

| Source | Publications décrites | Avec financeur | Avec numéro | Avec code ANR | Avec numéro européen |
|---|---|---|---|---|---|
| OpenAlex | 3 650 | 967 (26 %) | 663 (18 %) | 336 (9 %) | 117 |
| ScanR | 3 469 | 153 (4 %) | 426 (12 %) | 365 (11 %) | 36 |
| HAL | 3 072 | 584 (19 %) | 375 (12 %) | 349 (11 %) | 50 |
| Crossref | 2 242 | 575 (26 %) | 333 (15 %) | 98 (4 %) | 49 |
| WoS | 1 386 | 781 (56 %) | 466 (34 %) | 165 (12 %) | 94 |
| DataCite | 388 | 29 (7 %) | 24 (6 %) | 18 (5 %) | 4 |

- Toutes sources réunies, 1 317 publications (33 %) déclarent un financeur ou un numéro, 448 (11 %) un code ANR, 173 (4 %) un numéro européen. La part est stable d'une année à l'autre, de 28 à 35 %.
- Par type : 908 articles sur 1 719, 77 textes d'actes sur 241, 59 communications sur 538, 15 chapitres sur 301.
- HAL et OpenAlex réunis donnent 428 des 448 publications à code ANR, 144 des 173 à numéro européen, 1 168 des 1 317 à financement. Avec WoS : 441, 161 et 1 280. Sans ScanR : 444, 165 et 1 298.
- Les sources concordent sur les codes ANR. Entre HAL et OpenAlex, les codes d'une publication sont identiques 227 fois, inclus l'un dans l'autre 29 fois, différents une fois. Entre WoS et une autre source, ils diffèrent de 2 à 12 fois.
- Les textes libres (`funding_s`, `FX`, remerciements ScanR) ajoutent un code ANR à 3 publications.
- 316 codes ANR distincts. Les programmes d'investissement d'avenir (LABX, IDEX, EQPX, INBS) sont les seuls financements ANR de 159 des 448 publications. Le code IDEX du site figure dans 87.
- Les financeurs ont 5 244 formes brutes distinctes, dont 156 désignent l'ANR. OpenAlex nomme 1 127 financeurs à ROR distincts ; 8 de ces ROR sont dans `structures`.

## Proposition

Points à trancher avant de coder :

- **Niveau source.** Une table des financements déclarés par chaque enregistrement source : nom brut du financeur, identifiant du financeur (ROR, DOI du Funder Registry, identifiant OpenAlex, Wikidata), numéro brut.
- **Financeurs.** Un référentiel propre, sur le modèle des éditeurs : nom, identifiants, formes de nom. Peu de financeurs sont des structures : un lien facultatif vers la structure suffit pour un organisme à la fois financeur et tutelle.
- **Financements.** Un référentiel des financements identifiés : financeur, numéro normalisé, acronyme, titre, programme, année. Un code ANR se normalise en `ANR-AA-PROG-NNNN`, sans suffixe de partenaire. Un numéro européen est le numéro de la convention. Les numéros des autres financeurs restent bruts au niveau source.
- **Liens.** Publication–financeur et publication–financement, avec les sources qui les attestent. Une mention de financeur sans numéro donne seulement le lien au financeur.
- **Textes libres.** Non lus : ils n'apportent presque rien aux codes ANR.
- **Nom des tables.** `grants` désigne déjà les droits SQL (`infrastructure/db/grants.py`) : `funders` et `awards` évitent la confusion.

## Phasage

### Phase 1 — Mesure

- [x] Couverture et concordance des sources sur un échantillon du périmètre

### Phase 2 — Moissonnage et normalisation

- [ ] Ajouter les champs de projets ANR et européens à la liste HAL
- [ ] Ajouter `funders` et `awards` au `select` OpenAlex
- [ ] Normaliser les financements de HAL, OpenAlex, Crossref, DataCite, WoS (export tabulé et API) et ScanR
- [ ] Re-moissonnage complet de HAL et d'OpenAlex

### Phase 3 — Référentiels

- [ ] Financeurs : rapprochement des mentions par identifiant, puis par forme de nom
- [ ] Financements ANR et européens, titres et acronymes compris
- [ ] Évaluer les jeux de données ouverts de l'ANR et CORDIS comme référentiels des financements
- [ ] Liens des publications aux financeurs et aux financements

### Phase 4 — Lecture

- [ ] Filtres et pages, à préciser

### Phase 5 — Documentation

- [ ] Mise à jour de la documentation : données, sources, pipeline

## Hors périmètre

- Infrastructures remerciées : ScanR les extrait des remerciements, CERIF les modélise comme ressources utilisées (Resource Usage Statement).
- 513 des 3 938 œuvres OpenAlex de l'échantillon sont introuvables par leur identifiant dans l'API : œuvres fusionnées ou supprimées, à vérifier.
