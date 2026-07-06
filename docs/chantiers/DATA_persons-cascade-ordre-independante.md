# Chantier — Personnes : résolution d'identité ordre-indépendante

Commencé le 2026-07-04

Rendre le résultat de la phase personnes indépendant de l'ordre d'ingestion. Le geste tient en une idée, appliquée à deux canaux : remplacer la décision prise au moment où une signature arrive (« à quelle personne l'attacher ? ») par une lecture d'agrégat sur le snapshot. L'ordre-indépendance vient de là — lire le bloc ou la valeur plutôt que trancher à l'arrivée —, pas d'une comparaison de noms plus fine.

## Contexte

### Deux douleurs d'ordre-dépendance

La phase personnes parcourt les `source_authorships` sans `person_id` et tranche chaque rattachement à l'arrivée. Une entité créée n'est jamais remise en jeu. Deux symptômes en découlent :

- **Regroupement nominal dépendant de l'ordre.** Une forme réduite (« j martin ») arrivée avant sa forme pleine crée sa propre personne ; « jean martin » rencontrée ensuite en crée une seconde (sous-regroupement). Une forme ambiguë (« h chanal ») arrivée avant l'homonyme qui la départage se colle au seul candidat présent, et l'append-only ne revient jamais dessus (sur-regroupement). Une même personne aboutit à une ou deux fiches selon la séquence.
- **Capture d'identifiant (premier arrivé).** La première signature portant une valeur d'identifiant fort en fixe le nom-autorité, figé par `UNIQUE (id_type, id_value)`. Si cette première est corrompue (identifiant recopié sur le mauvais co-auteur), les signatures correctes suivantes échouent à la corroboration de nom et s'éparpillent en doublons ; l'identifiant reste collé à la mauvaise personne.

### Deux canaux de nature opposée

- **Canal nominal** — non transitif, ambigu. La forme de nom est sur toutes les signatures mais elle n'est pas une relation d'équivalence : une forme réduite (« j smith ») relierait par transitivité des personnes distinctes (« john smith », « jane smith »). Il se résout par lecture de bloc avec garde de cardinalité — une forme ambiguë reste orpheline —, jamais en graphe de noms.
- **Canal identifiant** — fonctionnel par valeur. Une valeur d'identifiant fort désigne une personne ; la résolution est exacte et se lit par agrégat sur la valeur.

### Le noyau, lu en entrée fixe

Le recompute lit le noyau curé et ne le surcharge jamais : signatures épinglées à une personne par résolution admin (`confirmed_authorships`), cannot-link (`distinct_persons`, et le référentiel RH — deux personnes portant chacune une notice `persons_rh` sont distinctes par construction, l'identité étant résolue au niveau institutionnel ; la contrainte `ON DELETE RESTRICT` interdit d'ailleurs de supprimer une personne RH), formes de nom `confirmed`/`rejected`, paires `(publication, personne)` rejetées. Tout le reste est recalculé.

Une personne purement nominale (aucun identifiant, aucune curation) ne porte aucune référence externe : son `person_id` peut changer d'un run à l'autre sans rien casser. Dès qu'elle acquiert de la curation — un épinglage, une forme confirmée, une marque de distinction —, elle devient ancrée et le noyau la protège. D'où l'absence de tout appareil de stabilité d'étiquette : il ne servirait qu'à protéger une curation que le noyau protège déjà.

## Décisions

- **Consensus par valeur d'identifiant.** Pour chaque valeur d'identifiant fort du snapshot, le nom-autorité est le consensus (pluralité) des noms de toutes les signatures portant la valeur, les formes `confirmed` prioritaires — jamais le nom capté par la première arrivée. La corroboration se fait contre ce consensus : les signatures compatibles se consolident sur la personne de la valeur ; une signature minoritaire (le report corrompu) devient variante minoritaire ou part au tri manuel. Un même geste tue trois choses d'un coup — la capture (le consensus prime le premier arrivé), le doublon (les signatures que le premier-arrivé éparpillait se re-consolident, la personne vidée est ramassée) et le lien corrompu (rejeté par minorité). Le `person_id` de la valeur reste stable ; seul son nom-autorité s'actualise.
- **Recompute nominal par bloc.** Après le canal identifiant, un bloc patronymique porte des personnes déjà **fixées** — résolues par identifiant, ou curées (RH, épinglées, `distinct_persons`) — et des signatures nominales **libres**, encore sans personne. Le recompute réattribue les seules signatures libres et lit les personnes fixées comme ancres en lecture seule (elles reçoivent ou repoussent une forme, jamais réattribuées) ; le résultat est une fonction pure du contenu du bloc, pas de la séquence. Chaque prénom plein distinct des signatures libres ajoute une ancre (deux occurrences du même plein → même personne, faux-merge d'homonymes pleins assumé) ; une forme se rattache à une ancre — fixée ou libre — si et seulement si elle en désigne exactement une (une → attache ; deux ou plus → orpheline signalée ; aucune ancre pleine, la réduite seule → elle ancre sa propre personne). Aucune garde de contexte, aucun départage. Les ancres fixées portent le cannot-link : deux homonymes pleins distincts (deux personnes RH, ou `distinct_persons`) restent deux ancres, et une signature libre ambiguë entre elles reste orpheline. Un faux-merge d'homonymes pleins libres se répare par épinglage-pour-scinder — quelques signatures épinglées vers une personne neuve, puis `distinct_persons` —, `distinct_persons` seul ne séparant pas des signatures réunies sous un même `person_id`.
- **Le noyau est une entrée fixe.** Le recompute ne reconsidère que les signatures libres ; les épinglées et les personnes curées sont des entrées, pas des sorties. Les résolutions admin d'orphelines s'inscrivent dans `confirmed_authorships` (`source_authorship_id` en clé primaire → `person_id`, grain signature) et sont lues comme épinglage dur : sans cette garde, le recompute nominal réorphelinerait le travail admin. C'est le seul ajout structurel du chantier.
- **Bridging cross-valeur : extension marginale différée.** Unifier une personne connue par une valeur d'identifiant et par une autre (sans signature partageant les deux) relève d'une fermeture transitive sur les valeurs. Le consensus par valeur suffit à l'ordre-indépendance et à la capture ; le bridging n'ajoute que l'unification de doublons cross-identifiant, aujourd'hui traités au triage assisté. À reprendre si le volume de merges manuels le justifie, avec sa propre garde de cohérence de composante.

## Phasage

### Phase 1 — Consensus par valeur d'identifiant

- [ ] Agrégat par valeur d'identifiant fort : nom-autorité = pluralité des noms des signatures portant la valeur, formes `confirmed` prioritaires.
- [ ] Corroboration contre le consensus (à la place du nom du premier arrivé) ; consolidation des signatures compatibles sur la personne de la valeur, démotion de la minoritaire.
- [ ] Substitution aux barreaux identifiant de `decide_person_match` ; canaux cross-source et nom inchangés à ce stade.
- [ ] Tests : une valeur corrompue ingérée en premier ne capte plus le nom-autorité ; 99 signatures correctes l'emportent sur 1 corrompue quel que soit l'ordre ; formes `confirmed` prioritaires ; non-régression des rattachements existants.

### Phase 2 — Recompute nominal par bloc

- [ ] Table `confirmed_authorships` : épinglage des résolutions admin d'orphelines, lu comme entrée fixe. Préalable au recompute nominal.
- [ ] Recompute d'un bloc patronymique, **en deux passes** pour rester ordre-indépendant à l'intérieur du bloc : d'abord poser les ancres pleines (personnes fixées + prénoms pleins libres, les pleins identiques fusionnant, fixées comprises), ensuite attacher les formes réduites par cardinalité contre cet ensemble d'ancres arrêté (une seule ancre compatible → attache, deux ou plus → orpheline) ; cannot-link (RH, `distinct_persons`) respectés. Un balayage ligne à ligne mêlant pleines et réduites réintroduirait la dépendance d'ordre.
- [ ] Tests, comme cas du même recompute : « j martin » et « jean martin » regroupent sans autre candidat ; « h chanal » reste orphelin dès que « hervé chanal » et « hélène chanal » coexistent ; l'ordre d'ingestion ne change pas le résultat ; une signature libre « jean martin » ambiguë entre deux personnes RH homonymes reste orpheline, sans réattribuer ni fusionner les ancres fixées.

## Questions ouvertes

- **Clé de blocage patronymique.** Quelle clé co-localise dans un même bloc les signatures qui partagent déjà une forme, sans les éparpiller ni gonfler les blocs ? Le point délicat est le découpage des patronymes composés ou à particule (quel jeton fait « le » nom), qui doit rester cohérent entre la génération des formes et la clé de blocage. Un changement complet de patronyme ne partage aucune forme : ces cas restent des personnes séparées jusqu'à ce qu'un identifiant les relie (fallback conservateur, hors canal nominal).

## Liens

- Phase personnes : `application/pipeline/persons/create_persons_from_source_authorships.py`, `domain/persons/matching.py`, `application/pipeline/persons/populate_person_name_forms.py`.
- Résolution admin d'orphelines : `application/authorships/assign_orphans.py`.
