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
- **Version d'un dépôt.** Une localisation d'une publication a une URL, une licence et une version : `submitted`, `accepted` ou `published`, comme chez OpenAlex et Unpaywall. La version `submitted` recoupe la relation `is_preprint_of` : comment éviter de dire deux fois la même chose ?
- **Double série.** Un volume LIPIcs appartient à la collection LIPIcs, qui a un ISSN, et à la série de son congrès (STACS, SoCG, ICALP). `monographs.journal_id` en désigne une seule : laquelle ?
- **Ouvrage en plusieurs volumes** (« Current Developments in Biotechnology and Bioengineering »). Chaque volume est-il une monographie, et qu'est-ce qui les relie ?
