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

`admin/structures.py` ne garde que les écritures. `laboratories.py`, son port, son adapter et ses modèles disparaissent ; le frontend garde sa route `/laboratories`, qui interroge la liste filtrée.

**Le détail réunit les deux projections plutôt que d'en garder deux.** Les formes de nom intéressent l'admin, le nombre de thèses la page publique ; aucun des deux ne coûte assez pour justifier deux endpoints. À vérifier avant de trancher : le coût du comptage de thèses sur une université.

## Phasage

### Phase 1 — inventaire

- [ ] Recenser les appels du frontend aux deux familles de routes, et ce que chaque page consomme réellement du détail.
- [ ] Mesurer le comptage de thèses et le tableau de bord sur les trois universités : la page publique n'ouvre aujourd'hui que des laboratoires.

### Phase 2 — les lectures rejoignent `/api/structures`

- [ ] `StructuresQueries` absorbe les quatre lectures de `LaboratoriesQueries` ; le détail réunit formes de nom et nombre de thèses.
- [ ] `RelatedStructureOut` absorbe `LabRelatedStructure`.
- [ ] La liste des structures accueille le filtre de périmètre et celui des types configurés.
- [ ] `laboratories.py` (router, port, adapter, modèles) disparaît ; les tests suivent.

### Phase 3 — le frontend

- [ ] Les pages `/laboratories` et `/laboratories/[id]` interrogent `/api/structures*`.
- [ ] Contrat TypeScript régénéré.

## Questions ouvertes

- **Le périmètre de la liste.** `/api/laboratories` filtre sur le périmètre `persons` et sur `laboratories_display_types` ; `/api/structures` ne filtre ni l'un ni l'autre et sert l'admin. Réunir les deux demande de décider si le filtre de périmètre est un paramètre de la requête (l'admin voit tout par défaut) ou un défaut de la route.
- **Le sort des structures sans signature.** `onr`, `site` et `admin` n'ont aucune signature rattachée : leur tableau de bord est vide et leurs sujets aussi. Un 404 sur ces types, ou une réponse vide, selon que l'endpoint se veut réservé aux structures « productrices ».
