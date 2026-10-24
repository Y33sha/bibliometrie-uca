# Chantier — Modèle des conteneurs

## Contexte

Le conteneur d'une publication est ce qui la publie ou l'héberge. Le schéma en donne trois représentations :

- `publishing.journals`, que référence `publications.journal_id` ;
- `publishing.monographs`, que référence `publications.monograph_id` : livres et volumes d'actes, avec ou sans ISBN, avec un `journal_id` vers leur collection ;
- `publications.container_title`, un titre libre quand aucune des deux tables ne convient.

Le chantier [Monographies](DATA_monographies.md) sépare les livres et les volumes d'actes, dans `monographs`, des séries dont ils font partie, dans `journals`.

`journals` réunit encore des choses de natures différentes. Son type (`journal_type`) vaut :

- `journal`, `book_series`, `proceedings`, `media` : des publications en série ;
- `repository`, `preprint_server`, `ebook_platform` : des localisations, qui hébergent des publications sans les publier ;
- `unknown`.

Les colonnes de `journals` décrivent une revue : présence dans le DOAJ, modèle open access, APC. Elles n'ont pas de sens pour un entrepôt. Le modèle open access (`oa_model`) a une valeur propre aux entrepôts, `repository`.

Le nom `journals` couvre ainsi des collections d'ouvrages, des serveurs de prépublications et des entrepôts de données. Il désigne mal son contenu.

### Localisations

Une publication désigne une version d'une œuvre. Un preprint forme une publication distincte, reliée à l'article par `is_preprint_of`. Une copie déposée de la version publiée rejoint la publication de l'article.

Trois sources décrivent les localisations d'un document :

- OpenAlex donne le lieu, l'URL, la version (`submittedVersion`, `acceptedVersion`, `publishedVersion`) et la licence de chaque localisation. La normalisation garde les URL, les identifiants et la licence de la localisation principale.
- Crossref donne la cible de résolution du DOI (`resource.primary.URL`) et les URL du texte intégral (`link`). La normalisation ne les lit pas.
- Unpaywall donne les localisations en open access. Le pipeline lit seulement son statut open access.

Localisations OpenAlex du raw store local : 105 586 works, 322 036 localisations.

- 97 % des localisations ont un lieu. OpenAlex range parmi les entrepôts des index (DOAJ) et des agrégateurs (Europe PMC).
- 40 % des works réunissent plusieurs versions.
- Les localisations d'entrepôt sont presque toutes en `submittedVersion` (200 949 sur 258 875), y compris dans HAL pour des articles publiés, et dans Cairn, qui héberge des versions publiées. Leur version est donc peu fiable.
- Sur 6 080 localisations arXiv en `submittedVersion` d'une publication autre qu'un preprint, 5 051 désignent un preprint qui n'a pas de publication propre.

Publications qui partagent un identifiant arXiv sans être typées preprint : 189 paires. Dans 135 paires, l'une des deux a un DOI arXiv. Les autres réunissent une communication et un article (27), un erratum ou un addendum et son article (6), un jeu de données et son article (5), deux publications de même type (16). Parmi ces dernières, des copies d'entrepôt restent séparées de leur article (Apollo `10.17863`, DESY `10.3204`), et des identifiants arXiv sont attribués à tort.

2 352 des 4 357 enregistrements DataCite arXiv sont typés `article`, d'après leur type brut. Aucun n'est rattaché à ArXiv.org, donc la correction `JOURNAL_TYPE_PREPRINT_SERVER_TO_PREPRINT` ne s'applique pas. 184 des 1 148 publications à DOI arXiv ont un autre type que `preprint`.

Test de l'API Unpaywall sur 120 DOI du périmètre, tirés au hasard :

- les 104 DOI Crossref ont une réponse, les 16 DOI DataCite aucune ;
- Unpaywall donne seulement les localisations en open access : 25 DOI n'en ont aucune ;
- une localisation comporte le type d'hébergeur (`publisher` ou `repository`), la version, la licence, l'URL de la page et du PDF, la date d'ouverture, et pour un entrepôt son institution et son identifiant (`endpoint_id`, présent sur 367 localisations d'entrepôt sur 396) ;
- les versions suivent la répartition d'OpenAlex : 330 localisations d'entrepôt sur 396 sont en `submittedVersion`, PubMed Central compris ;
- la date de publication est au jour pour 86 DOI, au 1er janvier pour 18.

### Éditeur d'une publication

Une publication a l'éditeur de sa revue : ni `publications` ni `source_records` n'ont de `publisher_id`. Quand une revue change d'éditeur, ses anciens articles passent au nouvel éditeur.

Mesure sur une base proche de la production (`measure_journal_publisher_changes`) : 42 revues ont deux éditeurs de préfixe DOI sur des périodes disjointes, pour 719 publications. 315 d'entre elles ont un éditeur de préfixe différent de celui de la revue (*animal* : Cambridge jusqu'en 2020, Elsevier ensuite). L'ISSN rattache ces publications à la même revue, donc aucun doublon de revue n'apparaît.

Trois données désignent l'éditeur d'un DOI Crossref :

- **Le titulaire du préfixe** (`doi_prefixes`) reste l'éditeur d'origine.
- **Le membre qui détient le DOI** (`member`, `publisher`) change avec la revue. Les DOI d'*animal* en 10.1017, préfixe de Cambridge, sont détenus par Elsevier. Sur les 37 250 enregistrements Crossref du raw store local, 1 519 ont un membre autre que le titulaire du préfixe, dont 1 181 hors des 42 revues. Les principaux cas : bioRxiv et medRxiv passés à openRxiv (442), Research Square à Springer (213), revues vendues (de BMJ, Springer, Cambridge et OUP à Elsevier, de Hindawi à Wiley, de Lavoisier à JLE).
- **Le domaine de résolution** désigne l'hébergeur : `agupubs.onlinelibrary.wiley.com` pour l'American Geophysical Union, `linkinghub.elsevier.com` pour l'American Dairy Science Association, `books.openedition.org` pour les presses universitaires. Il désigne parfois le propriétaire : `comptes-rendus.academie-sciences.fr`, pour les revues que Centre Mersenne héberge. Le raw store compte 1 459 domaines. 50 couvrent 82 % des enregistrements, 200 en couvrent 92 %.

Le membre Crossref est tantôt la société savante (AGU), tantôt l'éditeur commercial (OUP pour *Plant Physiology*, revue de l'ASPB), tantôt la plateforme (Centre Mersenne, OpenEdition). Sur 6 609 revues à publications Crossref, 6 446 ont un seul éditeur de préfixe. 1 995 d'entre elles ont un autre éditeur en base, pour 6 045 publications. Dans 1 818 de ces cas, l'éditeur de la revue n'a aucun membre Crossref.

### Inventaire

Mesure du 2026-10-24, sur une base proche de la production :

| `journal_type` | Entrées | Avec ISSN | Publications | Monographies rattachées |
|---|---|---|---|---|
| `journal` | 9 663 | 9 355 | 37 732 | 168 |
| `unknown` | 778 | 446 | 2 277 | 4 |
| `book_series` | 250 | 240 | 870 | 540 |
| `proceedings` | 180 | 96 | 1 147 | 760 |
| `media` | 44 | 33 | 633 | 0 |
| `ebook_platform` | 39 | 1 | 68 | 1 |
| `preprint_server` | 4 | 2 | 242 | 0 |
| `repository` | 3 | 1 | 175 | 0 |

- **Localisations.** Elles comptent peu d'entrées, car deux normaliseurs les écartent. OpenAlex ne cherche aucune revue quand la localisation principale est un entrepôt, HAL, theses.fr ou une plateforme d'ebooks (`should_skip_publisher_journal`). DataCite garde seulement les conteneurs qui désignent une revue (`container_names_a_journal`). Restent SSRN (172 publications), bioRxiv (205), Research Square (trois entrées, dont une `unknown` de 87 publications), medRxiv et ChemRxiv (`unknown`), Preprints.org, ArXiv.org, Zenodo (`journal`).
- **`ebook_platform`.** 38 entrées sur 39 sont des sources OpenAlex au nom d'un éditeur suivi de « eBooks » (« ENS Éditions eBooks »). Elles désignent un éditeur, pas un lieu.
- **`unknown`.** 61 entrées sont les universités qui délivrent les thèses ScanR (« Université Clermont Auvergne (2021-...) », « Lyon », « Normandie »), avec l'ABES pour éditeur, soit 1 395 publications.
- **`media`.** Ce sont des publications en série : *The Conversation France* (378), *Revue Politique et Parlementaire* (102), *Le Monde*.
- **Deux codages des localisations.** Le type (`journal_type`) et le modèle open access `repository` se contredisent. Seuls bioRxiv, Research Square et ArXiv.org ont `oa_model = repository`. Les statistiques écartent leurs 227 publications (`STATS_BASE`), mais gardent celles de SSRN, de medRxiv et de Research Square typé `unknown`.
- **Localisations hors de `journals`.** 57 990 publications ont un identifiant HAL, 5 256 un PMCID, 5 051 un identifiant arXiv, 2 109 un NNT, 74 533 des URL. 22 726 publications ont seulement un `container_title` : colloque, livre ou archive.

Usages du type dans le code :

- **Espaces de noms DOI** : aucun pour `repository`, `preprint_server`, `ebook_platform` et `book_series` (`domain/journals/doi_namespaces.py`).
- **Typage** : l'enrichissement OpenAlex type seulement une entrée `unknown` (`repository`, `conference`, `book series`, `ebook platform`). `type_proceedings_journals` et `link_monographs_to_collections` posent `proceedings` et `book_series`. La vérification Sudoc traite `proceedings` et `book_series` comme des séries de volumes (`holds_volumes`).
- **Corrections du type de document** : `media` donne `media`, `proceedings` donne `conference_paper`, `preprint_server` donne `preprint` (`domain/source_records/metadata_correction/rules.py`). La fusion de deux revues requalifie les publications absorbées d'après le type de la cible.
- **Open access** : statuts attendus selon `oa_model`, types de document attendus selon `journal_type`, pour le tableau de bord d'une revue (`domain/journals/expected.py`) ; exclusion `oa_model = repository` des statistiques.
- **DOAJ et APC** : ils concernent en pratique les seules entrées `journal`. 2 266 sont dans le DOAJ et 3 725 ont des APC, contre 54 et 2 pour les autres types.
- **Interface** : libellé du type, choix du type dans l'administration, liste des recueils d'actes probables.

### Points des autres fiches que le modèle conditionne

- [Conférences et actes](DATA_conferences-et-actes.md) : noms d'archive dans `container_title`, retypage des séries d'actes typées `journal` ou `book_series`.
- [Revues divergentes selon les sources](DATA_revues-divergentes-entre-sources.md) : couples d'une revue et d'un dépôt ou d'un serveur de preprints ; correction de la revue d'après Crossref, qui remplacerait une localisation par une revue.
- [Monographies](DATA_monographies.md) : conversion d'une entrée de `journals` en monographie dans l'administration, documentation.

## Décisions

- Trois natures distinctes :
  - publication en série : revue, collection d'ouvrages, série d'actes ;
  - publication isolée : monographie, livre ou volume d'actes, rattachée ou non à une série ;
  - localisation : entrepôt, serveur de prépublications, plateforme.
- Les localisations sortent de `journals`.
- Schéma :
  - `publishers` et `doi_prefixes`, inchangées. Le titulaire d'un préfixe est l'éditeur d'origine de ses DOI ;
  - `serials`, à la place de `journals` : revues, collections d'ouvrages, séries d'actes, médias. Les ISSN, les formes de nom, les espaces de noms DOI, le DOAJ, les APC et le modèle open access y restent. Aucune colonne d'éditeur ;
  - `monographs` : livres et volumes d'actes, rattachés à leur série (`serial_id`) ;
  - `platforms` : lieux qui hébergent des publications, à savoir entrepôts, serveurs de preprints, plateformes d'éditeurs, index et agrégateurs. Type, identifiant d'entrepôt Unpaywall (`endpoint_id`), source OpenAlex ;
  - `platform_domains` : domaine → plateforme, plateforme nullable ;
  - localisations d'un enregistrement source : URL de la page, URL du PDF, plateforme nullable, version, licence, date d'ouverture. L'agrégation les réunit par publication ;
  - `publisher_id` sur `source_records` et `publications`.
- L'éditeur d'une série est celui de ses publications les plus récentes. Une publication a donc l'éditeur à la date de sa publication.

## Phasage

### Phase 1 — Inventaire

- [x] Revues qui changent d'éditeur, d'après le préfixe DOI de leurs publications (`f02277482`).
- [x] Membre qui détient les DOI Crossref et domaine de résolution, sur le raw store.
- [x] Localisations OpenAlex par lieu et par version, sur le raw store.
- [x] Répartition des entrées de `journals` par type, et des publications rattachées.
- [x] Usages de chaque nature : normalisation, rattachement par préfixe DOI, enrichissements, statut open access, APC, interface.

### Phase 2 — Modèle

- [ ] Entités, noms et relations des trois natures.
- [ ] Migration du schéma.

### Phase 3 — Pipeline

- [ ] Normalisation et rattachement des conteneurs selon leur nature.
- [ ] Enrichissements limités à la nature qu'ils décrivent.
- [ ] Thèses ScanR : l'université qui délivre la thèse quitte `journals`.
- [ ] Sources OpenAlex « … eBooks » : rattachement à l'éditeur qu'elles nomment.
- [ ] Exclusion des statistiques : un seul critère, à la place de `oa_model = repository`.
- [ ] Type `preprint` d'après la plateforme du DOI, à la place du type de la revue : les enregistrements DataCite arXiv n'ont pas de revue.

### Phase 4 — API et interface

- [ ] Endpoints, pages et filtres.

### Phase 5 — Documentation

- [ ] Mise à jour de `docs/donnees`, `docs/pipeline` et `docs/agregats`.

## Questions ouvertes

- Noms des entités dans l'interface.
- Une publication peut-elle avoir à la fois une série, une monographie et une ou plusieurs localisations ?
- Sort des entrées `unknown`.
- Lien entre une localisation et le statut open access d'une publication (dépôt HAL, prépublication).
- **Version d'un dépôt.** Une localisation d'une publication a une URL, une licence et une version : `submitted`, `accepted` ou `published`, comme chez OpenAlex et Unpaywall. La version `submitted` recoupe la relation `is_preprint_of` : comment éviter de dire deux fois la même chose ?
- **Table des URL.** Les URL d'une publication viennent d'Unpaywall, de Crossref et d'OpenAlex, avec leur lieu et leur version. Le lieu se déduit du domaine, par une table domaine → lieu que les changements de plateforme font évoluer. Le lieu d'un domaine peut rester inconnu.
- **Éditeur d'une publication.** Quelle règle remplit l'éditeur à la date de publication ? Le titulaire du préfixe donne l'éditeur d'origine, le membre Crossref l'éditeur actuel, le domaine l'hébergeur. À défaut de DOI Crossref, l'agrégation des sources.
- **Maintenance des référentiels.** Chaque table a son régime : recalcul à chaque run, mise à jour incrémentale par file d'attente, ou valeur posée une fois (typage OpenAlex, `doi_prefixes`). Comment rafraîchir une valeur posée une fois ? `doi_prefixes` attribue à Hindawi un préfixe dont Wiley détient les DOI.
- **Responsabilité scientifique et éditeur commercial.** Faut-il distinguer les deux rôles ? Le membre Crossref et le domaine de résolution les séparent dans une partie des cas.
- **Double série.** Un volume LIPIcs appartient à la collection LIPIcs, qui a un ISSN, et à la série de son congrès (STACS, SoCG, ICALP). `monographs.journal_id` en désigne une seule : laquelle ?
- **Ouvrage en plusieurs volumes** (« Current Developments in Biotechnology and Bioengineering »). Chaque volume est-il une monographie, et qu'est-ce qui les relie ?
