# Administration intégrée au site, navigation entre entités liées

## Contexte

**Deux barres de navigation.** Le layout racine (`routes/+layout.svelte`) affiche la barre d'administration sous `/admin`, la barre publique ailleurs. Le lien « Admin » mène toujours à `admin/pipeline`, le lien « Public » à `stats`, quelle que soit la page de départ. La page de connexion mène à `admin/addresses`.

**Vérification de session dispersée.** `admin/+layout.svelte` interroge `/api/auth/check` et renvoie vers la connexion faute de session. La fiche publique d'une personne (`persons/[id]`) fait son propre appel pour afficher le bouton d'exclusion d'une contribution.

**Pages d'administration doublant une page publique.**

- `admin/publishers`, `admin/serials` et `admin/monographs` reprennent les listes publiques (`PublishersListView`, `SerialsListView`, `MonographsListView`), avec une cellule d'actions Modifier / Fusionner.
- `admin/publications` reprend `PublicationsListView`, avec un volet droit (`?publication=<id>`).
- `admin/persons` réécrit la liste des personnes à côté de `PersonsListView` : filtres, facettes et synchronisation avec l'URL. Ses facettes propres : exclusion, formes de nom et identifiants à confirmer.
- Une structure a deux pages de détail : `admin/structures/[id]` (édition, tutelles, formes de nom) et `laboratories/[id]` (dashboard, listes, collaborations, adresses).

**Files de triage.** Les référentiels d'administration comportent des onglets à compteur (`HubTabs`) :

- personnes : formes ambiguës, conflits d'identifiant, doublons par nom ;
- publications : fusions suspectes ;
- publications en série : doublons, conflits de préfixe DOI, actes probables, groupes.

Les contributions orphelines ont leur page (`admin/orphan-contributions`), signalée par un bandeau dans `admin/persons`.

**Comptes.** Un seul compte, déclaré dans les réglages (`settings.admin_user`). Le cookie de session contient son nom (`interfaces/api/session.py`). Le middleware `auth_middleware` exige la session pour toute écriture. Les lectures sont publiques, sauf une partie de la configuration. Le journal d'audit enregistre le nom de l'utilisateur.

**Listes d'entités liées en onglets.** Chaque fiche d'entité intègre les listes des entités liées :

| Fiche | Onglets |
|---|---|
| Laboratoire | Dashboard, Publications, Thèses, Personnes, Collaborations, Adresses |
| Personne | Dashboard, Publications, Thèses, Adresses |
| Éditeur | Dashboard, Revues, Monographies, Publications |
| Sujet | Sujets associés, Publications |

Dans un onglet, l'entité de la fiche est un filtre fixe, sans contrôle (`fixed` dans `filterRegistry.ts`). Les filtres des onglets Personnes et Thèses du laboratoire et de l'onglet Publications du sujet sont absents de l'URL (`urlSync={false}`) : le retour depuis une fiche les perd. Par défaut, la liste générale des publications retient les seuls types de la famille « Publications » (`restrictToPublications`), les onglets tous les types. Pour le LMBP : 2 555 publications dans `/publications?lab_id=205`, 3 468 dans l'onglet. La liste générale des publications lit tous ses filtres dans l'URL : `/publications?lab_id=…&subject_id=…` fonctionne. La liste des personnes reçoit le laboratoire par le composant parent seulement.

**Fonctions liées à un contexte.** L'onglet Publications d'un laboratoire comporte la colonne et la facette « Statut HAL », calculées d'après la collection HAL du laboratoire. L'onglet Publications d'une personne comporte la colonne et la facette « Auteur correspondant », la facette du périmètre et l'exclusion d'une contribution.

## Décisions

- **L'administration est un état de la session.** Un seul site. Les pages communes ajoutent leurs fonctions d'administration quand l'utilisateur de la session a le rôle admin. Les pages propres à l'administration (pipeline, configuration, adresses, pays, files de triage) restent des pages à part, dans la même barre de navigation.
- **Comptes : `users`, `roles`, `user_roles`.** La table `users` liste les utilisateurs autorisés. Les rôles sont propres à l'application. La session désigne l'utilisateur. Les droits viennent de ses rôles.
- **Une page par structure**, sous la route `structures/[id]`. Un onglet « Gestion », réservé à l'admin, comporte l'édition, les tutelles et les formes de nom. Les libellés publics (« Laboratoires », « Chercheurs ») sont indépendants des routes.
- **Volet d'édition ouvert par une icône** sur la ligne. Le titre ou le nom mène à la fiche.
- **`admin/persons` repose sur `PersonsListView`**, enrichie des facettes d'administration.
- **Files de triage en onglets de la liste publique**, affichés selon le rôle. Le bandeau des contributions orphelines suit la même règle.
- **Restrictions publiques en facettes.** Chaque restriction de la liste publique devient une facette réglée par défaut, que la session admin peut retirer : éditeurs et publications en série sans publication, personnes exclues, inactives ou absentes de la base RH.
- **Une seule liste des structures**, sous la route `structures`, avec une facette de type réglée par défaut sur les laboratoires.
- **Éditeurs et publications en série** : les actions Modifier et Fusionner restent dans la cellule d'actions, affichée selon le rôle.
- Pas de redirection des routes supprimées.
- **« Publications en série »** est le libellé de la liste et de la fiche, session ouverte ou non. La liste comporte des actes, des médias et des serveurs de preprints.

## Phasage

### 1. Comptes et rôles

- [x] Tables `users`, `roles`, `user_roles` ; premier utilisateur admin déclaré dans les réglages (c74e9350c)
- [x] Session contenant l'identifiant de l'utilisateur ; garde des écritures qui exige le rôle admin (c74e9350c)
- [x] `/api/auth/check` rend l'utilisateur et ses rôles (c74e9350c)

### 2. Session et navigation

- [x] État de session lu une fois dans le layout racine et partagé, à la place des appels de `admin/+layout.svelte` et de `persons/[id]` (d8d6c273d)
- [x] Une seule barre de navigation ; entrées d'administration affichées selon le rôle ; suppression des liens « Admin » et « Public » (d8d6c273d)
- [x] Retour à la page de départ après connexion (d8d6c273d)

### 3. Référentiels communs

#### 3a. Monographies

- [x] Suppression de `admin/monographs`, doublon de la page publique

#### 3b. Éditeurs

- [x] Cellule d'actions selon le rôle sur la page publique ; facette des éditeurs sans publication ; suppression de `admin/publishers`

#### 3c. Publications en série

- [x] Cellule d'actions selon le rôle sur la page publique ; facette des publications en série sans publication ; files de triage en onglets ; suppression de `admin/serials`

#### 3d. Publications

- [x] Icône de volet sur la ligne ; onglet « Fusions suspectes » selon le rôle ; suppression de `admin/publications`

#### 3e. Structures

- [x] Route `structures/[id]` et onglet « Gestion » ; suppression de `admin/structures/[id]` et de `laboratories/[id]`
- [ ] Liste unique sous `structures`, facette de type, création de structure selon le rôle ; suppression de `admin/structures` et de `laboratories`

#### 3f. Personnes

- [ ] `PersonsListView` : facettes d'administration, colonne du périmètre, icône de volet, onglets de triage, bandeau des contributions orphelines ; suppression de la réécriture de `admin/persons`

### 4. Listes d'entités liées

- [ ] Trancher entre onglets et renvoi vers la liste générale filtrée (voir Questions ouvertes)

## Questions ouvertes

- **Listes d'entités liées.** Piste : la fiche garde ce qui caractérise l'entité (en-tête, dashboard, graphe des sujets, collaborations, adresses). Les listes liées deviennent des liens vers la liste générale filtrée, filtre visible et supprimable. La liste générale propose les fonctions liées à un contexte quand ce contexte est seul sélectionné : statut HAL pour un seul laboratoire, correspondance, périmètre et exclusion pour une seule personne. La même règle dirait quels filtres la page Statistiques reçoit de la liste ([Statistiques](METIER_statistiques.md)). Coût : la liste générale affiche l'en-tête de la liste, et l'en-tête de l'entité disparaît ; un bandeau de contexte peut le remplacer.
- **Lectures réservées.** Les files de triage et les volets d'édition exigent-ils le rôle admin en lecture ?
- **Repère visuel du mode admin.** La barre d'administration a sa couleur (`--nav-admin`). La garder pour la session ouverte, ou signaler la session autrement.
- **Vocabulaire des listes.** Un libellé par liste, session ouverte ou non : « Labos » ou « Structures », « Chercheurs » ou « Personnes ».
- **Comptes** : page de gestion des utilisateurs, rôles autres qu'admin.
