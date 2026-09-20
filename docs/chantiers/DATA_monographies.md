# Chantier — Monographies

Périmètre : les publications qui portent un ISBN, celles de type `book` ou `book_chapter`, et les conteneurs de type `proceedings` avec leurs `conference_paper`.

## Contexte

Un livre n'a pas d'entité dans la base. Le conteneur d'un livre ou d'un chapitre est le livre lui-même, et le titre du livre va dans la colonne `container_title`. Deux cas y échappent :

- la notice porte un ISSN, celui de la collection : cette collection devient la revue du document ;
- le titre du conteneur est déjà celui d'un recueil d'actes en base : le document y est rattaché, sans création.

Un volume d'actes, lui, a une entrée dans `journals`. La table range donc au même niveau les revues, les recueils d'actes et les collections qui les réunissent.

Les chapitres d'un même livre ne partagent qu'une chaîne de caractères, qui varie d'une source à l'autre. Rien ne réunit un livre et ses chapitres.

### ISBN

L'ISBN identifie un livre. Seul Crossref est lu (`external_ids.isbn`) ; HAL (TEI `idno type="isbn"`) et WoS (`isbn`, `eisbn`) le fournissent aussi, DataCite surtout en texte libre.

Le DOI porte souvent l'ISBN. Sa forme annonce alors la nature du document :

- ISBN seul en fin de DOI (`10.1007/978-3-030-20131-9`) : le DOI est celui du livre ou du volume d'actes ;
- ISBN suivi d'un suffixe (`10.1007/978-3-030-58080-3_309`, `10.48611/isbn.978-2-406-17883-5.p.0071`) : le DOI est celui d'un chapitre ou d'une communication.

### Correction du DOI des chapitres

La phase `metadata_correction` prive de leur DOI les chapitres qui le partagent avec leur livre (`OUVRAGE_VS_CHAPITRE`) ou avec des chapitres de titres différents (`CHAPITRES_TITRES_DIFFERENTS`, `domain/source_publications/metadata_correction/shared_doi.py`). Elle ne vérifie jamais que les titres diffèrent vraiment, d'où deux défauts :

- **Titres presque identiques tenus pour distincts.** La comparaison procède par égalité stricte et inclusion. Sur `10.1016/b978-0-323-99643-3.00015-2`, HAL écrit « Green polymers filaments for 3D-printing » et les autres sources « Green polymer filaments for 3D printing » : les quatre enregistrements perdent le DOI de leur propre chapitre.
- **Un type contredit suffit à opposer le livre au chapitre.** Sur `10.48611/isbn.978-2-406-17883-5.p.0071`, HAL type le document `book` et les autres sources `book_chapter`, sous le même titre. Les chapitres perdent un DOI dont le suffixe désigne pourtant la page 71.

## Décisions

- Une table `monographs` porte les livres et les volumes d'actes. Seul y entre un titre qui contient des publications de la base.
- Une colonne booléenne `proceedings` distingue le volume d'actes du livre. Ces deux natures suffisent, donc aucun type n'est nécessaire.

## Phasage

### 1. Mesure

- [ ] Livres, chapitres et communications sans conteneur, en production. ISBN disponibles par source, dans les champs dédiés et dans les DOI.
- [ ] Publications dont le DOI porte un ISBN et dont le type ne s'accorde pas à la forme du DOI : ISBN seul hors de `book` et `proceedings`, ISBN suffixé hors de `book_chapter` et `conference_paper`. Causes et volumes.
- [ ] Correction du DOI des chapitres : part des groupes dont les titres sont presque identiques, part de ceux dont le DOI partagé porte un ISBN suffixé.

### 2. Table

- [ ] Migration `monographs` : titre, titre normalisé, `proceedings`, ISBN, éditeur, collection.
- [ ] Rattachement d'une publication à sa monographie.

### 3. Remplissage

- [ ] Étape du pipeline qui crée et retrouve une monographie.
- [ ] Reprise du stock à partir de `container_title`.

### 4. Correction du DOI des chapitres

- [ ] Opposition livre/chapitre : exiger que les titres diffèrent.
- [ ] Forme du DOI : un ISBN suffixé désigne un chapitre, donc aucune correction de divergence ne s'applique.
- [ ] Comparaison des titres : tolérer les coquilles dans le test de distinction.

## Questions ouvertes

- **Identification.** Deux enregistrements désignent-ils la même monographie par leur ISBN, par leur titre normalisé, ou par le préfixe ISBN de leur DOI ? Les titres divergent d'une source à l'autre, et l'ISBN manque souvent.
- **Collection.** Une monographie rattachée à une collection pointe-t-elle la revue qui porte l'ISSN de cette collection ?
- **Recueils d'actes déjà en base.** Les entrées `proceedings` de `journals` rejoignent-elles `monographs`, ou la table `journals` garde-t-elle les recueils qui portent un ISSN ? Un recueil et la collection qui le réunit y occupent aujourd'hui le même niveau (*Communications in Computer and Information Science*, *IFIP AICT*).
