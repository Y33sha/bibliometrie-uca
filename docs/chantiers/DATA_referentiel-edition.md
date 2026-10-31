# Chantier — Qualité du référentiel de l'édition

## Contexte

Base locale au 2026-10-27 : 10 871 revues, 6 872 éditeurs.

### Reconnaissance des revues

La normalisation cherche ou crée la revue de chaque enregistrement source (`find_or_create_serial`) : par identifiant OpenAlex, puis par ISSN, puis par titre parmi les formes de nom (`serial_name_forms`, 19 976 formes). Le résultat dépend de l'ordre d'arrivée des enregistrements sources. La phase `publishing` fusionne ensuite les revues en double par cinq règles (`merge_duplicate_serials`). Une fusion de revues est définitive.

Base locale au 2026-10-31 :

- 10 317 des 11 023 revues ont un ISSN actif. 176 882 des 185 262 enregistrements sources rattachés à une revue donnent un ISSN ou un identifiant OpenAlex.
- Le titre seul fixe la revue de 2 222 publications, réparties sur 666 revues : `journal` 957, `proceedings` 417, `media` 304, `preprint_server` 243, `unknown` 236, `book_series` 63.
- `biblio.journal` garde le premier conteneur nommé par la source. Le rattachement lit la série extraite du conteneur : collection séparée du livre, noms de plateforme d'ebooks écartés. Les deux diffèrent pour un chapitre.
- 441 des 2 534 formes sans éditeur et 2 719 des 17 438 formes avec éditeur sont sans enregistrement source producteur (2026-10-27). Un rattachement par une forme sans éditeur écrit seulement dans `source_records` : 1 605 couples (titre, éditeur) des enregistrements sources sont sans forme.
- Une forme sans éditeur répond à tout éditeur. Quatre formes sans éditeur désignent deux revues : « regards » (11220, 70507), « reperes » (8063, 9778), « atem archiv fur textmusikforschung » (67294, 96761), « french journal of urology » (20878, 20893). Le préfixe DOI de leurs publications sépare les deux revues « Regards » et les deux revues « Repères ».
- Les revues à forme sans éditeur comptent 10 123 enregistrements sources sans éditeur. 8 795 ont un DOI dont le préfixe a un titulaire connu (`doi_prefixes.publisher_id`). `doi_prefixes` est rempli après `normalize`.
- `delete_empty_publishers` garde un éditeur désigné par une forme de nom de revue.
- La règle 3 de `merge_duplicate_serials` fusionne dans la revue son titre précédent, son titre suivant ou son supplément. 21 revues ont des enregistrements sources rattachés seulement par l'ISSN d'un tel titre : 307 enregistrements sources, 166 publications. Tous les enregistrements sources de 20 de ces publications passent par ce seul ISSN.
- La vérification Sudoc range le titre précédent (zone 430) et le titre suivant (zone 440) sous un même statut d'ISSN, `related_title`.

CRISalid, Academic Observatory et OpenAIRE identifient la revue par ses seuls ISSN ou ISSN-L, et recalculent le rattachement des publications à chaque passage ([benchmark](archived/2026-10-12_benchmark-pipelines.md)).

### Éditeurs

- Deux noms normalisés sont partagés par deux éditeurs.
- 631 publications à DOI DataCite ont un éditeur différent du titulaire du préfixe. Ce titulaire désigne parfois le même éditeur sous un autre nom :
  - « Classiques Garnier » (14001), titulaire « Librairie Classiques Garnier » (82736), préfixes `10.15122` et `10.48611` ;
  - « INRAE » (13895) et « National Research Institute for Agriculture, Food and Environment » (83482), titulaire « Institut National de Recherche pour l'Agriculture, l'Alimentation et l'Environnement » (76867).
- Des noms d'éditeur contiennent un lieu ou un directeur d'ouvrage : « Paris: Classiques Garnier » (14077), « A. Hatzenberger dir., Classiques Garnier » (84199).

### Titres de revue

OpenAlex retire les apostrophes. 106 titres de revue ont la forme « Annales d Endocrinologie », « L Encéphale », « Journal Français d Ophtalmologie ». 441 titres ont une apostrophe.

### Conteneur libre

`publications.container_title` est renseigné pour 39 690 publications, dont 10 202 à revue et 8 876 à monographie. OpenAlex y met le nom d'un repository : « HAL (Le Centre pour la Communication Scientifique Directe) » pour 28 846 de ses 52 116 enregistrements sources à conteneur, puis arXiv, theses.fr, Figshare, Zenodo.

### Plateformes typées comme revues

Sept entrées de `serials` ont un type de plateforme, pour 560 publications : `repository` (SSRN Electronic Journal, AEA Randomized Controlled Trials, Global Monitoring Laboratory) et `preprint_server` (bioRxiv, Research Square, Preprints.org, ArXiv.org). Leurs 702 enregistrements sources viennent de ScanR (598), Crossref (78) et HAL (26). Trois ont un type saisi à la main, trois ont `oa_model = repository`. SSRN, bioRxiv, Research Square, Preprints.org et arXiv figurent dans la liste des plateformes connues (`domain/platforms/registry.py`). Lecteurs des deux types : enrichissement OpenAlex (`enrich_serials_from_openalex`), correction du type de document (`preprint_server` donne `preprint`), espaces de noms DOI.

### Listes de revues

Aucune table ne rattache une revue à une liste de référence : revues indexées dans le WoS, revues de confiance recommandées par la conférence des doyens de médecine.

### Administration

Les personnes et les publications ont un volet latéral (`PersonDrawer`, `PublicationDrawer`). Les pages Éditeurs et Revues (`publishers/`, `journals/`) ouvrent une page par entité.

## Décisions

- `biblio.journal` décrit la série qui sert au rattachement : titre, identifiant OpenAlex, liste des ISSN avec leur support et l'indicateur ISSN-L.
- La revue de chaque enregistrement source se calcule à chaque passage de `publishing`, comme sa publication : composantes connexes sur les ISSN et l'identifiant OpenAlex. Deux ISSN-L distincts restent toujours séparés. L'ISSN-L vient de la vérification Sudoc.
- Un titre précédent, un titre suivant ou un supplément forme une revue distincte. Une table relie les revues par ces trois relations, lues dans le Sudoc.
- Une série sans ISSN ni identifiant OpenAlex rejoint la seule revue à ISSN de même titre et d'éditeur compatible : le même éditeur, ou un éditeur absent d'un côté. Sinon, les séries de même titre et de même éditeur forment une revue sans ISSN.
- Pour ce rattachement par titre, un enregistrement source sans éditeur reçoit le titulaire de son préfixe DOI Crossref. Le titulaire d'un préfixe DataCite est souvent un repository ou un établissement : il est exclu. `source_records.publisher_id` garde l'éditeur donné par la source.
- Une revue garde son identifiant d'un passage à l'autre. Une fusion de revues décidée dans l'administration pose un jeton de fusion, lu par le calcul.

## Phasage

### Phase 1 — Reconnaissance des revues

- [x] Contrainte `NULLS NOT DISTINCT`, dédoublonnage des formes sans éditeur (7668391c6)
- [ ] `biblio.journal` écrit d'après la série qui sert au rattachement, ISSN en liste. Lecteurs adaptés : vérification Sudoc, comparaison des sources. Reprise du stock depuis le raw store par un script ponctuel.
- [ ] Calcul des revues dans `publishing` : composantes connexes coupées par ISSN-L, rattachement par titre, identifiant conservé, redirection des revues absorbées
- [ ] Éditeur déduit du préfixe DOI Crossref pour le rattachement par titre
- [ ] Relations entre revues : titre précédent, titre suivant, supplément, lues dans le Sudoc. Liens sur la page d'une revue.
- [ ] Fusion de revues dans l'administration par jeton de fusion
- [ ] Normalisation sans recherche ni création de revue ; collection des monographies posée par `publishing`
- [ ] Retrait de `serial_name_forms`, de `find_or_create_serial` et des règles de fusion remplacées par le calcul et les relations
- [ ] Comparaison des revues avant et après sur le stock, dont les quatre titres partagés par deux revues

### Phase 2 — Éditeurs

- [ ] Doublons d'éditeurs que révèle le titulaire DataCite du préfixe
- [ ] Lieu et directeur d'ouvrage dans les noms d'éditeur
- [ ] Mesure des autres doublons d'éditeurs sous des noms différents

### Phase 3 — Revues

- [ ] Apostrophes retirées du titre par OpenAlex (+ caractère @ à conserver)
- [ ] Stocker la langue des revues?

### Phase 4 — Conteneur libre

- [ ] Usage de `container_title` à côté de `serial_id` et `monograph_id` : exploitation ou suppression de la colonne
- [ ] Noms de repository dans le `container_title` d'OpenAlex

### Phase 5 — Administration

- [ ] Volet latéral des pages Éditeurs et Revues

### Phase 6 — Listes de revues

- [ ] Modélisation : table des listes, table de liaison entre revues et listes
- [ ] Source de chaque liste (question 2)
- [ ] Mise à jour de chaque liste (question 3)

### Phase 7 — Plateformes typées comme revues

- [ ] Normaliseurs ScanR, Crossref et HAL : un conteneur désignant une plateforme connue donne une localisation au lieu d'une revue
- [ ] Lecteurs des types `repository` et `preprint_server` basculés sur les plateformes
- [ ] Stock : entrées converties en plateformes, publications détachées
- [ ] Migration : valeurs `repository` et `preprint_server` retirées de `serial_type`, valeur `repository` retirée de `oa_model`

### Phase 8 — Fin de chantier

- [ ] Mise à jour de la documentation

## Questions ouvertes

1. Règle 5 de `merge_duplicate_serials` : deux revues rattachées à des enregistrements sources d'une même publication, aux titres compatibles (« Phys.Rev.Lett. » et « Physical Review Letters »). Utile une fois la revue de chaque publication arbitrée entre ses enregistrements sources ?
2. Source de chaque liste : fichier publié par l'organisme, API ou saisie dans l'administration. Accès à la liste des revues indexées dans le WoS après la résiliation de l'abonnement.
3. Mise à jour d'une liste : import complet qui la remplace, ajouts et retraits datés, ou liste posée une fois. Rattachement d'une entrée à une revue : par ISSN, par titre à défaut. Sort des entrées sans revue dans le référentiel.
