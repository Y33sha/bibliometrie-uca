# Chantier — Preprints et versions d'une publication

## Contexte

Un preprint forme une publication distincte, reliée à sa version publiée par `is_preprint_of`. Une copie de repository rejoint la version publiée qu'elle déclare. Un preprint reste à part, même quand il se déclare version de l'article.

OpenAlex et ScanR suivent un autre modèle : un work réunit le preprint et l'article, le preprint y est une localisation `submittedVersion`. Les localisations OpenAlex (`source_record_locations`) suivent ce modèle : la copie arXiv figure parmi les localisations de l'article, alors que l'enregistrement source DataCite arXiv forme sa propre publication.

La réconciliation coupe une composante par ancres, les DOI `primary` et `derived` : deux ancres distinctes désignent deux œuvres (`domain/publications/reconciliation.py`). Le DOI d'une forme secondaire (version Zenodo, pièce d'un jeu de données, DOI à suffixe de version) a une cible dans `doi_targets`, que la réconciliation lit à la place du DOI. Les formes d'une œuvre rejoignent ainsi sa publication. L'enregistrement source DataCite d'une forme secondaire est écarté de la réconciliation quand sa cible est le DOI `primary` d'un autre enregistrement source.

### Mesures du 2026-10-30

- 2 298 des 3 935 enregistrements sources DataCite arXiv sont typés `article`, d'après leur type d'origine. Aucun n'est écarté de la réconciliation. Les espaces de noms DOI excluent les serveurs de preprints du rattachement de revue.
- 2 802 couples publication–identifiant arXiv viennent d'une localisation arXiv en `submittedVersion` d'une publication autre qu'un preprint. Pour 2 350, le DOI arXiv est le DOI d'aucune publication.
- 81 paires de publications autres que des preprints partagent un identifiant arXiv actif.

**Paires reliées.** 1 652 paires `is_preprint_of` relient 1 624 preprints à 1 612 publications. Chaque paire vient d'un seul signal :

| Signal | Paires | Titre normalisé identique | Titre très différent (similarité < 0,5) |
|---|---|---|---|
| Relation déclarée par Crossref | 617 | 389 | 31 |
| Clé partagée (arXiv, HAL, PMID) | 547 | 439 | 9 |
| Titre identique | 461 | 461 | 0 |
| Relation déclarée par DataCite | 27 | 19 | 1 |

Le titre change souvent entre preprint et article : les titres différents d'une relation Crossref sont plausibles. Ceux d'une clé partagée sont suspects.

**Type de la cible.** 1 577 paires relient le preprint à une version publiée (article, communication publiée, synthèse, chapitre, data paper, ouvrage, éditorial, lettre). 75 le relient à une œuvre liée : communication orale (55), `other` (8), poster (6), rapport (3), thèse, jeu de données, logiciel. 27 preprints ont plusieurs cibles, et 36 cibles ont plusieurs preprints.

**Auteurs.** Comparaison des noms de famille normalisés, toutes sources confondues :

- tous les auteurs du preprint se retrouvent dans la cible pour 1 384 paires (83,8 %) ;
- au plus 20 % des auteurs du preprint manquent pour 213 paires ;
- plus de 20 % manquent pour 55 paires.

**Année.** Écart entre l'année de la cible et celle du preprint : 0 an (813 paires), 1 an (655), 2 ans (115), 3 ans ou plus (40). La cible précède le preprint dans 29 paires.

**Accès.** Pour 73 paires, la cible est fermée et le preprint ouvert.

**Preprints sans cible.** La base compte 3 500 preprints, dont 3 437 dans le périmètre. 1 851 preprints du périmètre n'ont pas de version publiée reliée. 284 d'entre eux ont, chez une même personne résolue, une publication de titre proche (similarité ≥ 0,8), publiée entre l'année précédente et les trois années suivantes ; 114 à plus de 0,95. Le meilleur candidat est un article pour 212 d'entre eux. Le rapprochement par titre exige l'égalité des titres normalisés et un candidat unique : il manque ces paires. Des titres proches désignent aussi des œuvres distinctes : deux analyses d'amplitude de désintégrations de mésons B, qui diffèrent par une particule.

**Publications à DOI arXiv.** 169 publications à DOI arXiv (`10.48550`) ont un autre type que `preprint`, dont 160 typées `article`. 143 sont reliées à une autre publication par `is_related_to` (DataCite, clé partagée) : ce sont des preprints mal typés, comptés dans la famille « Publications » en plus de leur article.

## Décisions

- **Le preprint fusionne avec sa version publiée.** Le chercheur consulte une seule œuvre dans sa bibliographie. Un preprint est une version d'une publication. OpenAlex et ScanR réunissent déjà l'article et son preprint.
- **Le type `preprint` désigne un preprint dont aucune version publiée n'est en base.** Un preprint fusionné prend le type de sa version publiée.
- **Le preprint reste visible comme version.** Sa diffusion (arXiv, HAL) a une valeur propre, surtout quand la version éditeur est fermée ; dans certaines disciplines, le preprint vaut presque l'article. La fiche le montre comme une version à part entière, distincte des formes secondaires repliées.
- **Seule une version publiée reçoit le preprint.** Une communication orale, un poster, une thèse, un jeu de données, un logiciel ou un `other` reste une œuvre liée par une relation.
- La question est distincte du modèle des conteneurs : les localisations se rangent par enregistrement source, et le type d'une plateforme vient d'une liste fermée, quel que soit le modèle retenu ici.

## Phasage

### Phase 1 — Règle de fusion

- [ ] Signaux qui autorisent la fusion : relation déclarée, clé partagée, titre, selon leur fiabilité mesurée.
- [ ] Garde sur les auteurs : la quasi-totalité des auteurs du preprint se retrouve dans la version publiée, comparés par personnes alignées plutôt que par noms bruts.
- [ ] Cible ambiguë : un preprint relié à plusieurs versions publiées.
- [ ] Fusion par une règle de `doi_targets` : le DOI du preprint a pour cible le DOI de sa version publiée.

### Phase 2 — Type des preprints arXiv

- [ ] Type `preprint` d'après le préfixe DOI du serveur (liste fermée du chantier [Modèle des conteneurs](archived/2026-10-25_DATA_modele-des-conteneurs.md)). 169 publications.

### Phase 3 — Rapprochement des preprints sans cible

- [ ] Rapprochement par titre proche, au sein des publications d'une même personne, sous la garde des auteurs. 284 preprints candidats.

### Phase 4 — Affichage

- [ ] Bloc « Versions » de la fiche publication : version publiée, preprint, avec plateforme et DOI.

### Phase 5 — Statistiques

- [ ] Famille « Preprints » des statistiques réduite aux preprints sans version publiée.

## Questions ouvertes

- **Fiabilité de la version déclarée.** La version des localisations d'entrepôt est peu fiable chez OpenAlex comme chez Unpaywall : 200 949 localisations d'entrepôt sur 258 875 sont en `submittedVersion`, y compris dans Cairn, qui héberge des versions publiées.
- **Cible antérieure au preprint** (29 paires) : repost tardif ou fausse paire ?
- **Année de l'œuvre fusionnée** : celle de la version publiée. L'année change pour 839 paires.
- **Preprint fusionné visible comme version** : `is_matchable` écarte l'enregistrement source DataCite d'une forme secondaire dont la cible est le DOI `primary` d'un autre enregistrement source. Avec une règle preprint → version publiée, l'enregistrement source DataCite arXiv serait écarté, et la fiche publication ne pourrait plus le montrer.
