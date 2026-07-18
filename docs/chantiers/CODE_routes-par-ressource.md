# Routes API par ressource : supprimer le dossier `admin`

## Contexte

Les routes de l'API sont réparties entre `interfaces/api/routers/` et `interfaces/api/routers/admin/`, et une partie d'entre elles porte un préfixe d'URL `/api/admin/`. Les deux découpages sont censés dire la même chose. Ni l'un ni l'autre ne tient.

**Le dossier ne prédit pas l'URL.** Sur les dix modules d'`admin/`, quatre ne servent aucun chemin `/api/admin/` — `perimeters` sert `/api/perimeters/*`, `pipeline_config` sert `/api/config/*`, `structures` sert `/api/structures/*`, `/api/structure-relations/*` et `/api/name-forms/*`, `addresses` sert `/api/addresses/*` et `/api/countries`. Deux mélangent les deux préfixes dans le même fichier : `admin/addresses.py` ne place sous `/api/admin/` que son unique endpoint de statistiques, `admin/persons.py` répartit ses vingt-et-une routes entre `/api/persons/*`, `/api/person-identifiers/*` et `/api/admin/*`.

**Le préfixe ne prédit pas la protection.** `auth_middleware` (`interfaces/api/app.py`) filtre sur la méthode HTTP — `POST`, `PUT`, `DELETE`, `PATCH` — en exemptant `/api/auth/`. Le chemin n'intervient nulle part ailleurs. Toute lecture est donc publique, et toute écriture protégée, quels que soient le dossier et le préfixe. `/api/admin/pipeline/runs`, `/api/admin/identifier-conflicts`, `/api/admin/persons/{id}` et `/api/admin/feedback/*` se lisent sans jeton. Le préfixe annonce au lecteur du contrat OpenAPI l'inverse de ce qui s'applique.

**Le classement se fait par consommateur.** Ce qui détermine aujourd'hui le dossier d'une route, c'est la page qui l'appelle : ce qu'affiche l'interface d'administration va dans `admin/`. Une ressource se retrouve donc scindée quand deux pages la lisent différemment — `persons.py` et `admin/persons.py` servent tous deux `/api/persons/{person_id}`, sous deux chemins ; `admin/pipeline_logs.py` et `admin/pipeline_phase_executions.py` se partagent `/api/admin/pipeline/*`, l'un portant `runs/{run_id}` et l'autre `runs/{run_id}/phases/{phase}/log`. Et à l'inverse un module cumule des ressources sans rapport : `admin/structures.py` en porte trois.

Le couplage joue dans le mauvais sens : le contrat HTTP bouge quand l'interface bouge. Les doublons déjà relevés dans [Lisibilité](CODE_lisibilite.md) en sont les symptômes — `/api/persons/directory` contre `/api/persons`, `/api/laboratories/*` contre `/api/structures/*`, `/api/stats/facets/entity-label` contre son homologue de `publications` : à chaque fois, deux pages affichant la même ressource ont produit deux endpoints, qui dérivent ensuite séparément.

Ce chantier précède la fin de la relecture d'`interfaces/api/`, pour ne pas relire et corriger des fichiers qui changent de place ensuite.

## Décisions

**Une ressource, un module, un préfixe.** Les routes se rangent par ressource du métier — le nom que l'URL désigne — et non par appelant. Le fichier porte le nom de la ressource, sert tous ses chemins quelle que soit la page qui les consomme, et couvre lectures comme écritures. Le dossier `admin/` disparaît ; ses modules remontent d'un cran.

**Le contrôle d'accès sort de l'arborescence et de l'URL.** C'est une préoccupation transverse, déclarée sur l'opération, non encodée dans le chemin. Le middleware par méthode reste la règle en vigueur. La capacité de protéger une lecture précise ne se perd pas avec le préfixe : elle s'exprime par une dépendance FastAPI posée sur une route ou sur un `APIRouter`, ce qui la rend visible à l'endroit qu'elle protège au lieu de la déduire d'un segment d'URL. Ce chantier n'en pose aucune et ne change aucun comportement d'authentification.

**Le préfixe se déclare une fois par module.** Chaque router prend `APIRouter(prefix="/api/<ressource>", tags=["<ressource>"])` et ses décorateurs portent des chemins relatifs. Le préfixe cesse d'être recopié dans chacune des cent-cinquante routes, et les `tags` groupent la documentation OpenAPI, aujourd'hui une liste plate.

**Ce chantier déplace, il ne fusionne pas.** Les endpoints qui font double emploi pour une même ressource restent en double à l'arrivée, chacun dans le module de sa ressource. Leur fusion appartient aux fiches qui la traitent : [Structures et laboratoires](CODE_structures-et-laboratoires.md) et [Projections de lecture des personnes](CODE_projections-de-lecture-des-personnes.md), qui reprennent la main après. L'ordre compte dans ce sens : deux projections d'une même ressource se comparent une fois voisines dans le même module, alors que les fusionner d'abord reviendrait à trancher sur des fichiers dont la parenté ne se voit pas encore. Il garde aussi chaque déplacement mécanique et vérifiable route par route.

**Les chemins plats deviennent des sous-ressources.** `/api/admin/address-stats` désigne des statistiques d'adresses, donc `/api/addresses/stats` ; `/api/admin/duplicates/*` désigne des doublons de publications, `/api/admin/orphan-authorships/*` des signatures orphelines. Le déplacement suit le motif déjà appliqué à `/api/publisher-types`, devenu `/api/publishers/types`.

### Cible

| Module | Préfixe | Provenance |
| --- | --- | --- |
| `addresses.py` | `/api/addresses` | `admin/addresses.py`, moins les pays ; `address-stats` devient `stats` |
| `authorships.py` | `/api/authorships` | `admin/authorships.py` ; `orphan-authorships` devient `orphans` |
| `auth.py` | `/api/auth` | inchangé |
| `config.py` | `/api/config` | `admin/pipeline_config.py` |
| `countries.py` | `/api/countries` | `admin/addresses.py` |
| `feedback.py` | `/api/feedback` | `admin/feedback.py` |
| `hal_problems.py` | `/api/hal-problems` | inchangé |
| `journals.py` | `/api/journals` | inchangé |
| `laboratories.py` | `/api/laboratories` | inchangé, fusion traitée par sa fiche |
| `name_forms.py` | `/api/name-forms` | `admin/structures.py` |
| `perimeters.py` | `/api/perimeters` | `admin/perimeters.py` ; les racines se posent à la création et se réécrivent en `PUT`, sans endpoint dédié |
| `persons.py` | `/api/persons` | `persons.py` + `admin/persons.py` ; `person-identifiers` devient une sous-ressource |
| `pipeline.py` | `/api/pipeline` | `admin/pipeline_logs.py` + `admin/pipeline_phase_executions.py` |
| `publications.py` | `/api/publications` | `publications.py` + `admin/publication_duplicates.py` ; `admin/duplicates` devient `duplicates` |
| `publishers.py` | `/api/publishers` | inchangé |
| `stats.py` | `/api/stats` | inchangé |
| `structures.py` | `/api/structures` | `admin/structures.py`, moins les formes de nom ; `structure-relations` devient `relations` |
| `subjects.py` | `/api/subjects` | inchangé |

## Phasage

### Phase 1 — Préparer le filet

- [x] Recensement croisé : 127 routes pour 118 chemins distincts, contre 112 chemins appelés par le frontend. Le croisement vaut aussi comme test « qui l'appelle » — voir *Endpoints sans appelant* ci-dessous.
- [x] Couverture d'intégration relevée : **25 chemins ne sont nommés par aucun test d'intégration**. Ils se concentrent sur les lectures d'administration des personnes (onze chemins : formes ambiguës, conflits d'identifiants, intrus détachables, doublons de nom, avec leurs compteurs), les lectures de laboratoire (adresses, tableau de bord, sujets) et les agrégats de statistiques (collaborations, pivot et son schéma). S'y ajoute l'authentification, que la fixture d'intégration court-circuite en forgeant le jeton au lieu d'appeler `/api/auth/login`. Un test qui appelle une route paramétrée avec un identifiant en dur la couvre bel et bien : le rapprochement ramène les segments numériques à leur forme paramétrée, faute de quoi `GET /api/publications/{id}`, `/api/laboratories/{id}` et `/api/persons/{id}/theses` passeraient pour découverts.
La couverture se complète module par module, à l'entrée de chacun, plutôt qu'en bloc : un test qui nomme le chemin est ce qui fait échouer bruyamment un renommage manqué, et sans lui une route déplacée avec un frontend non ajusté produit un 404 que rien ne signale.

#### Endpoints sans appelant

Six chemins n'étaient appelés par aucun module du frontend. Le contrôle a écarté les faux positifs des chemins composés (`${base}/api/…`, `${endpoint}/entity-label`), qui sont bien consommés.

- [x] Cinq routes supprimées, avec leurs méthodes de port, leurs implémentations d'adaptateur et leurs tests. `GET /api/stats/years` — la page de statistiques tire ses années de `/api/stats/facets`. `GET /api/addresses/suggest-countries` — la page pays passe par `/api/addresses/countries` avec le drapeau `suggest`. `GET /api/persons/departments` et `/roles` — les deux facettes sont servies par `/api/persons/facets`, qui les porte déjà. `DELETE /api/perimeters/{id}/structures/{structure_id}` — retirer une racine se fait en réécrivant `structure_ids` par `PUT /api/perimeters/{id}`, ce que l'interface fait à chaque édition.
- [x] `GET /api/journals/oa-models` **n'était pas mort mais contourné**, et c'est le frontend qui a été corrigé. Le modal d'édition des revues codait ses trois options en dur dans son gabarit, tandis que le sélecteur voisin du même formulaire itérait les valeurs de `/api/journals/types` ; la copie avait déjà divergé, le domaine disant « Archive / dépôt » et le gabarit « Archive/dépôt ». Le modal charge les deux énumérations de la même façon.

### Phase 2 — Traiter les modules un par un

Chaque module se traite d'un bout à l'autre avant de passer au suivant, en trois temps.

1. **Couverture.** Ajouter un test d'intégration qui nomme chacun de ses chemins non couverts. C'est le filet, et il se pose avant de toucher aux chemins.
2. **Préfixe.** `APIRouter(prefix="/api/<ressource>", tags=["<ressource>"])`, décorateurs en chemins relatifs (`""` pour la racine de la collection, jamais `"/"` qui servirait une URL à barre finale), enregistrement ajusté dans `app.py`. Étape à contrat constant : le contrat OpenAPI régénéré ne doit montrer que l'apparition des `tags`.
3. **Placement.** Scission, fusion ou remontée hors d'`admin/`, puis renommage des chemins, chacun avec son consommateur frontend dans le même commit.

L'ordre part des modules sans chemin non couvert et sans scission — la mécanique s'y éprouve à risque nul — puis remonte vers ceux qui demandent des tests, et finit par les recompositions.

**Sans couverture à compléter ni recomposition**, remontée hors d'`admin/` et préfixe seulement :

- [x] `subjects` — préfixe posé, chemins et `operationId` inchangés au contrat, `tags` apparus. Le contrat TypeScript régénéré ne bouge pas d'une ligne : `openapi-typescript` n'émet pas les `tags`, qui ne servent que le groupement de la documentation.
- [x] `publishers`, `hal_problems` — mêmes contrôles, contrat inchangé.
- [x] `feedback` — `/api/admin/feedback/*` → `/api/feedback/*`.
- [x] `publications` — `admin/publication_duplicates.py` y est fondu (282 lignes réunies, bien en deçà de la taille raisonnable, et les doublons de publications sont voués à disparaître : rien ne justifie un module qui leur soit propre). `/api/admin/duplicates/*` → `/api/publications/duplicates/*`, frontend ajusté dans le même commit. `export-theses.csv` gagne au passage la couverture qui lui manquait.
- [x] `authorships` — `/api/admin/orphan-authorships/*` → `/api/authorships/orphans/*`.
- [x] `perimeters`, et `pipeline_config` renommé `config` d'après la ressource qu'il sert.

**Avec couverture à compléter :**

- [ ] `journals` — un chemin non couvert (`/api/journals/facets`).
- [ ] `auth` — deux chemins non couverts. La fixture d'intégration forge le jeton au lieu d'appeler `/api/auth/login`, donc le parcours de connexion n'est jamais exercé de bout en bout.
- [ ] `config` — `PUT /api/config/{key}` non couvert.
- [ ] `stats` — trois chemins non couverts (collaborations, pivot, schéma du pivot).
- [ ] `laboratories` — trois chemins non couverts (adresses, tableau de bord, sujets).

**Avec recomposition :**

- [x] `addresses` : le référentiel des pays sort en `countries.py` — c'est une lecture de pays, non d'adresse, et son chemin `/api/countries` le disait déjà. L'attribution des pays, elle, porte sur des adresses et reste en place. `/api/admin/address-stats` → `/api/addresses/stats` : un nom plat et préfixé `admin` qui n'évoquait plus rien devient une sous-ressource lisible.
- [x] `structures` : les formes de nom sortent en `name_forms.py`, `/api/structure-relations/*` → `/api/structures/relations/*`. Le module portait trois ressources ; il en garde deux, la structure et le lien qui la rattache, ce dernier passé en sous-ressource. Les routes de relation se déclarent avant celles qui prennent un `{structure_id}` : un segment littéral placé après serait capté par le paramètre.
- [x] `pipeline` : `admin/pipeline_logs.py` et `admin/pipeline_phase_executions.py` fusionnent ; `/api/admin/pipeline/*` → `/api/pipeline/*`. Les deux modules se partageaient déjà le préfixe, chacun renvoyant à l'autre dans son docstring — le détail d'un run vivait d'un côté, le log de ses phases de l'autre. Le module réuni distingue ce qui compte vraiment : deux lectures viennent des fichiers que l'orchestrateur laisse derrière lui, les trois autres de la base.
- [ ] `persons` : `persons.py` et `admin/persons.py` fusionnent — quatorze chemins non couverts à traiter d'abord, le plus gros lot du chantier. `/api/person-identifiers/*` devient une sous-ressource, et les lectures d'administration (`ambiguous-name-forms`, `identifier-conflicts`, `detachable-intruders`, `name-duplicates`, `admin/persons/{id}`) rejoignent `/api/persons/*`. Vérifier l'ordre de déclaration du module cumulé : les chemins littéraux (`/directory`, `/search`, `/facets`, `/stats`) doivent précéder `/{person_id}`, contrainte aujourd'hui tenue par l'ordre d'enregistrement de deux fichiers dans `app.py` — une route littérale ajoutée dans le mauvais fichier serait captée par le paramètre, en silence.

### Phase 3 — Clore

- [ ] Le dossier `interfaces/api/routers/admin/` est vide et disparaît.
- [ ] Plus aucun chemin ne porte le segment `admin` : contrôle final sur le contrat OpenAPI régénéré.
- [ ] Les fiches [Structures et laboratoires](CODE_structures-et-laboratoires.md) et [Projections de lecture des personnes](CODE_projections-de-lecture-des-personnes.md) reprennent la main : les doublons se voient mieux une fois chaque ressource rassemblée dans son module.

## Questions ouvertes

- **Le sort de `/api/admin/persons/{person_id}` face à `/api/persons/{person_id}`.** Deux projections de la même ressource sous deux chemins, que ce chantier ramène dans un seul module sans les fusionner. Elles se retrouvent alors voisines, ce qui rendra visible si l'écart entre les deux est une différence de besoin ou une duplication — question qui appartient à la fiche des projections de lecture des personnes.
- **Le niveau des formes de nom.** `name_forms.py` les traite en ressource de premier rang, comme aujourd'hui, alors qu'une forme de nom n'existe que rattachée à une structure. Le rangement en sous-ressource (`/api/structures/{id}/name-forms`) se défend, mais les écritures actuelles ciblent la forme par son seul identifiant, sans passer par sa structure. À trancher en phase 3.
- **La versionnage du préfixe.** `/api/` ne porte pas de version. C'est le seul segment qui se place conventionnellement au-dessus de la ressource, et le moment de l'introduire serait celui où l'on réécrit tous les chemins. À arbitrer contre le coût : un unique consommateur, et aucune contrainte de compatibilité ascendante.
