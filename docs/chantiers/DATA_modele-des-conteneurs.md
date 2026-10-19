# Chantier — Modèle des conteneurs

## Contexte

Le conteneur d'une publication est ce qui la publie ou l'héberge. Le schéma en donne trois représentations :

- `publishing.journals`, que référence `publications.journal_id` ;
- `publishing.monographs`, que référence `publications.monograph_id`, avec un ISBN et un `journal_id` vers sa collection ;
- `publications.container_title`, un titre libre quand aucune des deux tables ne convient.

`journals` réunit des choses de natures différentes. Son type (`journal_type`) vaut :

- `journal`, `book_series`, `proceedings`, `media` : des publications en série ;
- `repository`, `preprint_server`, `ebook_platform` : des localisations, qui hébergent des publications sans les publier ;
- `unknown`.

Les colonnes de `journals` décrivent une revue : présence dans le DOAJ, modèle open access, APC. Elles n'ont pas de sens pour un entrepôt.

`monographs` apparaît après `journals`, pour réunir les volumes d'actes sous une même collection d'actes. Un livre sans ISBN n'a pas d'entité : son titre reste dans `container_title`.

Le nom `journals` couvre ainsi des collections d'ouvrages, des serveurs de prépublications et des entrepôts de données. Il désigne mal son contenu.

Deux fiches portent sur des cas que le modèle conditionne :

- [Monographies](DATA_monographies.md) : livres, ISBN, chapitres, recueils d'actes ;
- [Conférences et actes](DATA_conferences-et-actes.md) : séries d'actes typées `journal` ou `book_series`, `container_title` qui contient tantôt un colloque, tantôt une archive.

## Décisions

- Trois natures distinctes :
  - publication en série : revue, collection d'ouvrages, série d'actes ;
  - publication isolée : monographie, livre ou volume d'actes, rattachée ou non à une série ;
  - localisation : entrepôt, serveur de prépublications, plateforme.
- Les localisations sortent de `journals`.

## Phasage

### Phase 1 — Inventaire

- [ ] Répartition des entrées de `journals` par type, et des publications rattachées, sur la base de production.
- [ ] Usages de chaque nature : normalisation, rattachement par ISSN et par préfixe DOI, enrichissements (DOAJ, Sudoc, OpenAlex), statut open access, APC, interface.

### Phase 2 — Modèle

- [ ] Entités, noms et relations des trois natures.
- [ ] Migration du schéma.

### Phase 3 — Pipeline

- [ ] Normalisation et rattachement des conteneurs selon leur nature.
- [ ] Enrichissements limités à la nature qu'ils décrivent.

### Phase 4 — API et interface

- [ ] Endpoints, pages et filtres.

### Phase 5 — Documentation

- [ ] Mise à jour de `docs/donnees`, `docs/pipeline` et `docs/agregats`.

## Questions ouvertes

- Noms des trois entités, en anglais dans le code et en français dans l'interface.
- Une publication peut-elle avoir à la fois une série, une monographie et une ou plusieurs localisations ?
- Place de `media`, et sort de `unknown`.
- Lien entre une localisation et le statut open access d'une publication (dépôt HAL, prépublication).
- Ordre avec les fiches Monographies et Conférences et actes.
