# Projections de lecture des personnes : deux endpoints pour une entité

## Contexte

Deux endpoints listaient les personnes. `/api/persons/directory` servait l'annuaire public (page `/persons`), `/api/persons` la liste de curation (page `/admin/persons`). Chacun avait son modèle de réponse, sa dataclasse de filtres et sa requête.

Ce qui les distinguait n'était pas le public — rien de ce que la curation expose n'est confidentiel — mais trois choses de nature différente.

**Un filtre.** L'annuaire excluait les personnes rejetées, la liste de curation les incluait et exposait le drapeau. D'où deux totaux : 13 996 contre 14 012, soit 16 personnes.

**Un scope.** L'annuaire acceptait `lab_id`, qui restreint aux personnes d'un laboratoire et y restreint leur décompte. La liste de curation n'en avait pas ; en revanche elle portait un second décompte. Le même nom de champ ne comptait donc pas la même chose selon l'endpoint et selon le paramètre.

**Des champs.** La liste de curation ajoutait noms normalisés, dates de début et de fin, `rejected`, les identifiants avec leur statut et leur source, et les formes de nom avec leur état d'arbitrage.

Le coût n'expliquait pas la partition. Sur cinquante lignes, l'annuaire répondait en 17 ms, la curation en 31. Le poids divergeait davantage — 11 550 octets contre 54 445 — mais tenait à un seul bloc, `name_forms`, qui faisait 63 % de la réponse de curation sans qu'aucune ligne ne l'affiche.

## Décisions

**Les identifiants se rendent sous une seule forme, la forme plate.** `{id, id_type, id_value, source, status}` partout ; le regroupement par type et la dérivation de `confirmed` sont des gestes d'affichage, faits dans le composant qui affiche. Écarter les attributions rejetées en est un aussi, et se lit dans le même statut.

**Ce qui distingue les deux lectures, ce sont des paramètres, non des ressources.** `rejected` est un filtre, `lab_id` un scope, le reste une question de champs servis. Une fois les formes de nom sorties de la liste et les identifiants unifiés, l'écart de poids tombe de 4,7 à 1,3 et la projection complète coûte 19 125 octets contre 13 351 à la plus étroite : servir une seule projection revient moins cher que d'entretenir deux piles de lecture.

**`GET /api/persons` rend la collection.** L'annuaire public est un appel de cette lecture, avec `rejected=false` et, sur la fiche d'un laboratoire, `lab_id`. Une seule dataclasse de filtres sert la liste et ses facettes, construite par une dépendance unique : ce que l'une honore, l'autre le décompte.

## Phasage

### Phase 0 — ce qui diverge sans l'avoir voulu

Deux écarts précédaient toute question de projection, et l'ont faussée : la fiche affirmait les filtres partagés, ils ne l'étaient pas.

- [x] `search` désignait deux comportements sous un même nom : l'annuaire cherchait dans le nom et le prénom, la liste de curation y ajoutait l'adresse électronique. Le même terme ne rendait donc pas le même ensemble. Les trois lectures — annuaire, liste, facettes — partagent maintenant `person_search_clause`, aligné sur la version la plus large.
- [x] `pub_count` ne comptait pas la même chose de part et d'autre : l'annuaire compte les signatures où la personne tient le rôle d'**auteur**, la curation les compte **toutes**, jury et rapporteurs inclus. La table étant unique par paire (publication, personne), l'écart tient entièrement au rôle — et il va du simple au double sur les encadrants.

  Les deux dénombrent donc la même chose, à une condition près, et leurs noms le disent : `signature_count` pour l'ensemble, `signature_count_as_author` pour la restriction, `in_perimeter_signature_count` pour celles du périmètre. Nommer l'un `pub_count` et l'autre `signature_count` aurait laissé croire à deux natures. Les vocabulaires de tri suivent, et l'interface cesse d'afficher des signatures sous le mot « publications » — jusque dans la confirmation de fusion, qui annonçait des publications réattribuées là où toutes les signatures le sont.

  `uca_pub_count` disparaît au passage : le périmètre se nomme, il ne s'abrège pas en un établissement.

- [x] Mesure de ce que la liste de curation transporte : `name_forms` en fait 65 % (32 262 octets sur 49 904 pour cinquante personnes) et **aucune ligne ne l'affiche** — seul le tiroir d'une personne le consomme, par `PersonDrawer`. Sans lui, la liste tomberait à 17 642 octets, contre 10 424 pour l'annuaire. L'écart de projection qui motivait ce chantier tient donc pour l'essentiel à un champ que la lecture qui le porte ne montre pas.

### Phase 1 — les identifiants

- [x] `persons_directory` rend `identifiers` à plat ; `PersonDirectoryEntry` perd `orcids`, `idhals`, `idrefs`, et `ValueConfirmedOut` disparaît avec eux, sans autre porteur.
- [x] Le regroupement descend dans `IdentifiersCell`, le seul composant qui le rend, plutôt que dans un module partagé : ses deux appelants — table de l'annuaire et page profil — reçoivent la forme plate et la lui passent telle quelle.
- [x] Une troisième copie de la lecture est apparue en chemin : le profil d'une personne émettait le même SELECT que la liste de curation, au filtre de statut près. Les trois passent par `public_identifiers`, où le seul écart devient un paramètre — une attribution rejetée est écartée des lectures publiques, gardée en curation pour permettre le retour en arrière.
- [x] `identifiers` cesse d'être nullable : la lecture rend une liste vide plutôt que rien, et le client n'a plus de garde à porter.

### Phase 2 — la forme de la projection

- [x] Constat après les phases 0 et 1, sur cinquante lignes : 13 351 octets pour l'annuaire, 17 655 pour la curation, dont respectivement 4 412 et 4 315 d'identifiants. L'écart initial de 4,7 tombe à 1,3, et ce qui reste tient à quatre champs.

  Les deux lectures partagent `search`, `departments`, `roles`, `has_orcid`, `has_idhal`, `has_idref`, `has_rh`, et servent `id`, les deux noms, `role_title`, `department_name`, `has_rh`, `identifiers`. Ce qui les sépare :

  | | annuaire | curation |
  | --- | --- | --- |
  | filtres propres | `lab_id` (scope) | `has_pending_forms`, `has_pending_identifiers` |
  | personnes rejetées | exclues sans recours | incluses, sous le drapeau `rejected` |
  | dénombrement | `signature_count_as_author` | `signature_count`, `in_perimeter_signature_count` |
  | champs propres | — | `rejected`, `start_date`, `end_date` |

  Les dates ne servent qu'au tiroir d'une personne, comme les formes de nom avant elles ; elles relèvent de la lecture par personne, non de la liste.

- [x] Aucune des trois issues n'a eu à être tranchée : une fois l'écart réduit à quatre champs, la projection complète coûte 19 125 octets contre 13 351 à la plus étroite, et la fusion tombe d'elle-même. `GET /api/persons` rend la collection, `GET /api/persons/directory` disparaît, et une seule dataclasse `PersonFilters` sert la liste et ses facettes — la même dépendance FastAPI construit les deux.
- [x] `rejected` devient un filtre : omis il laisse tout passer, et l'annuaire public pose `rejected=false`. `lab_id` reste un scope, et restreint au laboratoire les trois dénombrements plutôt que le seul décompte d'auteur.
- [x] Le vocabulaire de tri est l'union des deux : les trois dénombrements sont triables, comme la fonction et le département.
- [x] Les attributions d'identifiant rejetées voyagent partout, avec leur statut ; l'affichage public les écarte à la lecture du statut, comme il en dérive déjà la confirmation. La règle d'affichage vit dans le composant qui affiche.

## Questions ouvertes

- **Les facettes de la page de curation décomptent une population plus étroite que sa liste.** Elle demande ses facettes avec `rejected=false` et sa liste sans, si bien que ses compteurs ignorent les 16 personnes rejetées que le tableau affiche. Le paramètre rend l'écart visible dans l'appel ; le retirer suffit à l'effacer, au prix d'un décompte qui bouge.

## Lien

Même motif que [Structures et laboratoires](archived/2026-07-19_CODE_structures-et-laboratoires.md), close : une entité, deux piles de lecture nées de deux pages. Elle a tranché en ramenant les lectures sous la ressource, le filtre qui les distinguait passant en paramètre — la route rend la collection, la page publique demande sa restriction.
