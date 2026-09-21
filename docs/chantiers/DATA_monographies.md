# Chantier — Monographies

Périmètre : les publications qui portent un ISBN, celles de type `book` ou `book_chapter`, et les conteneurs de type `proceedings` avec leurs `conference_paper`.

## Contexte

Un livre n'a pas d'entité dans la base. Le conteneur d'un livre ou d'un chapitre est le livre lui-même, et le titre du livre va dans la colonne `container_title`. Deux cas font exception :

- la notice porte un ISSN, celui de la collection : cette collection devient la revue du document ;
- le titre du conteneur est déjà celui d'un recueil d'actes en base : le document y est rattaché, sans création.

Un volume d'actes, lui, a une entrée dans `journals`. La table range donc au même niveau les revues, les recueils d'actes et les collections dont ils font partie.

Les chapitres d'un même livre ne partagent qu'une chaîne de caractères, qui varie d'une source à l'autre. Rien ne réunit un livre et ses chapitres.

### ISBN

L'ISBN identifie un livre. Seul ceux issus de Crossref sont lus (`external_ids.isbn`) ; pourtant HAL (TEI `idno type="isbn"`) et WoS (`isbn`, `eisbn`) le fournissent aussi, DataCite dans un `relatedIdentifiers` de type ISBN ou dans l'identifiant de son conteneur.

Un livre porte souvent deux ISBN, un par support. Crossref et WoS disent lequel est électronique ; HAL et DataCite le taisent. Le numéro lui-même n'en dit rien : l'éditeur attribue un numéro par format. Un ISBN-13 est un EAN-13, à préfixe 978 ou 979.

Le DOI porte souvent l'ISBN. Sa forme annonce alors la nature du document :

- ISBN seul en fin de DOI (`10.1007/978-3-030-20131-9`) : le DOI est celui du livre ou du volume d'actes ;
- ISBN suivi d'un suffixe (`10.1007/978-3-030-58080-3_309`, `10.48611/isbn.978-2-406-17883-5.p.0071`) : le DOI est celui d'un chapitre ou d'une communication.

### Correction du DOI des chapitres

La phase `metadata_correction` prive de leur DOI les chapitres qui le partagent avec leur livre (`OUVRAGE_VS_CHAPITRE`) ou avec des chapitres de titres différents (`CHAPITRES_TITRES_DIFFERENTS`, `domain/source_publications/metadata_correction/shared_doi.py`). Elle a deux défauts :

- **Titres presque identiques tenus pour distincts.** La comparaison procède par égalité stricte et inclusion. Sur `10.1016/b978-0-323-99643-3.00015-2`, HAL écrit « Green polymers filaments for 3D-printing » et les autres sources « Green polymer filaments for 3D printing » : les quatre enregistrements perdent le DOI de leur propre chapitre.
- **Un type contredit suffit à opposer le livre au chapitre.** Sur `10.48611/isbn.978-2-406-17883-5.p.0071`, HAL type le document `book` et les autres sources `book_chapter`, sous le même titre. Les chapitres perdent un DOI dont le suffixe désigne pourtant la page 71.

## Décisions

### Table des monographies

- Une table `monographs` porte les livres et les volumes d'actes. Seul y entre un titre qui contient des publications de la base.
- Une colonne booléenne `proceedings` distingue le volume d'actes du livre. Ces deux natures suffisent, donc aucun type n'est nécessaire.
- La table a une clé technique. L'ISBN, absent de nombreuses monographies, porte une contrainte d'unicité.
- Deux colonnes portent les ISBN, `isbn` et `eisbn`, comme les revues portent leurs ISSN. Une source qui déclare le support électronique alimente `eisbn` ; sans déclaration, l'ISBN va dans `isbn`. Les identifiants externes d'un enregistrement suivent la même partition.
- Chaque écriture d'un ISBN passe par le value object `ISBN` : forme ISBN-13 sans séparateur, ISBN-10 converti, clé de contrôle vérifiée. `normalize_external_ids` l'applique déjà aux identifiants externes.
- Une zone qui porte plusieurs valeurs donne son premier ISBN. Rien n'indique l'ordre des supports.
- Une monographie est retrouvée par ISBN, puis par titre normalisé chez le même éditeur : deux éditeurs publient des livres de même titre. Deux monographies de même titre qui portent chacune des ISBN restent distinctes.
- La normalisation pose `source_publications.monograph_id`, que l'agrégation reporte sur `publications.monograph_id`, comme `journal_id`.

### Cible

- `journals` contient les publications en série : revues et collections, avec ou sans ISSN, sous leur titre de référence. `journal_type = proceedings` désigne une série d'actes, jamais un volume.
- `monographs` contient les livres et les volumes d'actes. Leur `journal_id` désigne leur collection, quand elle existe.
- Le `journal_id` d'un enregistrement désigne une série, jamais un volume. Son `monograph_id` désigne le livre ou le volume qui le contient.
- La cible s'atteint par le processus, depuis une base vide : chaque règle se calcule à chaque run, sans état antérieur.

### Règles

- **Niveau d'un titre de conteneur.** Un ISBN désigne un livre ; un ISSN désigne une série, jamais un volume. Quand la source sépare les deux niveaux, sa structure fait foi : `container-title` de Crossref, `bookTitle_s` de HAL, type de source OpenAlex. Sans ISSN, une entrée dont les documents sont des livres, des chapitres ou des articles de congrès est un volume, quel que soit son titre. Avec un ISSN, le titre départage : une année, un ordinal d'édition ou un numéro de volume désignent un volume qui porte l'ISSN de sa collection ; sinon, c'est la collection. Le classement vit dans le domaine (`domain/journals/series.py`).
- **Titre de référence d'une série à ISSN.** Une série d'actes ou une collection de livres dont le titre a la forme d'un volume prend le titre de sa notice Sudoc, à défaut son titre sans marques d'édition (`series_title`). Une revue garde son titre, même daté (« Periodontology 2000 »). Les autres titres restent la référence.
- **Série sans ISSN.** Elle se reconnaît seulement entre plusieurs volumes : même clé de série (titre sans année, numéro d'édition ni ordinal), éditeur compatible. Son titre est la forme commune des volumes.
- **Chemin.** Aucune suppression avant la dernière étape. Les monographies doublonnent d'abord les entrées de `journals` ; elles sont ensuite rattachées à leur collection ; les entrées de `journals` qui décrivent un volume sont supprimées en dernier, une fois vidées.

## Phasage

### 1. Table

- [x] Migration `monographs` : titre, titre normalisé, `proceedings`, année, ISBN sous contrainte d'unicité, éditeur, collection (`e3a559024`).
- [x] Rattachement d'une publication à sa monographie : `publications.monograph_id` (`e3a559024`).

### 2. ISBN des autres sources

- [x] Audit du raw store (`audit_isbn_in_raw_store`, `5dee27b41`). Les notices brutes portent l'ISBN à quatre places : la zone TEI `<idno type="isbn">` de HAL, un `relatedIdentifiers` de type ISBN ou l'identifiant du conteneur chez DataCite, un identifiant `isbn` ou `eisbn` chez WoS, les identifiants externes de ScanR. Sur la base locale, DataCite en porte un dans 91 % de ses notices, WoS dans 31 %, HAL dans 20 %, ScanR dans aucune. Leur lecture donnerait un ISBN à 2 954 publications et à 1 774 conteneurs de chapitres qui n'en ont pas.
- [x] Lecture de ces champs par les normaliseurs de HAL, DataCite et WoS. Crossref range sous `eisbn` l'ISBN dont il déclare le support électronique, WoS celui de son identifiant `eisbn`. `find_isbns` extrait chaque motif d'ISBN d'une zone, et le value object valide à l'écriture.
- [ ] Stock : réhydrater le staging depuis le raw store, puis renormaliser HAL, DataCite et WoS. La zone TEI de HAL demande d'extraire chaque motif d'ISBN : sur 4 421 valeurs, 182 portent deux ISBN, un EAN, un ISSN, une faute de frappe ou un suffixe de chapitre (`978-3-319-77273-8_16`).
- [x] Colonne `eisbn` de `monographs`, alimentée par les sources qui déclarent le support électronique.
- [ ] Support inconnu : vérification dans le Sudoc, qui le donne en zone 182 (`n` papier, `c` électronique) et accepte plusieurs ISBN par requête. Sur un échantillon interrogé un à un, le Sudoc tient 11 des 12 ISBN venus de HAL et 12 des 12 venus de Crossref, contre 1 sur 12 pour ceux de DataCite.
- Deuxième source écartée pour l'instant : la DNB, interrogeable en SRU sans clé, couvre les éditeurs allemands que le Sudoc rate — Springer, De Gruyter, Dagstuhl — et donne le support en zones 337 et 338. Open Library et Google Books ne conviennent pas : le premier couvre peu et se trompe de support, le second ne le donne pas.

### 3. Remplissage

- [x] Rattachement des enregistrements : `source_publications.monograph_id`, agrégé dans `publications.monograph_id`.
- [x] Trouve-ou-crée d'une monographie (`application/services/monographs/core.py`).
- [x] Normalisation, sans rien retirer : l'enregistrement garde son `journal_id` selon la règle en place, et reçoit en outre sa monographie, dont le `journal_id` désigne la même entrée de `journals`. Chaque source décrit le conteneur du document (`ContainerFacts`). Crossref : `container-title` porte `[collection, livre]` pour un chapitre, le volume d'actes en tête pour un article de congrès. HAL : `bookTitle_s` ; le congrès (`conferenceTitle_s`) ne désigne pas un volume, une communication le nomme avec ou sans actes publiés. OpenAlex : source `conference` pour le volume, `book series` ou `journal` pour la collection. WoS : titre de la source, hors ISSN. ScanR : congrès d'une communication. DataCite : conteneur sans ISSN.
- [x] Sous-étape `delete_empty_monographs` de `publishers_journals`. Un éditeur qui porte une monographie n'est pas vide ; la fusion d'éditeurs transfère les monographies.
- [x] Audit de 2026 : 161 monographies, correspondance un pour un avec `journals` (6 entrées). 15 titres en double, presque tous parce que HAL ne donne pas l'éditeur.
- [x] Rapprochement par titre dans le domaine (`choose_monograph`) : un éditeur absent ne sépare pas deux monographies ; la monographie du même éditeur passe avant celle sans éditeur.
- [x] Sous-étape `merge_duplicate_monographs` : une monographie rejoint la seule monographie compatible de son titre (`duplicate_monographs`). Simulation : 12 fusions sur 24 titres en double. Les autres opposent des éditeurs en double (Quæ et Quae, Peter Lang et Peter Lang Verlag, Garnier et Classiques Garnier, Springer et ses filiales) ou des volumes de même titre à ISBN distincts.
- [ ] Volumes HAL : la plupart des documents typés `PROCEEDINGS` sont des communications. Trois signaux désignent un volume : seulement des éditeurs ou des contributeurs, un titre qui commence par « Actes », « Proceedings », « Book of abstracts » ou « Dossier », un titre égal à celui du conteneur. Ils retiennent 107 documents sur 350.
- [x] DataCite : le filtre des conteneurs vaut pour `journal_id` seulement. Un livre prend l'ISBN de ses identifiants (`identifiers`, `alternateIdentifiers`). Les livres et chapitres Classiques Garnier (226) ont un conteneur sans titre, décrit par les seuls ISSN de la collection (`LISSN`, `EISSN`).
- [ ] Stock : renormalisation de toutes les sources (Crossref réhydraté depuis le raw store).
- [ ] Mesure : monographies créées, correspondance avec les entrées de `journals` (un pour un attendu), doublons (même livre sous deux titres, sans ISBN commun), livres, chapitres et communications sans monographie.

### 4. Classement des conteneurs (à blanc)

- [x] Fonction du domaine : niveau d'un titre de conteneur (`container_level`), d'après l'année, l'ordinal d'édition et le numéro de volume ; un siècle n'est pas un ordinal. Clé de série d'un titre de volume (`series_key`).
- [x] Audit versionné (`audit_container_levels`) sur 10 864 entrées. Revues : 9 663, dont 520 sans ISSN. Plateformes : 92. Titres de volume : 654 sans ISSN, 3 avec ISSN (ICORES 2023, World Congress 2009, CoDIT). Titres de série : 324 avec ISSN, des collections ; 127 sans ISSN, presque tous des livres ou des volumes sans marque d'édition, d'où la règle : sans ISSN, une entrée de livres, chapitres ou articles de congrès est un volume.
- [x] Audit des séries sans ISSN : 97 séries reconnues pour 321 volumes, par clé de série et éditeur (Winter Simulation Conference, CoDIT, IROS, ICRA, Goldschmidt, PoS ICRC). Aucun faux regroupement dans l'échantillon.

### 5. Titre de référence des séries

- [x] Vérification Sudoc : une série d'actes ou une collection de livres à ISSN dont le titre a la forme d'un volume entre dans la file, et reçoit le titre de sa notice, à défaut son titre sans marques d'édition. Le nouveau titre devient une forme de nom. Aucune des trois séries concernées (ICORES, CoDIT, IFMBE Proceedings) n'a de notice Sudoc, ni de source chez Crossref ; OpenAlex nomme la troisième d'après son volume de 2009. Parmi les 14 entrées à ISSN titrées comme un volume, 10 sont des revues (« Gestion 2000 », « 1895 »), qui gardent leur titre.

### 6. Normalisation cible

- [x] `determine_container_type` (`domain/journals/containers.py`) sépare la description du conteneur (`ContainerDescription`) en série et volume. La normalisation en tire le `journal_id` et la monographie des enregistrements.
- [x] Résolution de la série (`find_or_create_containers`) : trouvée ou créée sous son titre de série. Une série à ISSN sans titre est seulement cherchée par ISSN (source OpenAlex de type `conference`, article de congrès Crossref à deux titres). Un volume donne seulement une monographie. Un article sans ISSN dont le conteneur nomme une édition datée de congrès (« 2021 ICCAS ») reçoit un volume d'actes.
- [x] Séries sans ISSN, dans la sous-étape `link_monographs_to_collections` : les monographies sans collection à ISSN dont le titre porte une marque d'édition se regroupent par clé de série et éditeur (`group_series`). Chaque série trouve ou crée son entrée dans `journals`, typée série d'actes ou collection de livres selon ses volumes. Le rattachement retient la collection à ISSN, puis la série sans ISSN, puis le volume, puis aucune entrée (`choose_monograph_journal`). La suppression des revues vides épargne une entrée qu'une monographie désigne. Simulation : 92 séries, dont 88 nouvelles entrées, 292 monographies rattachées. Des titres identiques sans marque d'édition (« Current Developments in Biotechnology and Bioengineering », 32 groupes) désignent un ouvrage en plusieurs volumes : pas de série.
- [x] Sous-étape `link_monographs_to_collections` : une monographie a pour `journal_id` la seule entrée de `journals` à ISSN que portent ses enregistrements. Plusieurs entrées au même niveau sont signalées comme conflit, sans changement. Mesure : 734 monographies à collection, aucune à plusieurs candidats.
- [x] Rattachement par espace de noms DOI réservé aux articles et articles de congrès : 220 livres et chapitres recevaient la revue de leur éditeur (Hermès chez CAIRN, EAC).
- [x] Agrégation : le `journal_id` d'une publication vient de ses enregistrements, à défaut de la collection de sa monographie (`monograph_journals`). Aujourd'hui 49 publications, dont 34 vers une collection à ISSN.
- [x] Règle de correction `PROCEEDINGS_VOLUME_TO_CONFERENCE_PAPER` : un article ou un chapitre dont la monographie est un volume d'actes devient un article de congrès. Prédicat `in_proceedings_volume`, joint à la lecture. Aujourd'hui 8 enregistrements ; la règle prend le relais de `JOURNAL_TYPE_PROCEEDINGS_TO_CONFERENCE_PAPER` quand les volumes quittent `journals`.

- [ ] Conférences sans ISSN : reconnaître les principales conférences par une liste fermée d'acronymes, pour regrouper leurs volumes en série même sans ISSN. Forme de la liste à trancher.

### 7. Stock

- [x] Choix du chemin : normalisation cible d'un seul coup (la série par ISSN, le volume en monographie, aucun volume créé dans `journals`), et oneshot pour le stock. Le oneshot reconstruit la description du conteneur à partir des champs en base et appelle `determine_container_type`. Condition : l'état qu'il produit est un point fixe du pipeline.
- [x] Instantané des articles de congrès (`snapshot_conference_papers`), avant la bascule : 12 842 articles, 627 séries (536 à ISSN, 91 sans), 1 198 volumes (1 133 en monographie, 65 dans `journals`), 10 488 articles sans série, 11 070 sans volume.
- [x] Normalisation cible.
- [ ] Audit de l'écart entre le oneshot et la normalisation, sur les notices du raw store. Mesurer les séries à ISSN sans titre absentes de `journals`.
- [ ] Oneshot, puis `publishers_journals` et `publications` ; un second run doit tout laisser en l'état.
- [ ] Suppression des entrées de `journals` qui décrivent un volume, une fois vidées (`delete_empty_journals`).
- [ ] Mesure finale : instantané après la bascule, comparé au premier (`--compare`).

### 8. Administration

- [ ] Conversion d'une entrée de `journals` en monographie, et l'inverse. La décision survit à la renormalisation : le classement d'un titre la consulte avant ses règles.

### 9. Type contredit par la forme du DOI

- [ ] Mesure : publications dont le DOI porte un ISBN et dont le type ne s'y accorde pas — ISBN seul hors de `book` et `proceedings`, ISBN suffixé hors de `book_chapter` et `conference_paper`. Causes et volumes.

### 10. Correction du DOI des chapitres

- [ ] Mesure : part des groupes corrigés dont les titres sont presque identiques, part de ceux dont le DOI partagé porte un ISBN suffixé.
- [ ] Opposition livre/chapitre : exiger que les titres diffèrent.
- [ ] Forme du DOI : un ISBN suffixé désigne un chapitre, donc aucune correction de divergence ne s'applique.
- [ ] Comparaison des titres : tolérer les coquilles dans le test de distinction.

### 11. Documentation

- [ ] Mise à jour de la documentation : `docs/pipeline/03-normalize.md` (conteneurs et monographies), `docs/pipeline/05-publishers-journals.md` (suppression des monographies vides), `docs/agregats/journals.md`, fiche des revues (règle des conteneurs).

## Questions ouvertes

- **Identification sans ISBN.** L'ISBN réunit deux enregistrements quand il est là. Sinon, quel signal les réunit : le titre normalisé du conteneur, l'éditeur, le préfixe du DOI ? Les titres divergent d'une source à l'autre.
- **Volumes multiples.** Un titre paru en plusieurs volumes n'est pas traité. Chaque volume est-il une monographie, et qu'est-ce qui les relie ?
- **Double série.** Un volume LIPIcs appartient à la collection LIPIcs, qui porte un ISSN, et à la série de son congrès (STACS, SoCG, ICALP). `monographs.journal_id` n'en désigne qu'une : laquelle ?
- **Volumes HAL.** Faut-il faire une monographie d'un document `PROCEEDINGS` qui présente l'un des trois signaux de volume ? Les « Dossier : … Actes du colloque » (une trentaine) sont-ils des monographies, ou des numéros spéciaux de revue ?

