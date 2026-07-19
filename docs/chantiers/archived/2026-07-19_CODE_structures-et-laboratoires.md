# Structures et laboratoires : une entité, deux piles de lecture

## Contexte

Un laboratoire est une structure dont le `structure_type` vaut `labo`. Le domaine ne connaît que `Structure` ; il n'existe ni entité ni agrégat `Laboratory`. L'API, elle, expose deux familles de routes de lecture pour cette entité unique.

`/api/laboratories/*` sert la page publique : la liste, le détail, les adresses, les sujets et le tableau de bord. `/api/structures/*` sert l'admin : la liste, le détail, et les écritures (création, édition, suppression, relations, formes de nom). Le nom `laboratories` vient de la route frontend `/laboratories`, qui affiche une liste de laboratoires.

**Les lectures « labo » ne sont pas propres aux laboratoires.** Aucune ne filtre sur le type. `get_laboratory`, `get_laboratory_addresses`, `get_laboratory_subjects` et `get_laboratory_dashboard` prennent un identifiant de structure et filtrent sur `authorship_structures.structure_id`, que la détection d'adresse alimente sans regarder le type. L'identifiant d'une université rend donc un détail, un tableau de bord et des sujets — pleins, et exacts :

| type | structures | signatures rattachées |
| --- | --- | --- |
| `labo` | 40 | 144 717 |
| `universite` | 3 | 138 270 |
| `ecole` | 7 | 23 051 |
| `chu` | 1 | 21 725 |
| `autre` | 1 | 1 979 |
| `onr`, `site`, `admin` | 10 | 0 |

Seule la **liste** est propre aux laboratoires, et par filtrage : périmètre `persons`, plus les types que porte la configuration `laboratories_display_types`. C'est une requête sur les structures, non une ressource distincte.

Le coût de cette partition est la duplication. Deux détails coexistent pour la même entité :

| | `/api/structures/{id}` | `/api/laboratories/{id}` |
| --- | --- | --- |
| `structure`, `parents`, `children` | oui | oui |
| formes de nom | oui | — |
| nombre de thèses | — | oui |

Et deux jeux de modèles : `StructureDetailResponse` / `LaboratoryDetailResponse`, `RelatedStructureOut` / `LabRelatedStructure` — dont le port dit lui-même qu'ils ne diffèrent que par `code` et `relation_id`. Deux ports (`StructuresQueries`, `LaboratoriesQueries`), deux adapters, deux jeux de tests.

Le router public annonce par ailleurs ce qu'il ne tient pas : `/api/laboratories/{id}` sur une université répond 200 sous le titre « profil public d'un laboratoire », et son 404 ne tombe que sur une structure inexistante.

## Décisions

**Les routes nomment les entités, non les pages.** Le frontend est un client parmi d'autres, et ses routes suivent une logique de navigation qui lui appartient : `/laboratories` est une page, pas une ressource. Le test n'est pas « entité contre interface » — une vue filtrée peut légitimement avoir son endpoint —, mais : cette route introduit-elle une seconde pile de lecture pour une entité qui en a déjà une ? Ici, oui.

Les lectures se rejoignent sous `/api/structures/*`, qui portent l'entité :

- `/api/structures/{id}` — le détail, réunion des deux : identifiants, parents, enfants, formes de nom, nombre de thèses.
- `/api/structures/{id}/addresses`, `/subjects`, `/dashboard` — les trois sous-ressources, telles quelles.
- `/api/structures` — la liste, avec ses filtres : type, texte, et le périmètre que `/api/laboratories` applique aujourd'hui.

`structures.py` accueille ces lectures auprès de ses écritures. `laboratories.py`, son port, son adapter et ses modèles disparaissent ; le frontend garde sa route `/laboratories`, qui interroge la liste filtrée.

**Le détail réunit les deux projections plutôt que d'en garder deux.** Les formes de nom intéressent l'admin, le nombre de thèses la page publique ; aucun des deux ne coûte assez pour justifier deux endpoints. À vérifier avant de trancher : le coût du comptage de thèses sur une université.

## Phasage

### Phase 1 — inventaire

- [x] Appels du frontend. `/api/laboratories` sert deux pages et rien d'autre : la liste `/laboratories`, et la fiche `/laboratories/[id]` qui consomme les quatre lectures — détail, adresses, tableau de bord, sujets. `/api/structures` sert trois pages d'administration (liste des structures, fiche d'une structure, sélecteur de périmètre dans la configuration) et le sélecteur de structure de la page des adresses ; ses écritures passent par `lib/api/structures.ts`. Aucune page n'appelle les deux familles.
- [x] Coût sur une université. Il suit le volume de signatures, non le type : sur l'Université Clermont Auvergne (141 442 signatures), le détail répond en 286 ms, le tableau de bord en 1 135 ms, les sujets en 408 ms — contre 86, 598 et 119 ms sur le plus gros laboratoire (30 206 signatures). Le comptage de thèses seul y prend 88 ms, moins que sur un laboratoire moyen. Rien n'y fait obstacle : la lenteur du tableau de bord est proportionnelle au volume et préexiste à toute fusion.

  Le découpage des routes a bougé depuis la rédaction : `interfaces/api/routers/structures.py` porte lectures et écritures, `name_forms.py` a pris les formes de nom, et le dossier `admin/` n'existe plus.

### Phase 2 — les lectures rejoignent `/api/structures`

- [x] `StructuresQueries` absorbe les quatre lectures de `LaboratoriesQueries` ; le détail réunit formes de nom et nombre de thèses.
- [x] `RelatedStructureOut` absorbe `LabRelatedStructure`, et sert aussi les tutelles de la liste.
- [x] La liste accueille `in_perimeter` et un `type` multi-valué. Le périmètre est un paramètre, non un défaut : une route de collection rend la collection, et c'est à la page publique de demander sa restriction — non à l'administration de lever une restriction qu'elle n'a pas posée.
- [x] `laboratories.py` (router, port, adapter, modèles) disparaît ; les tests suivent.

### Phase 3 — le frontend

- [x] Les pages `/laboratories` et `/laboratories/[id]` interrogent `/api/structures*`, contrat TypeScript régénéré.
- [x] Les types affichés viennent de la configuration, que la page lit désormais elle-même. Il a fallu pour cela que `GET /api/config` redevienne lisible sans session, restreint à une liste blanche de clés : la table mêle des réglages d'exploitation et les identifiants d'accès aux sources, et c'est ce mélange qui avait rendu sa lecture entière réservée. Une clé absente de la liste reste privée par défaut.

  Un test se perd au passage : celui qui vérifiait que la configuration pilote les types affichés. Ce lien vit maintenant dans la page, où seul le typage le couvre. Les tests de la requête attestent le filtrage par types, non son alimentation.

## Lien

Même motif que [Projections de lecture des personnes](CODE_projections-de-lecture-des-personnes.md) : une entité, deux piles de lecture nées de deux pages. Les deux fiches se tranchent ensemble ou pas du tout — la réponse à l'une vaut réponse à l'autre.

## État à la clôture

Une entité, une pile de lecture. `/api/structures` porte la liste, le détail et les trois sous-ressources ; le router, le port, l'adaptateur et les six modèles de `laboratories` ont disparu, pour 312 lignes de moins. Les pages `/laboratories` du frontend restent, et interrogent la ressource.

Les deux questions ouvertes sont tranchées. Le périmètre est un paramètre de la requête : la route rend la collection, la page publique demande sa restriction. Et les structures sans signature rendent des agrégats vides plutôt qu'un 404 — la route porte les structures, non les seules productrices.
