# Chantier — Preprints et versions d'une publication

## Contexte

Un preprint à DOI forme une publication distincte, reliée à sa version publiée par `is_preprint_of`. Une copie de repository rejoint la version publiée qu'elle déclare. Un preprint reste à part, même quand il se déclare version de l'article.

OpenAlex et ScanR suivent un autre modèle : un work réunit le preprint et l'article, le preprint y est une localisation `submittedVersion`. Les localisations OpenAlex (`source_record_locations`) suivent ce modèle : la copie arXiv figure parmi les localisations de l'article, alors que l'enregistrement source DataCite arXiv forme sa propre publication. Les identifiants OpenAlex le suivent aussi : le work de l'article contient en `secondary` le `hal_id` du dépôt HAL du preprint. Un enregistrement source preprint sans DOI rejoint ainsi la publication de l'article par une clé partagée.

La réconciliation coupe une composante par ancres, les DOI `primary` et `derived` : deux ancres distinctes désignent deux œuvres (`domain/publications/reconciliation.py`). Le DOI d'une forme secondaire (version Zenodo, pièce d'un jeu de données, DOI à suffixe de version) a une cible dans `doi_targets`, que la réconciliation lit à la place du DOI. Les formes d'une œuvre rejoignent ainsi sa publication. L'enregistrement source DataCite d'une forme secondaire est écarté de la réconciliation quand sa cible est le DOI `primary` d'un autre enregistrement source.

La phase `relations` reconstruit `publication_relations` à chaque run. Elle suit `finalize`, qui calcule le périmètre et les compteurs. L'option `--no-extras` l'omet.

Le volet Accès de la fiche d'une publication classe ses copies ouvertes par version (éditeur, acceptée, soumise, inconnue), puis par ordre d'arrivée. Les localisations HAL et DataCite sont sans version : une localisation OpenAlex arXiv en `submittedVersion` passe devant le dépôt HAL. La phase `publications` calcule l'adresse d'accès (`best_copy_url`) et le statut open access d'une publication recalculée, sur les copies de ses enregistrements sources.

### Typologie du 2026-11-01, base locale

Le type d'une publication vient du premier enregistrement source typé, dans l'ordre de priorité des sources (theses.fr, Crossref, DataCite, HAL, OpenAlex, ScanR, WoS), puis dans l'ordre d'arrivée.

**Clés de réunion.** Un work OpenAlex ou un enregistrement source ScanR cite en `secondary` les `hal_id` de plusieurs dépôts HAL : preprint, article, communication, poster. La clé de confirmation d'un type d'identifiant est l'identifiant de rôle le plus fort, puis de plus petite valeur : entre plusieurs dépôts, le numéro décide. OpenAlex type aussi `preprint` des works de dépôts HAL d'articles. Le bloc de métadonnées (type, titre, année) relie alors un tel work à l'enregistrement source DataCite arXiv (3059).

**Publications qui contiennent un enregistrement source preprint et un enregistrement source d'un type publié.** L'ancre est le DOI de la publication, jugé sur les enregistrements sources Crossref, DataCite, HAL et theses.fr dont il est le DOI propre.

| Ancre | Publications | Enregistrements sources réunis | Type retenu | Exemples |
|---|---|---|---|---|
| DOI de la version publiée | 644 | dépôt HAL preprint sans DOI (209), qui cite le DOI (31) ; work OpenAlex typé preprint : arXiv (182), dépôt HAL (114), qui cite le DOI (87), au DOI de la publication (29) | publié, sauf 19474 | 1800, 373, 292, 25884 |
| DOI du preprint, type publié donné par OpenAlex ou ScanR seuls | 200 | work OpenAlex typé article : arXiv, Zenodo, discussions Copernicus, DESY | preprint | 9524, 184561, 312726 |
| DOI du preprint, dépôt HAL d'un type publié | 142 | article (72), communication (62), chapitre (6), data paper | preprint | 3059, 299298, 2658 |
| Sans DOI | 144 | dépôt HAL d'un type publié, work OpenAlex du dépôt typé preprint | type HAL | 26982, 3060 |

Dépôts HAL d'un type publié réunis au DOI d'un preprint :

- 45 articles sans aucun DOI, tous avec revue. 14 sont reliés par `is_preprint_of` à une version publiée distincte.
- 27 articles qui citent le DOI du preprint (2934 : article de Nature Communications déposé avec le DOI bioRxiv).
- 57 communications sans aucun DOI, aucune avec revue ou recueil. 12 sont reliées.

16 publications typées version publiée sont dans le périmètre par leurs seuls enregistrements sources preprint.

**Autres cas.**

- Revue d'un preprint : 149 discussion papers (Copernicus) prennent la revue de l'article par l'espace de noms DOI (`SERIAL_BY_DOI_NAMESPACE`) ; 70 preprints prennent celle d'un dépôt HAL d'article réuni.
- Working papers typés `other` : le type `other` de DataCite passe devant le type `preprint` de HAL. 87 publications, dont 72 à DOI OSF (`10.17605`) (14691, 255632).
- Œuvres distinctes réunies : 496 publications typées communication ont un enregistrement source Crossref `article` et un dépôt HAL communication, dont 154 avec plusieurs dépôts HAL. 620 réunit un article de revue et une communication de 2021 par les `hal_id` secondaires de ScanR : le sous-type de la communication l'emporte sur `article`.

**Liens `is_preprint_of`** (relations du 2026-10-31) : 1 724 vers une publication du corpus. 63 viennent de preprints à plusieurs cibles. 78 visent un type non publié, 81 une publication sans DOI vue par HAL, 13 une publication sans DOI vue par le seul WoS (165044 vers 301756, doublon de l'article). 15 relient un preprint du périmètre à une cible hors périmètre. 48 partent d'un preprint qui contient un dépôt HAL d'un type publié.

### Mesures du 2026-10-30

- 2 298 des 3 935 enregistrements sources DataCite arXiv sont typés `article`, d'après leur type d'origine. Aucun n'est écarté de la réconciliation.
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

### Mesure du 2026-11-01 : preprint du périmètre, version publiée hors périmètre

49 paires `is_preprint_of` relient un preprint du périmètre à une version publiée hors périmètre. Classement d'après les adresses des personnes du périmètre du preprint :

- 23 : le preprint entre dans le périmètre par un ROR donné par OpenAlex sans adresse, surtout celui du Laboratoire de Mathématiques Blaise Pascal. Les adresses de ces auteurs désignent d'autres laboratoires de mathématiques.
- 11 : la cible est un enregistrement ScanR seul.
- 8 : ces personnes ont une adresse du périmètre sur le preprint, une autre adresse sur la cible.
- 7 : ces personnes ont une adresse du périmètre sur le preprint, aucune adresse sur la cible.

## Décisions

- **Un preprint relié à sa version publiée est masqué.** Il reste une publication, avec son DOI, son type et sa date. Il est absent des listes, des statistiques, des compteurs et des bibliographies. Ses copies figurent dans le volet Accès de la version publiée. La réconciliation garde un DOI par publication, et une fausse paire se corrige par le retrait du lien.
- **Le masquage se lit dans le lien `is_preprint_of`.** Toutes les vues filtrent les preprints masqués par une même jointure sur `publication_relations`.
- **Le lien est vérifié à sa création.** La phase `relations` relie un preprint à une seule version publiée, sous la garde des auteurs. Une communication orale, un poster, une thèse, un jeu de données, un logiciel ou un `other` reste une œuvre liée par une autre relation.
- **`relations` précède `finalize`**, hors des enrichissements : le masquage pèse sur le périmètre et les compteurs.
- **Le statut open access de la version publiée tient compte des copies de son preprint masqué.** Pour 73 paires, la version publiée est fermée et le preprint ouvert.
- **Les copies d'un preprint figurent avec la mention *preprint* dans le volet Accès.** Elles passent après les autres copies ouvertes : un preprint donne l'accès principal seulement s'il est la seule copie ouverte.

## Phasage

### Phase 1 — Mesures

- [x] Preprints du périmètre dont la version publiée est hors périmètre
- [x] Typologie des publications qui réunissent un preprint et sa version publiée
- [ ] Fiabilité du type des dépôts HAL d'un type publié réunis à un preprint, sur échantillon (2658 : contribution Snowmass typée communication)

### Phase 2 — Réunion et type des preprints

- [x] Type `preprint` d'après le préfixe DOI du serveur de preprints, pour un enregistrement source sans revue (67c1b73ef)
- [x] Enregistrements sources lus dans l'ordre d'arrivée pour l'agrégation (c1b6d7615)
- [ ] Dépôts HAL réunis à une œuvre d'une autre nature : preprint et version publiée

### Phase 3 — Création du lien

- [ ] Signaux qui créent le lien : relation déclarée, clé partagée, titre, selon leur fiabilité mesurée
- [ ] Garde sur les auteurs : la quasi-totalité des auteurs du preprint se retrouve dans la version publiée, comparés par personnes alignées
- [ ] Cible unique, d'après les 27 preprints à plusieurs cibles

### Phase 4 — Masquage

- [ ] `relations` avant `finalize`
- [ ] Preprints masqués filtrés dans toutes les vues : listes, facettes, statistiques, compteurs, bibliographies, exports
- [ ] Adresse d'accès et statut open access calculés après `relations`, sur les copies de la publication et de ses preprints masqués

### Phase 5 — Lien des preprints sans cible

- [ ] Lien par titre proche, au sein des publications d'une même personne, sous la garde des auteurs. 284 preprints candidats.

### Phase 6 — Affichage

- [ ] Volet Accès de la version publiée : copies de ses preprints après les autres copies, avec la mention *preprint*

### Phase 7 — Fin de chantier

- [ ] Mise à jour de la documentation

## Questions ouvertes

- **Dépôts HAL réunis à une œuvre d'une autre nature.** Les `hal_id` secondaires d'OpenAlex et de ScanR réunissent un dépôt HAL preprint sans DOI à l'article (209 publications), un dépôt HAL d'article ou de communication au preprint arXiv (142), une communication à l'article (620). Deux voies :
  - scinder : le dépôt forme sa propre publication, reliée puis masquée. Un preprint sans DOI forme alors aussi une publication distincte.
  - typer : la publication prend le type de la version publiée, avec le DOI du preprint. Une communication sans revue ni recueil (57) garde un type incertain.
- **Version publiée hors périmètre** (49 paires ; 15 en base locale) : le masquage sort l'œuvre du périmètre. Deux voies : le preprint reste visible ; ou la version publiée entre dans le périmètre par ses preprints masqués, comme par un enregistrement source preprint réuni (16 publications). La seconde voie pose la question des laboratoires des preprints masqués.
- **Revue d'un preprint.** La revue de l'article, donnée par l'espace de noms DOI, compte 149 discussion papers parmi ses publications.
- **Working papers typés `other`** (87) : le type `preprint` de HAL devant le type `other` de DataCite ?
- **Portée de la mention *preprint*.** Une copie arXiv vient du preprint masqué (DataCite, sans version) ou des localisations OpenAlex de l'article (`submittedVersion`). Une plateforme garde une seule copie : la mention dépend alors du chemin. Piste : la mention vaut pour la copie d'un enregistrement source preprint, et pour toute copie hébergée par un serveur de preprints.
- **Fiabilité de la version déclarée.** La version des localisations d'entrepôt est peu fiable chez OpenAlex comme chez Unpaywall : 200 949 localisations d'entrepôt sur 258 875 sont en `submittedVersion`, y compris dans Cairn, qui héberge des versions publiées.
- **Cible antérieure au preprint** (29 paires) : repost tardif ou fausse paire ?
- **Rejet d'un lien par l'administration**, pour une fausse paire passée à travers la garde des auteurs.
- **Doublons hors preprints.** Copies de repository (Apollo), articles à deux DOI, revues qui changent de préfixe DOI, articles vus par le seul WoS sans DOI (301756) : chaque copie ou double DOI forme une publication de plus.
