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

- Une table `monographs` porte les livres et les volumes d'actes. Seul y entre un titre qui contient des publications de la base.
- Une colonne booléenne `proceedings` distingue le volume d'actes du livre. Ces deux natures suffisent, donc aucun type n'est nécessaire.
- La table a une clé technique. L'ISBN, absent de nombreuses monographies, porte une contrainte d'unicité.
- Deux colonnes portent les ISBN, `isbn` et `eisbn`, comme les revues portent leurs ISSN. Une source qui déclare le support électronique alimente `eisbn` ; sans déclaration, l'ISBN va dans `isbn`. Les identifiants externes d'un enregistrement suivent la même partition.
- Chaque écriture d'un ISBN passe par le value object `ISBN` : forme ISBN-13 sans séparateur, ISBN-10 converti, clé de contrôle vérifiée. `normalize_external_ids` l'applique déjà aux identifiants externes.
- Une zone qui porte plusieurs valeurs donne son premier ISBN. Rien n'indique l'ordre des supports.

## Phasage

### 1. Table

- [x] Migration `monographs` : titre, titre normalisé, `proceedings`, année, ISBN sous contrainte d'unicité, éditeur, collection (`e3a559024`).
- [x] Rattachement d'une publication à sa monographie : `publications.monograph_id` (`e3a559024`).

### 2. ISBN des autres sources

- [x] Audit du raw store (`audit_isbn_in_raw_store`, `5dee27b41`). Les notices brutes portent l'ISBN à quatre places : la zone TEI `<idno type="isbn">` de HAL, un `relatedIdentifiers` de type ISBN ou l'identifiant du conteneur chez DataCite, un identifiant `isbn` ou `eisbn` chez WoS, les identifiants externes de ScanR. Sur la base locale, DataCite en porte un dans 91 % de ses notices, WoS dans 31 %, HAL dans 20 %, ScanR dans aucune. Leur lecture donnerait un ISBN à 2 954 publications et à 1 774 conteneurs de chapitres qui n'en ont pas.
- [x] Lecture de ces champs par les normaliseurs de HAL, DataCite et WoS. Crossref range sous `eisbn` l'ISBN dont il déclare le support électronique, WoS celui de son identifiant `eisbn`. `find_isbns` extrait chaque motif d'ISBN d'une zone, et le value object valide à l'écriture.
- [ ] Stock : réhydrater le staging depuis le raw store, puis renormaliser HAL, DataCite et WoS. La zone TEI de HAL demande d'extraire chaque motif d'ISBN : sur 4 421 valeurs, 182 portent deux ISBN, un EAN, un ISSN, une faute de frappe ou un suffixe de chapitre (`978-3-319-77273-8_16`).
- [ ] Colonne `eisbn` de `monographs`, alimentée par les sources qui déclarent le support électronique.
- [ ] Support inconnu : vérification dans le Sudoc, qui le donne en zone 182 (`n` papier, `c` électronique) et accepte plusieurs ISBN par requête. Sur un échantillon interrogé un à un, le Sudoc tient 11 des 12 ISBN venus de HAL et 12 des 12 venus de Crossref, contre 1 sur 12 pour ceux de DataCite.
- Deuxième source écartée pour l'instant : la DNB, interrogeable en SRU sans clé, couvre les éditeurs allemands que le Sudoc rate — Springer, De Gruyter, Dagstuhl — et donne le support en zones 337 et 338. Open Library et Google Books ne conviennent pas : le premier couvre peu et se trompe de support, le second ne le donne pas.

### 3. Remplissage

- [ ] Mesure : livres, chapitres et communications sans conteneur, et titres de conteneur distincts qu'ils portent.
- [ ] Étape du pipeline qui crée et retrouve une monographie.
- [ ] Reprise du stock à partir de `container_title`.

### 4. Type contredit par la forme du DOI

- [ ] Mesure : publications dont le DOI porte un ISBN et dont le type ne s'y accorde pas — ISBN seul hors de `book` et `proceedings`, ISBN suffixé hors de `book_chapter` et `conference_paper`. Causes et volumes.

### 5. Correction du DOI des chapitres

- [ ] Mesure : part des groupes corrigés dont les titres sont presque identiques, part de ceux dont le DOI partagé porte un ISBN suffixé.
- [ ] Opposition livre/chapitre : exiger que les titres diffèrent.
- [ ] Forme du DOI : un ISBN suffixé désigne un chapitre, donc aucune correction de divergence ne s'applique.
- [ ] Comparaison des titres : tolérer les coquilles dans le test de distinction.

## Questions ouvertes

- **Identification sans ISBN.** L'ISBN réunit deux enregistrements quand il est là. Sinon, quel signal les réunit : le titre normalisé du conteneur, l'éditeur, le préfixe du DOI ? Les titres divergent d'une source à l'autre.
- **Collection.** Une monographie rattachée à une collection pointe-t-elle la revue qui porte l'ISSN de cette collection ?
- **Volumes multiples.** Un titre paru en plusieurs volumes n'est pas traité. Chaque volume est-il une monographie, et qu'est-ce qui les relie ?
- **Recueils d'actes déjà en base.** Les entrées `proceedings` de `journals` rejoignent-elles `monographs`, ou la table `journals` garde-t-elle les recueils qui portent un ISSN ? Un recueil et la collection qui le réunit y occupent aujourd'hui le même niveau (*Communications in Computer and Information Science*, *IFIP AICT*).
