# Chantier — Preprints et versions d'une publication

## Contexte

Un preprint forme une publication distincte, reliée à sa version publiée par `is_preprint_of`. Une version converge avec l'article seulement sous un même préfixe DOI : une copie déposée de la version publiée rejoint l'article, un preprint arXiv reste à part.

OpenAlex et ScanR suivent un autre modèle : un work réunit le preprint et l'article, le preprint y est une localisation `submittedVersion`. Les localisations OpenAlex (`source_record_locations`) suivent ce modèle : la copie arXiv figure parmi les localisations de l'article, alors que l'enregistrement DataCite arXiv forme sa propre publication.

La convergence interdit de réunir deux DOI distincts (cannot-link DOI, `domain/publications/reconciliation.py`). Elle porte sur le DOI effectif : `metadata_correction` remplace déjà le DOI d'une forme secondaire (version Zenodo, pièce d'un jeu de données) par celui de l'œuvre. L'agrégation passe alors ces enregistrements sources en fin de priorité (`secondary_ids`), et la fiche publication les replie sous « sources secondaires ».

### Mesures du 2026-10-25

- 2 352 des 4 357 enregistrements DataCite arXiv sont typés `article`, d'après leur type brut. Les espaces de noms DOI excluent les serveurs de preprints du rattachement de revue.
- Sur 6 080 localisations arXiv en `submittedVersion` d'une publication autre qu'un preprint, 5 051 désignent un preprint qui n'a pas de publication propre.
- 189 paires de publications partagent un identifiant arXiv sans être typées preprint. Des copies d'entrepôt restent séparées de leur article (Apollo `10.17863`, DESY `10.3204`), et des identifiants arXiv sont attribués à tort.

### Mesures du 2026-10-27

**Paires reliées.** 1 570 paires `is_preprint_of` relient 1 540 preprints à 1 523 publications. Chaque paire vient d'un seul signal :

| Signal | Paires | Titre normalisé identique | Titre très différent (similarité < 0,5) |
|---|---|---|---|
| Relation déclarée par Crossref | 554 | 346 | 31 |
| Clé partagée (arXiv, HAL, PMID) | 551 | 436 | 12 |
| Titre identique | 442 | 442 | 0 |
| Relation déclarée par DataCite | 23 | 16 | 1 |

Le titre change souvent entre preprint et article : les titres différents d'une relation Crossref sont plausibles. Ceux d'une clé partagée sont suspects, certains sans rapport entre eux.

**Type de la cible.** 1 495 paires relient le preprint à une version publiée (article, communication publiée, synthèse, chapitre, lettre, éditorial, data paper, ouvrage). 75 le relient à une œuvre liée : communication orale (50), `other` (14), poster, rapport, thèse, jeu de données, logiciel. 28 preprints ont plusieurs cibles, en général un article et une communication orale ou un poster. 37 articles ont plusieurs preprints, en général une copie HAL et une copie arXiv.

**Auteurs.** Comparaison des noms de famille normalisés, toutes sources confondues :

- tous les auteurs du preprint se retrouvent dans la cible pour 1 405 paires (89,5 %) ;
- au plus 20 % des auteurs du preprint manquent pour 121 paires, surtout par des écarts de forme du nom (« Nom Prénom ») ;
- plus de 20 % manquent pour 44 paires, parmi lesquelles les fausses paires : jeu de données, thèse, communication d'une grande collaboration, titres sans rapport.

**Année.** Écart entre l'année de la cible et celle du preprint : 0 an (770 paires), 1 an (624), 2 ans (108), 3 ans ou plus (40). La cible précède le preprint dans 28 paires.

**Accès.** Pour 68 paires, la cible est fermée et le preprint ouvert.

**Preprints sans cible.** La base compte 3 360 preprints, dont 3 303 dans le périmètre. 1 793 preprints du périmètre n'ont pas de version publiée reliée. 284 d'entre eux ont, chez une même personne résolue, une publication de titre proche (similarité ≥ 0,8), publiée entre l'année précédente et les trois années suivantes ; 117 à plus de 0,95. Le meilleur candidat est un article pour 206 d'entre eux. Le rapprochement par titre exige l'égalité des titres normalisés et un candidat unique : il manque ces paires. Des titres proches désignent aussi des œuvres distinctes : deux analyses d'amplitude de désintégrations de mésons B, qui diffèrent par une particule.

**Publications à DOI arXiv.** 171 publications à DOI arXiv (`10.48550`) ont un autre type que `preprint`, dont 163 typées `article`. Environ 140 sont reliées à leur version publiée par `is_related_to` (DataCite, clé partagée) : ce sont des preprints mal typés, comptés dans la famille « Publications » en plus de leur article.

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
- [ ] Fusion par substitution du DOI du preprint, dans `metadata_correction`, par des règles rejouables depuis une base vide.

### Phase 2 — Type des preprints arXiv

- [ ] Type `preprint` d'après le préfixe DOI du serveur (liste fermée du chantier [Modèle des conteneurs](archived/2026-10-25_DATA_modele-des-conteneurs.md)). 171 publications.

### Phase 3 — Rapprochement des preprints sans cible

- [ ] Rapprochement par titre proche, au sein des publications d'une même personne, sous la garde des auteurs. 284 preprints candidats.

### Phase 4 — Affichage

- [ ] Bloc « Versions » de la fiche publication : version publiée, preprint, avec plateforme et DOI.

### Phase 5 — Statistiques

- [ ] Famille « Preprints » des statistiques réduite aux preprints sans version publiée.

## Questions ouvertes

- **Fiabilité de la version déclarée.** La version des localisations d'entrepôt est peu fiable chez OpenAlex comme chez Unpaywall : 200 949 localisations d'entrepôt sur 258 875 sont en `submittedVersion`, y compris dans Cairn, qui héberge des versions publiées.
- **Cible antérieure au preprint** (28 paires) : repost tardif ou fausse paire ?
- **Année de l'œuvre fusionnée** : celle de la version publiée. L'année change pour 800 paires.
