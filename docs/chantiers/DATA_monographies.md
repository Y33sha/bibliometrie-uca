# Chantier — Monographies

## Contexte

Un livre ou un volume d'actes n'a pas d'entité dans la base. La table `journals` ne le retient que s'il porte un ISSN, celui de sa collection. Sans ISSN, son titre va dans `container_title`, colonne de `publications` et de `source_publications`.

Les chapitres d'un même livre ne partagent donc qu'une chaîne de caractères, qui varie d'une source à l'autre. Rien ne réunit un livre et ses chapitres, ni un volume d'actes et ses communications.

L'ISBN identifie un livre. Seul Crossref est lu (`external_ids.isbn`) ; HAL et WoS le fournissent aussi, DataCite surtout en texte libre. Le DOI d'un chapitre contient souvent l'ISBN de son livre (`10.1007/978-3-030-58080-3_309`).

## Décisions

- Une table `monographs` porte les livres et les volumes d'actes. Seul y entre un titre qui contient des publications de la base.
- Une colonne booléenne `proceedings` distingue le volume d'actes du livre. Ces deux natures suffisent, donc aucun type n'est nécessaire.

## Phasage

### 1. Mesure

- [ ] Livres, chapitres et communications sans conteneur, en production. ISBN disponibles par source, dans les champs dédiés et dans les DOI.

### 2. Table

- [ ] Migration `monographs` : titre, titre normalisé, `proceedings`, ISBN, éditeur, collection.
- [ ] Rattachement d'une publication à sa monographie.

### 3. Remplissage

- [ ] Étape du pipeline qui crée et retrouve une monographie.
- [ ] Reprise du stock à partir de `container_title`.

## Questions ouvertes

- **Identification.** Deux enregistrements désignent-ils la même monographie par leur ISBN, par leur titre normalisé, ou par le préfixe ISBN de leur DOI ? Les titres divergent d'une source à l'autre, et l'ISBN manque souvent.
- **Collection.** Une monographie rattachée à une collection pointe-t-elle la revue qui porte l'ISSN de cette collection ?
- **Étape du pipeline.** La normalisation crée-t-elle la monographie, comme elle crée la revue, ou une étape postérieure la déduit-elle des enregistrements réunis ?
