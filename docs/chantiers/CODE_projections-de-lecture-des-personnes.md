# Projections de lecture des personnes : deux endpoints pour une entité

## Contexte

Deux endpoints listent les personnes. `/api/persons/directory` sert l'annuaire public (page `/persons`), `/api/persons` sert la liste admin (page `/admin/persons`). Chacun a son modèle de réponse, sa dataclasse de filtres et sa requête.

Ce qui les distingue n'est pas le public — rien de ce que l'admin expose n'est confidentiel — mais trois choses de nature différente.

**Un filtre.** L'annuaire exclut les personnes rejetées (`p.rejected = FALSE`), la liste admin les inclut et expose le drapeau. D'où deux totaux : 14 419 contre 14 435, soit 16 personnes.

**Un scope.** L'annuaire accepte `lab_id`, qui restreint aux personnes d'un laboratoire et scope leur `pub_count` à ce laboratoire. La liste admin n'en a pas ; en revanche elle porte `uca_pub_count` en plus du `pub_count` global. Le même nom de champ ne compte donc pas la même chose selon l'endpoint et selon le paramètre.

**Des champs.** La liste admin ajoute noms normalisés, dates de début et de fin, `rejected`, `uca_pub_count`, les identifiants avec leur statut et leur source, et les formes de nom avec leur état d'arbitrage.

Le coût n'explique pas la partition. Sur cinquante lignes, l'annuaire répond en 17 ms, l'admin en 31. Le poids diverge davantage — 11 550 octets contre 54 445 — mais il tient à un seul bloc :

| bloc | octets / 50 lignes |
| --- | --- |
| annuaire, identifiants groupés | 4 386 |
| admin, identifiants à plat | 5 630 |
| admin, `name_forms` | 34 101 |

`name_forms` fait 63 % de la réponse admin. Les identifiants, eux, coûtent 1 244 octets de plus à plat que groupés — 25 octets par personne.

**Les identifiants sont rendus sous deux formes pour rien.** L'admin rend `{id, id_type, id_value, source, status}` à plat ; l'annuaire rend `orcids`, `idhals`, `idrefs`, chacun réduit à `{value, confirmed}`, où `confirmed` vaut `status IN ('confirmed', 'authenticated')`. Cette dérivation est écrite en SQL dans l'annuaire (trois `json_agg`) et en TypeScript dans la page profil, qui reçoit la forme plate et fait le même travail. Le profil prouve que le client sait consommer la forme plate.

## Décisions

**Les identifiants se rendent sous une seule forme, la forme plate.** `{id, id_type, id_value, source, status}` partout ; le regroupement par type et la dérivation de `confirmed` sont des gestes d'affichage, que la page profil fait déjà. Les trois `json_agg` de l'annuaire disparaissent avec la règle qu'ils dupliquent. Le surcoût est de 25 octets par personne.

**Ce qui distingue les deux lectures, ce sont des paramètres, non des ressources.** `rejected` est un filtre, `lab_id` un scope. Le reste est une question de champs servis.

**Reste à trancher la forme de la projection.** Trois issues, dont aucune n'est gratuite :

- *Servir la projection complète.* Un modèle unique et statique ; l'annuaire reçoit `name_forms` sans les afficher, et sa réponse quintuple.
- *Un paramètre de projection.* Un endpoint, deux formes ; le contrat rend une union et le typage statique s'émousse là où il est fort aujourd'hui.
- *Deux endpoints assumés.* Deux projections d'une même ressource, dont la duplication restante est celle des mécaniques de liste — comptage, pagination, tri —, les filtres étant désormais partagés.

Le choix engage le contrat public et le frontend.

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

- [ ] Trancher entre les trois issues.
- [ ] `rejected` devient un filtre de la lecture ; `lab_id` reste un scope.
- [ ] Selon l'issue : fusion des deux endpoints, ou énoncé de ce qui justifie leur séparation.

## Questions ouvertes

- **Le sens de `pub_count`.** Il compte les publications du laboratoire quand `lab_id` est posé, toutes sinon ; et l'admin porte en plus `uca_pub_count`. Trois décomptes sous deux noms — à clarifier avant de fusionner quoi que ce soit.
- **La duplication des mécaniques de liste.** `persons_directory` et `list_persons` émettent la même requête de comptage, au caractère près. Elle se factorise indépendamment de l'issue retenue.

## Lien

Même motif que [Structures et laboratoires](archived/2026-07-19_CODE_structures-et-laboratoires.md), close : une entité, deux piles de lecture nées de deux pages. Elle a tranché en ramenant les lectures sous la ressource, le filtre qui les distinguait passant en paramètre — la route rend la collection, la page publique demande sa restriction.
