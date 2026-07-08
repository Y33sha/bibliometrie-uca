# Chantier — Personnes : résolution d'identité ordre-indépendante

Commencé le 2026-07-04 - Terminé le 2026-07-08

Rendre le résultat de la phase personnes indépendant de l'ordre d'ingestion. Le geste tient en une idée, appliquée à deux canaux : remplacer la décision prise au moment où une signature arrive (« à quelle personne l'attacher ? ») par une réinitialisation des attributions dérivées, suivie d'un recalcul depuis le snapshot. L'ordre-indépendance vient de là — recalculer depuis l'agrégat plutôt que trancher à l'arrivée sans jamais revenir dessus.

## Contexte

### Deux douleurs d'ordre-dépendance

La phase personnes parcourt les `source_authorships` sans `person_id` et tranche chaque rattachement à l'arrivée. Une entité créée n'est jamais remise en jeu. Deux symptômes en découlent :

- **Regroupement nominal dépendant de l'ordre.** Une forme réduite (« j martin ») arrivée avant sa forme pleine crée sa propre personne ; « jean martin » rencontrée ensuite en crée une seconde (sous-regroupement). Une forme ambiguë (« h chanal ») arrivée avant l'homonyme qui la départage se colle au seul candidat présent, et rien ne revient dessus (sur-regroupement). Une même personne aboutit à une ou deux fiches selon la séquence.
- **Capture d'identifiant (premier arrivé).** La première signature portant une valeur d'identifiant fort en fixe l'attribution, figée par `UNIQUE (id_type, id_value)`. Si cette première est corrompue (identifiant recopié sur le mauvais co-auteur), les signatures correctes suivantes échouent à la corroboration de nom et s'éparpillent en doublons ; l'identifiant reste collé à la mauvaise personne.

### Deux canaux de nature opposée

- **Canal nominal** — non transitif, ambigu. La forme de nom est sur toutes les signatures mais n'est pas une relation d'équivalence : une forme réduite (« j smith ») relierait par transitivité des personnes distinctes (« john smith », « jane smith »). Il se résout par match de forme avec garde d'ambiguïté — une forme qui désigne plusieurs personnes reste orpheline —, jamais en graphe de noms.
- **Canal identifiant** — fonctionnel par valeur. Une valeur d'identifiant fort désigne une personne ; l'attribution correcte se lit par consensus des porteurs de la valeur, entre des personnes qui existent déjà.

### Le noyau, lu en entrée fixe

Le recalcul lit le noyau curé et ne le surcharge jamais : signatures épinglées à une personne par résolution admin (`confirmed_authorships`), cannot-link (`distinct_persons`, et le référentiel RH — deux personnes portant chacune une notice `persons_rh` sont distinctes par construction, l'identité étant résolue au niveau institutionnel ; la contrainte `ON DELETE RESTRICT` interdit d'ailleurs de supprimer une personne RH), formes de nom `confirmed`/`rejected`, paires `(publication, personne)` rejetées, identifiants `confirmed`/`authenticated`. Tout le reste est recalculé.

Une personne purement nominale (aucun identifiant, aucune curation) ne porte aucune référence externe : son `person_id` peut changer d'un run à l'autre sans rien casser. Dès qu'elle acquiert de la curation — un épinglage, une forme confirmée, une marque de distinction —, elle devient ancrée et le noyau la protège. D'où l'absence de tout appareil de stabilité d'étiquette : il ne servirait qu'à protéger une curation que le noyau protège déjà.

## Décisions

- **Le geste commun : réinitialiser puis recalculer depuis le snapshot.** Chaque canal remet à zéro ses attributions **dérivées** (celles qu'aucune curation ne fixe) et les recalcule depuis un agrégat du snapshot, insensible à la séquence. Une colonne `resolution_mode` (`identifier` / `name` / `cross_source`, NULL si orpheline) sur `source_authorships` enregistre par quel canal chaque `person_id` a été posé ; elle porte les trois réinitialisations. Les signatures épinglées et les personnes curées sont des entrées, jamais réinitialisées.

- **Canal identifiant : corroboration, puis arbitrage des conflits par consensus en tête de phase.** Un match par identifiant exige que le nom de la signature soit compatible avec le propriétaire de la valeur — `same_person_name`, tolérante aux variantes de graphie du propriétaire lui-même (concaténation « abdel mouhcine »/« abdelmouhcine », particule accolée, typo, transposition) — pour qu'une variante corrobore et se rattache directement au propriétaire au lieu de créer un doublon ; l'homonyme de patronyme et le porteur étranger restent rejetés, le rejet étant journalisé. Un **conflit** — une valeur dont les signatures porteuses désignent au moins deux personnes existantes, ou dont le propriétaire n'est pas celui que soutient la majorité — est arbitré par le **consensus** : l'`author_name_normalized` majoritaire des porteurs (pondéré au nombre de signatures, jamais le premier arrivé) désigne, parmi les candidats, la personne vers qui la valeur revient (`form_matches_person` : compatible avec le nom-prénom canonique ou une forme de nom `confirmed` — les formes `pending`, vecteur de contamination, jamais consultées), si et seulement si ce n'est pas le propriétaire actuel. Le consensus arbitre entre des personnes qui **existent** ; il ne désigne jamais une personne à créer. L'arbitrage se fait par **balayage du snapshot en tête de phase** — tous les conflits vus, ordre-indépendamment —, non par collecte au fil de la cascade, qui n'attrape que les collisions que l'ordre fait surgir. Les signatures affectées par un transfert — portées sur l'ancien propriétaire, `resolution_mode = 'identifier'`, dont l'identité porte la valeur — repassent à NULL, et la cascade les re-résout contre la carte corrigée. L'`add_identifier` unitaire de l'admin garde son refus strict.

- **Canal nominal : re-orphelinage sur ambiguïté, GC, re-attache.** Le match par forme de nom reste inchangé (forme unique → attache, ambiguë → orpheline, inconnue → création). S'y ajoute la remise en jeu : une forme qui **devient ambiguë** (désigne au moins deux personnes) re-orpheline ses signatures nominales non épinglées (`resolution_mode = 'name'`) ; la suppression des personnes vidées (GC) retire leurs formes canoniques, ce qui peut désambiguïser une forme réduite ; les orphelines dont la forme redevient unique se re-attachent. C'est le GC des personnes réduites vidées qui referme le sous-regroupement : « j martin » cesse d'exister comme forme dès que sa personne réduite disparaît, et les signatures « j martin » rejoignent « jean martin ». L'ordre-indépendance émerge de l'itération (convergence multi-run : une œuvre peut rester sous-résolue jusqu'à la passe suivante). Aucune clé de blocage, aucun recompute par bloc : le lookup `person_name_forms` est déjà un agrégat indexé, sans comparaison quadratique.

- **`resolution_mode`, partition des trois réinitialisations.** Une signature `identifier` affectée par un transfert repasse à NULL ; une signature `name` à forme devenue ambiguë repasse à NULL ; une signature `name` qui porte un identifiant ne bouge **pas** sur transfert (son `person_id` ne dépend pas de la valeur) ; les `cross_source` sont **toutes** re-nullées à chaque run et recalculées — le cross-source est un opérateur d'ensemble par (publication, position) dont le donneur de `person_id` est toujours un membre fermement résolu (identifiant/nom), jamais un autre résultat cross-source. Les épinglages admin vivent dans `confirmed_authorships`, pas dans une valeur de mode : une orpheline assignée par l'admin porte un `person_id` sans mode automatique, l'autorité étant l'épinglage. Invariant : `person_id` et `resolution_mode` s'écrivent ensemble pour les résolutions automatiques.

- **Traçabilité des transferts : journal et métrique, pas de table.** Un transfert est le diff du recalcul de consensus — une valeur dont l'attributaire change. Il est journalisé par événement et compté dans les métriques de la phase, de quoi contrôler ce qui se passe. L'arbitrage étant re-dérivable du consensus à tout moment, aucune table d'historique n'est tenue.

- **Le noyau est une entrée fixe.** Les résolutions admin d'orphelines s'inscrivent dans `confirmed_authorships` (`source_authorship_id` en clé primaire → `person_id`, grain signature) et sont réappliquées avant la cascade : sans cette garde, la remise en jeu nominale ré-orphelinerait le travail admin. C'est le seul ajout structurel de table du chantier.

- **Bridging cross-valeur : extension marginale différée.** Unifier une personne connue par une valeur d'identifiant et par une autre (sans signature partageant les deux) relève d'une fermeture transitive sur les valeurs. Le consensus par valeur suffit à l'ordre-indépendance et à la capture ; le bridging n'ajoute que l'unification de doublons cross-identifiant, aujourd'hui traités au triage assisté. À reprendre si le volume de merges manuels le justifie, avec sa propre garde de cohérence de composante.

## Phasage

### Phase 1 — Canal identifiant : corroboration et arbitrage des conflits

- [x] `form_matches_person` (forme vs personne : nom-prénom canonique ou forme confirmée) et `same_person_name` (nom-prénom, tolérant à la graphie), prédicats purs testés. (a2969860, c52771ae)
- [x] Corroboration par `same_person_name` au barreau identifiant de `decide_match_by_identifier`, à la place de `names_compatible` : la variante de graphie du propriétaire se rattache directement (pas de doublon), l'homonyme et le porteur étranger restent rejetés. (c52771ae)
- [x] Arbitrage d'un conflit par consensus (logique) : consensus des valeurs en conflit (query ciblée `author_identifying_keys` × `source_authorships` pour le poids en signatures), transfert (`transfer_to`, `pending` seulement) si `form_matches_person(consensus, candidat)` et pas `(consensus, propriétaire)`. En place, aujourd'hui déclenché par collecte au fil de la cascade puis passe de résolution après la boucle. (c89073d4, 9c6a0fda)
- [x] Remédiation du stock (oneshot `remediate_identifier_captures`, prod) : réattribue par consensus les identifiants portés par au moins deux personnes, via l'arbitrage. Ni scission ni fusion — seul l'identifiant bouge, entre personnes existantes ; la fusion d'un éventuel doublon reste au dédoublonnage assisté. (b17e3422)
- [x] Tests d'intégration : capture recalée sur la majorité, porteur étranger qui ne vole pas ; corroboration de graphie sans doublon, homonyme rejeté (unitaires). (9c6a0fda)
- [x] Retrofit de l'orchestration au geste commun : arbitrage des conflits par balayage du snapshot en tête de phase (`build_identifier_conflicts`, partagé avec la remédiation du stock), null ciblé des signatures affectées (`null_identifier_signatures`), journal par transfert. La logique d'arbitrage (consensus, corroboration, `form_matches_person`) ne change pas ; l'ordre et le périmètre du balayage, oui — la correction d'une capture devient multi-run. (eb5ea8d6, e6d7ddb7)

### Phase 2 — Canal nominal et structure partagée

- [x] Table `confirmed_authorships` : épinglage des résolutions admin d'orphelines. Écriture admin (attache → épingle, détachement / rejet de forme → désépinglent), lecture pipeline (`enforce_confirmed_authorships` réapplique les épinglages avant la cascade). (ab8896e3)
- [x] Colonne `resolution_mode` (`identifier` / `name` / `cross_source`, NULL si orpheline) sur `source_authorships`, écrite à chaque pose automatique de `person_id`. Prérequis partagé : elle scope le null ciblé du canal identifiant, le re-orphelinage nominal et le recompute en bloc du cross-source. (8f59b28d)
- [x] Re-orphelinage nominal : NULL (personne et mode) des signatures `resolution_mode = 'name'` non épinglées dont la forme désigne au moins deux personnes. (e9d6148a)
- [x] GC des personnes vidées intégré à la phase (hors RH) : retirer les formes canoniques (FK `CASCADE`) désambiguïse la forme réduite. La re-attache des orphelines désambiguïsées est portée par la cascade, qui reprend les orphelines à chaque run — pas de passe dédiée. (e9d6148a)
- [x] Reset cross-source : NULL de toutes les signatures `resolution_mode = 'cross_source'` non épinglées en tête de phase (recompute complet), et arrêt de la ré-injection des résultats cross-source dans l'index vivant de la cascade (un cross-source n'en ancre jamais un autre). (dbe6a076)
- [x] Ordre-indépendance propre du cross-source : dans `decide_person_match`, le match par forme de nom passe avant le cross-source, et la création par nom est différée à une seconde passe. Une signature à créer rejoint alors par cross-source une ancre d'une autre source de la même publication — deux graphies du même auteur aux formes de nom disjointes mais `names_compatible` (« Jean Martin » / « J-P Martin ») ne créent plus deux personnes selon l'ordre. (aeddbb01)
- [x] Tests : convergence « j martin » / « jean martin » sur plusieurs runs et re-orphelinage de « h chanal » dès que l'homonyme coexiste (e2e via `run()`, peuplement canonique simulé) ; re-orphelinage, reset cross-source et GC ciblés (unitaires sur les requêtes). Le cas RH-homonyme relève de la garde d'ambiguïté générale (forme partagée → orpheline) ; la capture d'identifiant recalée par consensus est couverte en Phase 1. (b899bed2, e9d6148a, dbe6a076)

## Questions ouvertes

- **Événements pipeline dans `audit_log`.** Le principe actuel tient le pipeline hors de `audit_log` (une entrée par action unitaire du pipeline gonflerait la table). Une exception se défend pour les phénomènes à la fois rares et hors-norme — non-corroboration, transfert d'identifiant, conflit d'attribution — qui gagneraient à être révisables dans l'admin, au-delà du journal éphémère. À trancher : acteur « système » ou garde `user_id` relâchée pour ces seuls types.
## Liens

- Cascade personnes : `application/pipeline/persons/create_persons_from_source_authorships.py`, `infrastructure/queries/pipeline/persons_create.py`.
- Règles de nom : `domain/persons/matching.py` (`decide_match_by_identifier`, `form_matches_person`), `domain/persons/name_matching.py` (`names_compatible`, `same_person_name`).
- Écriture identifiants : `application/persons/core.py` (`add_identifiers_from_authorships`, `add_identifier`).
- Arbitrage des conflits : `application/pipeline/persons/resolve_identifier_transfers.py`.
- Audit consensus (diagnostic) : `interfaces/cli/oneshot/audit_identifier_consensus.py`.
- Résolution admin d'orphelines (canal nominal) : `application/authorships/assign_orphans.py`, épinglage via `confirmed_authorships`.
