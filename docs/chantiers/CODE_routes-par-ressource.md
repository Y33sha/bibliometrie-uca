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

**Ce chantier déplace, il ne fusionne pas.** Les endpoints qui font double emploi pour une même ressource restent en double à l'arrivée, chacun dans le module de sa ressource. Leur fusion appartient aux fiches qui la traitent : [Structures et laboratoires](CODE_structures-et-laboratoires.md) et [Projections de lecture des personnes](CODE_projections-de-lecture-des-personnes.md). Cette séparation garde le déplacement mécanique et vérifiable route par route.

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
| `perimeters.py` | `/api/perimeters` | `admin/perimeters.py` |
| `persons.py` | `/api/persons` | `persons.py` + `admin/persons.py` ; `person-identifiers` devient une sous-ressource |
| `pipeline.py` | `/api/pipeline` | `admin/pipeline_logs.py` + `admin/pipeline_phase_executions.py` |
| `publications.py` | `/api/publications` | `publications.py` ; `admin/duplicates` devient `duplicates` |
| `publishers.py` | `/api/publishers` | inchangé |
| `stats.py` | `/api/stats` | inchangé |
| `structures.py` | `/api/structures` | `admin/structures.py`, moins les formes de nom ; `structure-relations` devient `relations` |
| `subjects.py` | `/api/subjects` | inchangé |

## Phasage

### Phase 1 — Préparer le filet

- [x] Recensement croisé : 127 routes pour 118 chemins distincts, contre 112 chemins appelés par le frontend. Le croisement vaut aussi comme test « qui l'appelle » — voir *Endpoints sans appelant* ci-dessous.
- [x] Couverture d'intégration relevée : **28 chemins sur 118 ne sont nommés par aucun test d'intégration**. Ils se concentrent sur trois familles — les lectures d'administration des personnes (onze chemins : formes ambiguës, conflits d'identifiants, intrus détachables, doublons de nom, avec leurs compteurs), les lectures de laboratoire (détail, adresses, tableau de bord, sujets), et les agrégats de statistiques (collaborations, pivot et son schéma). S'y ajoutent l'authentification, que la fixture d'intégration court-circuite en forgeant le jeton au lieu d'appeler `/api/auth/login`, et quelques détails d'entité (`GET /api/publications/{id}`, `/api/persons/{id}/theses`, `/dashboard`, `/subjects`).
- [ ] Compléter la couverture des 28 chemins avant tout déplacement : un test qui nomme le chemin est ce qui fait échouer bruyamment un renommage manqué. Sans lui, une route déplacée et un frontend non ajusté produisent un 404 que rien ne signale.

#### Endpoints sans appelant

Six chemins ne sont appelés par aucun module du frontend. Le contrôle a écarté les faux positifs des chemins composés (`${base}/api/…`, `${endpoint}/entity-label`), qui sont bien consommés.

| Chemin | Ce qui semble le servir à sa place |
| --- | --- |
| `GET /api/stats/years` | la page de statistiques construit ses années autrement |
| `GET /api/addresses/suggest-countries` | la page pays passe par `/api/addresses/countries` avec le drapeau `suggest` |
| `GET /api/persons/departments` | les listes lisent les départements dans `/api/persons/facets` |
| `GET /api/persons/roles` | même chose pour les rôles |
| `GET /api/journals/oa-models` | l'énumération est publiée dans le contrat OpenAPI, et le frontend la tient du type généré |
| `DELETE /api/perimeters/{id}/structures/{structure_id}` | rien — l'interface ajoute une structure à un périmètre sans jamais l'en retirer |

Les cinq lectures sont des candidates à la suppression, à confirmer une par une. Le sixième cas est de nature différente : l'endpoint fonctionne et c'est l'interface qui est incomplète. Une fonctionnalité manquante ne se traite pas en supprimant ce qui l'aurait servie.

### Phase 2 — Adopter le préfixe par module

Sans changer aucun chemin servi, module par module : `APIRouter(prefix=..., tags=[...])`, décorateurs en chemins relatifs, enregistrement ajusté dans `app.py`. Étape purement mécanique, à contrat constant — le contrat OpenAPI régénéré ne doit montrer que l'apparition des `tags`.

- [ ] Les huit modules déjà mono-ressource et sans préfixe `/api/admin/`.
- [ ] Les modules à ressources multiples, après la scission de la phase 3.

### Phase 3 — Scinder et fusionner les modules

- [ ] `admin/addresses.py` : les pays sortent en `countries.py`.
- [ ] `admin/structures.py` : les formes de nom sortent en `name_forms.py`, les relations passent en sous-ressource de `structures`.
- [ ] `admin/pipeline_logs.py` et `admin/pipeline_phase_executions.py` fusionnent en `pipeline.py`.
- [ ] `persons.py` et `admin/persons.py` fusionnent. Le module cumulé étant le plus gros de l'API, vérifier au passage l'ordre de déclaration : les chemins littéraux (`/directory`, `/search`, `/facets`, `/stats`) doivent précéder `/{person_id}`, contrainte aujourd'hui tenue par l'ordre d'enregistrement de deux fichiers dans `app.py` — une route littérale ajoutée dans le mauvais fichier serait captée par le paramètre, en silence.
- [ ] Les modules restants remontent d'`admin/` sans autre changement ; le dossier disparaît.

### Phase 4 — Renommer les chemins

Chaque renommage se fait avec son consommateur frontend dans le même commit, contrat OpenAPI régénéré.

- [ ] `/api/admin/address-stats` → `/api/addresses/stats`.
- [ ] `/api/admin/duplicates/*` → `/api/publications/duplicates/*`.
- [ ] `/api/admin/orphan-authorships/*` → `/api/authorships/orphans/*`.
- [ ] `/api/admin/feedback/*` → `/api/feedback/*`.
- [ ] `/api/admin/pipeline/*` → `/api/pipeline/*`.
- [ ] `/api/structure-relations/*` → `/api/structures/relations/*`.
- [ ] `/api/person-identifiers/*` → sous-ressource de `/api/persons`.
- [ ] Les lectures d'administration des personnes (`/api/admin/ambiguous-name-forms`, `/api/admin/identifier-conflicts`, `/api/admin/detachable-intruders`, `/api/admin/name-duplicates`, `/api/admin/persons/{id}`) rejoignent `/api/persons/*`.
- [ ] Plus aucun chemin ne porte le segment `admin` : contrôle final sur le contrat OpenAPI régénéré.

## Questions ouvertes

- **Le sort de `/api/admin/persons/{person_id}` face à `/api/persons/{person_id}`.** Deux projections de la même ressource sous deux chemins, que ce chantier ramène dans un seul module sans les fusionner. Elles se retrouvent alors voisines, ce qui rendra visible si l'écart entre les deux est une différence de besoin ou une duplication — question qui appartient à la fiche des projections de lecture des personnes.
- **Le niveau des formes de nom.** `name_forms.py` les traite en ressource de premier rang, comme aujourd'hui, alors qu'une forme de nom n'existe que rattachée à une structure. Le rangement en sous-ressource (`/api/structures/{id}/name-forms`) se défend, mais les écritures actuelles ciblent la forme par son seul identifiant, sans passer par sa structure. À trancher en phase 3.
- **La versionnage du préfixe.** `/api/` ne porte pas de version. C'est le seul segment qui se place conventionnellement au-dessus de la ressource, et le moment de l'introduire serait celui où l'on réécrit tous les chemins. À arbitrer contre le coût : un unique consommateur, et aucune contrainte de compatibilité ascendante.
