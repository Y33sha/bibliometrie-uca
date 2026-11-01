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
- `serial_issns` compte 18 740 lignes pour 18 736 ISSN. Un ISSN retiré d'une revue par la vérification Sudoc reste dans une ligne sans revue.
- D'après les ISSN-L des revues, 1 139 enregistrements sources donnent des ISSN de plusieurs ISSN-L, dans 449 publications : OpenAlex 542, ScanR 370, Crossref 116, HAL 90, WoS 21. Pour 1 011 d'entre eux, l'un des ISSN est celui d'un titre précédent, d'un titre suivant ou d'un supplément.

Base locale au 2026-11-01, après le rattachement par ISSN-L :

- 12 267 revues, contre 11 023 : 1 374 créées, dont 373 sans ISSN ; 130 disparues, dont 54 absorbées avec une redirection. Les quatre titres partagés par deux revues restent sur deux revues.
- Un titre précédent garde sa revue : « Physical review D Particles and fields » (0556-2821) à côté de « Physical review D » (2470-0010), « Materials in engineering » à côté de « Materials & design ». Un enregistrement source DataCite de 2022 donne l'ISSN du titre précédent de Physical Review D.
- 118 titres Sudoc sont partagés par plusieurs ISSN-L, et 60 d'entre eux ont des enregistrements sources sur deux revues. 54 opposent un ISSN papier et un ISSN électronique. Le Sudoc donne parfois un ISSN-L faux : 0093-4127, ISSN du titre précédent, pour l'ISSN papier de Journal of Comparative Psychology (0735-7036).
- 3 839 ISSN sont sans notice Sudoc, donc sans ISSN-L Sudoc. 2 734 enregistrements sources donnent un tel ISSN à côté d'ISSN d'une autre revue. Les combinaisons les plus fréquentes réunissent des revues distinctes : titres successifs (Physical Review C, INRA et INRAE productions animales), éditions (The Conversation, Australie et France).
- 812 revues sans ISSN ont des enregistrements sources. 62 ont un titre compatible avec une seule revue à ISSN : vraies variantes (« Geochim.Cosmochim.Acta ») et faux acronymes (« Act II » et « AI »). 132 ont un titre compatible avec plusieurs revues à ISSN, souvent deux revues de même titre Sudoc.
- 55 titres sont partagés par plusieurs revues sans ISSN, dont 54 collections de monographies. Les actes SciTePress se répartissent entre deux éditeurs (79458, 15030).
- Le titulaire du préfixe DOI Crossref départagerait 5 enregistrements sources rattachés par un titre de plusieurs revues à ISSN. 6 monographies ont une collection sans ISSN et aucun éditeur.

CRISalid, Academic Observatory et OpenAIRE identifient la revue par ses seuls ISSN ou ISSN-L, et recalculent le rattachement des publications à chaque passage ([benchmark](archived/2026-10-12_benchmark-pipelines.md)).

### Éditeurs

- Deux noms normalisés sont partagés par deux éditeurs.
- 631 publications à DOI DataCite ont un éditeur différent du titulaire du préfixe. Ce titulaire désigne parfois le même éditeur sous un autre nom :
  - « Classiques Garnier » (14001), titulaire « Librairie Classiques Garnier » (82736), préfixes `10.15122` et `10.48611` ;
  - « INRAE » (13895) et « National Research Institute for Agriculture, Food and Environment » (83482), titulaire « Institut National de Recherche pour l'Agriculture, l'Alimentation et l'Environnement » (76867).
- Des noms d'éditeur contiennent un lieu ou un directeur d'ouvrage : « Paris: Classiques Garnier » (14077), « A. Hatzenberger dir., Classiques Garnier » (84199).

Base locale au 2026-11-01 : 6 785 éditeurs, dont 5 698 nommés par au moins un enregistrement source. Doublons possibles, par signal :

- Même nom, formes juridiques et mots génériques retirés : 51 groupes, 108 éditeurs. « Copernicus GmbH » et « Copernicus Publ », « Brepols Publ » et « Brepols Publishers », « ISTE Group » et « ISTE ».
- Noms compatibles : 350 paires. Vrais doublons (« Presses Universitaires De France » et « Presses Univ France », « Académie des sciences (Paris) » et « ACAD SCIENCES ») et faux (« American Physiological Society » et « American Physical Society », « INRIA » et « INRA »).
- Noms emboîtés : 1 735 paires. Souvent un nom composé de deux éditeurs : « Published by Elsevier (since 2021) / Cambridge University Press », « Juris éditions, Dalloz [2013-2017] ».
- Même identifiant OpenAlex, même membre Crossref : aucun.
- Éditeurs nommés par les enregistrements sources d'une même revue à ISSN : 206 paires dans au moins 3 revues. Surtout une marque et sa maison mère : « BioMed Central » et Springer (132 revues), Birkhäuser et Springer, Lippincott Williams & Wilkins et Ovid. Parfois un doublon : « BioMed Central » et « BMC » (80 revues).
- « INSTICC » et « SCITEPRESS », éditeurs des 54 collections de monographies dédoublées, sont l'institut et sa marque d'édition.

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
- Une revue correspond à un ISSN-L.
- `serial_issns` contient une ligne par ISSN, avec son ISSN-L : celui de la table de l'ISSN International Centre, à défaut celui de l'ISSN qui l'annule d'après le Sudoc, à défaut celui d'OpenAlex, à défaut l'ISSN lui-même. La table est importée chaque mois et omet les ISSN annulés. Le Sudoc donne le titre, le support, le statut et les liens entre ISSN. La colonne `serial_id` est calculée.
- Une table relie les ISSN, une ligne par lien : titre précédent vers titre suivant, revue principale vers supplément. Un titre précédent, un titre suivant ou un supplément forme une revue distincte.
- À chaque passage de `publishing`, un enregistrement source est rattaché à la revue de l'ISSN-L de ses ISSN, à défaut à la revue de son identifiant OpenAlex.
- Un enregistrement source dont les ISSN mènent à plusieurs ISSN-L rejoint la seule revue de même titre normalisé, à défaut la seule revue de titre compatible (`compatible_titles`). Sinon, il reste sans revue par ISSN.
- Une seule fonction renvoie la revue d'un ISSN-L, créée au besoin. Le rattachement et la vérification Sudoc l'appellent tous deux.
- Titre d'une revue : celui saisi à la main, sinon celui de la notice Sudoc de son ISSN-L, sinon le plus fréquent parmi ses enregistrements sources. `serial_issns.sudoc_title` garde le titre de la notice Sudoc de chaque ISSN. Une revue vide reste quand l'un de ses ISSN est cité par la série d'un enregistrement source, ou relié à un titre précédent, suivant ou à un supplément.
- Identifiant OpenAlex d'une revue : celui des enregistrements sources OpenAlex dont l'ISSN-L, d'après OpenAlex, est celui de la revue. Modèle OA : celui d'OpenAlex pour cette source, sauf saisie à la main.
- Une série sans ISSN ni identifiant OpenAlex rejoint la seule revue à ISSN de même titre, quel que soit son éditeur. L'éditeur départage plusieurs revues à ISSN de même titre. À défaut, elle rejoint la seule revue à ISSN de titre compatible parmi celles des autres enregistrements sources de sa publication (« JHEP »). La publication est celle du run précédent. Sinon, les séries de même titre forment une revue sans ISSN.
- Une revue sans ISSN est identifiée par son titre normalisé : chaque source nomme l'éditeur à sa façon (« Edition CdP », « Editions CdP »). Une collection de monographies sans ISSN est identifiée par son titre et son éditeur : les noms de collection génériques (« Essais ») sont fréquents.
- Deux revues de même ISSN-L fusionnent : la revue vide est absorbée, avec une redirection.
- L'administration modifie le titre, le type et le modèle OA d'une revue. Les ISSN sont en lecture seule.
- Une série qui désigne une plateforme est écartée à la normalisation : source OpenAlex de la liste des plateformes connues (Cairn.info), ou titre qui nomme le serveur de preprints du DOI du document (« SSRN Electronic Journal »). La série d'une vraie revue reste, même sous un DOI de serveur de preprints.
- Un enregistrement source sans revue, dont les DOI sont tous ceux d'un serveur de preprints, passe de « article » ou « autre » à « preprint ».
- `serial_type` perd `repository` et `preprint_server`, `oa_model` perd `repository`. Les revues de ces types passent au type inconnu.
- L'administration fusionne une revue sans ISSN dans une autre revue. Une table titre normalisé → revue garde la décision, et le rattachement par titre la consulte. La fusion de deux revues à ISSN-L est refusée.
- Deux éditeurs de même nom, aux formes juridiques et aux mots génériques près, fusionnent. L'éditeur gardé est le seul titulaire de préfixe DOI du groupe, à défaut le plus nommé par les enregistrements sources. Un groupe à plusieurs titulaires de préfixe, ou de nom réduit à un mot courant (« Academic »), reste en l'état.

## Phasage

### Phase 1 — Reconnaissance des revues

- [x] Contrainte `NULLS NOT DISTINCT`, dédoublonnage des formes sans éditeur (7668391c6)
- [x] `biblio.journal` écrit d'après la série qui sert au rattachement, ISSN en liste. Lecteurs adaptés : vérification Sudoc, comparaison des sources. Migration du format sur toutes les bases (773670312, a3be1805f)
- [x] Reprise du contenu des séries depuis le raw store (`rewrite_biblio_journal`)
- [x] `serial_issns` : une ligne par ISSN, colonne `issnl`, table des liens entre ISSN. Vérification Sudoc ISSN par ISSN (27f9ef446)
- [x] Rattachement des enregistrements sources dans `publishing` : ISSN-L, identifiant OpenAlex, titre. Fusion des revues de même ISSN-L. Titre, identifiant OpenAlex et modèle OA de chaque revue (27f9ef446)
- [x] Rattachement par titre : titre identique avant titre compatible parmi plusieurs ISSN-L, revue sans ISSN identifiée par son titre seul, décisions de l'administration par titre (ba79befd1)
- [x] Titre seul rattaché à la revue à ISSN d'un autre enregistrement source de la publication (b2ecf4014)
- [x] Revue à ISSN gardée même vide, revérification Sudoc de tous les ISSN (5474a9263)
- [x] Titre de chaque revue d'après la notice Sudoc de son ISSN-L, gardée par ISSN (816a520de)
- [x] Relations entre revues déduites des liens entre ISSN. Liens sur la page d'une revue (035cdf8f6)
- [x] Administration : ISSN en lecture seule, fusion limitée aux revues sans ISSN et gardée dans la table des titres (27f9ef446)
- [x] Normalisation sans recherche ni création de revue. Collection sans ISSN des monographies : revue sans ISSN de son titre et de son éditeur (27f9ef446)
- [x] Retrait de `serial_name_forms`, de `find_or_create_serial` et des règles de fusion remplacées par le calcul et les relations (27f9ef446)
- [x] Comparaison des revues avant et après sur le stock, dont les quatre titres partagés par deux revues et les titres de Materials & Design (67208, 106232) et de Physical Review D (9, 106629)
- [x] Mesure des ISSN-L distincts de même titre Sudoc : « Perspectives médiévales », 0338-2338 et 2103-6527
- [x] Mesure des ISSN sans ISSN-L donnés ensemble par un même enregistrement source
- [x] Mesure des séries sans ISSN de titre compatible avec une revue à ISSN, sans autre enregistrement source de leur publication rattaché à cette revue
- [x] Mesure des collections sans ISSN des monographies réparties entre plusieurs éditeurs
- [x] ISSN-L lu dans la table de l'ISSN International Centre, importée chaque mois ; le Sudoc garde le titre, le support, le statut et les liens (f56521a60)
- [x] ISSN annulé lié à l'ISSN qui l'annule, dont il prend l'ISSN-L (c71b4a7c7)
- [x] Revue vide à ISSN supprimée quand aucun de ses ISSN n'est cité ni relié (c3b44143c)

### Phase 2 — Éditeurs

- [ ] Doublons d'éditeurs que révèle le titulaire DataCite du préfixe
- [ ] Lieu et directeur d'ouvrage dans les noms d'éditeur
- [x] Mesure des autres doublons d'éditeurs sous des noms différents
- [x] Fusion des éditeurs de même nom aux formes juridiques et mots génériques près (2a553667a)

### Phase 4 — Conteneur libre

- [ ] Usage de `container_title` à côté de `serial_id` et `monograph_id` : exploitation ou suppression de la colonne
- [ ] Noms de repository dans le `container_title` d'OpenAlex

### Phase 5 — Administration

- [ ] Volet latéral des pages Éditeurs et Revues

### Phase 6 — Listes de revues

- [ ] Modélisation : table des listes, table de liaison entre revues et listes
- [ ] Source de chaque liste (question 1)
- [ ] Mise à jour de chaque liste (question 2)

### Phase 7 — Plateformes typées comme revues

- [x] Normalisation : série qui désigne une plateforme écartée ; DOI d'un serveur de preprints donnant une copie sur ce serveur (67c1b73ef, e4898057b)
- [x] Type « preprint » d'après le DOI de serveur de preprints ; types `repository` et `preprint_server` retirés des lecteurs (67c1b73ef)
- [x] Stock : séries de plateforme retirées, copies déduites du DOI (`apply_platform_rules`, e4898057b)
- [x] Migration : valeurs `repository` et `preprint_server` retirées de `serial_type`, valeur `repository` retirée de `oa_model` (67c1b73ef)

### Phase 8 — Fin de chantier

- [ ] Mise à jour de la documentation

## Questions ouvertes

1. Source de chaque liste : fichier publié par l'organisme, API ou saisie dans l'administration. Accès à la liste des revues indexées dans le WoS après la résiliation de l'abonnement.
2. Mise à jour d'une liste : import complet qui la remplace, ajouts et retraits datés, ou liste posée une fois. Rattachement d'une entrée à une revue : par ISSN, par titre à défaut. Sort des entrées sans revue dans le référentiel.
3. Marques et maisons mères : « BioMed Central » et Springer, « SCITEPRESS » et INSTICC. Éditeurs distincts, éditeur unique, ou marque reliée à sa maison mère.
