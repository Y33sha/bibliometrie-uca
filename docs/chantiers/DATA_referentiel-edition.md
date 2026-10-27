# Chantier — Qualité du référentiel de l'édition

## Contexte

Base locale au 2026-10-27 : 10 871 revues, 6 872 éditeurs.

### Formes de nom des revues

`serial_name_forms` associe un titre normalisé et un éditeur à une revue. La recherche par titre de `find_or_create_serial` lit seulement cette table. Une forme s'ajoute à la création d'une revue et à chaque rattachement par identifiant OpenAlex ou par ISSN. Aucune étape ne purge la table.

- **Doublons.** La contrainte `(form_normalized, publisher_id)` compte deux éditeurs nuls comme différents : 69 413 des 69 836 formes sans éditeur sont des doublons.
- **Provenance.** `source_records.biblio` garde ce que la source donne : titre brut de la revue, ISSN et identifiant OpenAlex (`biblio.journal`), nom brut de l'éditeur (`biblio.publisher`). Rapprochées de ces titres, 441 des 2 534 formes sans éditeur et 2 719 des 17 438 formes avec éditeur sont sans enregistrement source producteur. 1 605 couples (titre, éditeur) des enregistrements sources sont sans forme : le rattachement par titre écrit seulement dans `source_records`.
- **Titre du référentiel.** La correction d'un titre dans l'administration réécrit `serials.title` seulement. La vérification Sudoc écrit une forme quand elle donne son titre de série à une série d'actes ou à une collection.
- **Forme sans éditeur.** Elle répond à tout éditeur. Quatre formes sans éditeur désignent deux revues : « regards » (11220, 70507), « reperes » (8063, 9778), « atem archiv fur textmusikforschung » (67294, 96761), « french journal of urology » (20878, 20893). Le préfixe DOI de leurs publications sépare les deux revues « Regards » et les deux revues « Repères ».
- **Éditeur absent.** Les revues à forme sans éditeur comptent 10 123 enregistrements sources sans éditeur. 8 795 ont un DOI dont le préfixe a un titulaire connu (`doi_prefixes.publisher_id`). Pour 8 097, ce titulaire a déjà une forme pour la revue. `doi_prefixes` est rempli après `normalize`.
- **Éditeurs retenus.** `delete_empty_publishers` garde un éditeur que désigne une forme de nom de revue.

### Éditeurs

- 1 602 publications, dans 445 revues, ont un éditeur différent de celui de leur revue.
- 4 765 publications ont un éditeur différent du titulaire du préfixe de leur DOI : 4 134 préfixes Crossref, 631 préfixes DataCite. `publications.publisher_id` est défini comme le titulaire du préfixe du DOI Crossref, à défaut l'éditeur des enregistrements sources.
- Deux noms normalisés sont partagés par deux éditeurs.

### Titres de revue

OpenAlex retire les apostrophes. 106 titres de revue ont la forme « Annales d Endocrinologie », « L Encéphale », « Journal Français d Ophtalmologie ». 441 titres ont une apostrophe.

### Conteneur libre

`publications.container_title` est renseigné pour 39 690 publications, dont 10 202 à revue et 8 876 à monographie. OpenAlex y met le nom d'un repository : « HAL (Le Centre pour la Communication Scientifique Directe) » pour 28 846 de ses 52 116 enregistrements sources à conteneur, puis arXiv, theses.fr, Figshare, Zenodo.

### Administration

Les personnes et les publications ont un volet latéral (`PersonDrawer`, `PublicationDrawer`). Les pages Éditeurs et Revues (`publishers/`, `journals/`) ouvrent une page par entité.

## Décisions

- Une forme par couple (forme, éditeur), éditeur absent compris.
- Les valeurs de la source qui servent au rattachement de la revue et de l'éditeur sortent de `biblio`. Elles deviennent des colonnes typées de `source_records` : titre brut de la revue et sa forme normalisée, nom brut de l'éditeur, ISSN et identifiant OpenAlex de la revue.
- Une forme de nom sans éditeur et sans enregistrement source producteur est supprimée.

## Phasage

### Phase 1 — Formes de nom des revues

- [x] Contrainte `NULLS NOT DISTINCT`, dédoublonnage des formes sans éditeur (7668391c6)
- [ ] Colonnes de la source sur `source_records`, écrites par les normaliseurs et reprises de `biblio` pour le stock. Lecteurs à basculer : vérification Sudoc, détection des actes de congrès, comparaison des sources.
- [ ] Régime de `serial_name_forms` (question 1), purge des formes sans producteur
- [ ] Titre du référentiel comme forme de nom
- [ ] Éditeur déduit du préfixe DOI pour un enregistrement source sans éditeur (question 2)
- [ ] Les quatre formes sans éditeur partagées par deux revues

### Phase 2 — Éditeurs

- [ ] Divergences entre éditeur de la publication, éditeur de la revue et titulaire du préfixe : audit, classement par cause
- [ ] Mesure des doublons d'éditeurs sous des noms différents

### Phase 3 — Titres de revue

- [ ] Apostrophes retirées par OpenAlex

### Phase 4 — Conteneur libre

- [ ] Usage de `container_title` à côté de `serial_id` et `monograph_id` : exploitation ou suppression de la colonne
- [ ] Noms de repository dans le `container_title` d'OpenAlex

### Phase 5 — Administration

- [ ] Volet latéral des pages Éditeurs et Revues

### Phase 6 — Fin de chantier

- [ ] Mise à jour de la documentation

## Questions ouvertes

1. Régime de `serial_name_forms` : recalcul à chaque passage de `publishing` à partir des colonnes de `source_records` et du titre du référentiel, ou accumulation avec purge. Avec le recalcul, deux revues qui produisent le même couple (forme, éditeur) demandent un départage. Celui de la recherche donne la revue à ISSN électronique actif, puis le plus petit identifiant.
2. Éditeur déduit du DOI : report dans `publishing` une fois les préfixes résolus, ou résolution du préfixe dès `normalize`. Destination : `source_records.publisher_id`, le nom brut restant dans sa colonne, ou la forme de nom seule.
3. Migration `c8e3f1a6d924` : sa première étape supprime une forme sans éditeur quand aucun enregistrement source sans éditeur ne désigne sa revue. Le lien exact passe par `normalize_text`, hors de portée du SQL pur. Garder cette étape, ou la retirer au profit de la purge de la phase 1.
