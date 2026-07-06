# Chantier — Personnes : résolution d'identité recalculable et ordre-indépendante

Commencé le 2026-07-04

Rendre le résultat de la phase personnes indépendant de l'ordre d'ingestion, en traitant l'appartenance d'une signature à une personne comme un état dérivé recalculable — sur le modèle de la phase publications — plutôt que comme une cascade qui rattache ou crée sans jamais reconsidérer une entité existante. Le noyau des décisions humaines reste seul intangible ; tout le reste se recalcule.

## Contexte

### Le problème : une cascade append-only, dépendante de l'ordre

La phase personnes parcourt les `source_authorships` sans `person_id` et, pour chacune, applique une cascade de signaux (identifiant déposé, compte HAL, IdRef, cross-source par position, forme de nom) qui aboutit soit à un rattachement, soit à une création. L'opération n'ajoute que : une personne créée n'est jamais remise en jeu, aucun signal ultérieur ne la fusionne ni ne la scinde. Le résultat dépend donc de l'ordre d'arrivée, sous trois formes :

- **Sous-regroupement.** Une signature « j martin » crée une personne dont les formes dérivées ne contiennent pas « jean martin ». Une signature « jean martin » rencontrée ensuite crée une seconde personne. Dans l'ordre inverse, la forme pleine engendre l'initiale et les deux signatures convergent. Une même personne aboutit à une ou deux fiches selon l'ordre.
- **Identifiant capté par le premier arrivé.** Une valeur d'identifiant est captée par la première signature qui la porte, figée par `UNIQUE (id_type, id_value)`. Si cette première signature est erronée (identifiant recopié sur le mauvais co-auteur par une source), les signatures correctes suivantes voient leur match refusé par corroboration de nom et retombent en création. L'identifiant reste collé à la mauvaise personne, les bonnes signatures s'éparpillent.
- **Sur-regroupement par forme ambiguë.** Une forme réduite (« h chanal ») relie deux personnes réellement distinctes (« Hervé Chanal », « Hélène Chanal »). Selon l'ordre, la signature ambiguë se colle à l'une ou à l'autre, et l'arrivée tardive d'un homonyme ne défait jamais un rattachement déjà posé.

### Pourquoi une résolution recalculable

Rendre le résultat ordre-indépendant revient à définir l'identité comme une **fonction déterministe de l'état courant** — l'ensemble des signatures plus les décisions humaines — recalculée depuis ce jeu à chaque changement, jamais par mutation d'un état antérieur. Rattachement, création, fusion et scission cessent alors d'être des actions distinctes : ce sont les issues possibles d'un même recalcul, comme l'appartenance d'une `source_publication` à une `publication` dans la phase publications. « Fusionner » ou « défusionner » deux fiches ne sont pas des opérations à programmer ; ce sont deux façons de décrire un recalcul qui aboutit à un regroupement différent du précédent.

Cette recalculabilité est le seul point commun aux deux canaux décrits plus bas ; leur mécanisme diffère radicalement. La forme de nom n'est **pas** une relation d'équivalence — une forme réduite (« j smith ») est un pont qui relierait par transitivité des personnes distinctes (« john smith », « jane smith ») —, donc le canal nominal ne se traite **jamais** en graphe transitif. Seul le canal identifiant, où l'égalité de valeur est transitive et de haute précision, se prête à une fermeture transitive.

### Deux canaux de nature opposée

Le point structurant du chantier est que les signaux d'identité se répartissent en deux canaux qu'il faut traiter différemment :

- **Canal identifiant** — borné et fonctionnel. Une valeur d'identifiant fort désigne une personne ; deux signatures partageant la valeur, sous garde de compatibilité de nom, appartiennent à la même personne. La résolution y est exacte et se valide par des tests d'ordre-indépendance nets. Il couvre environ deux tiers du référentiel.
- **Canal nominal** — non borné et ambigu. La forme de nom est présente sur toutes les signatures et seule disponible pour environ un tiers du référentiel (personnes sans aucun identifiant fort non rejeté), mais elle est non transitive et de fiabilité inégale. Il se résout par recherche par bloc avec garde de cardinalité — une forme ambiguë reste orpheline —, jamais en graphe de noms. Désambiguïser une forme ambiguë par le contexte (co-auteurs, laboratoire, période) est un problème heuristique sans critère de clôture ; ce chantier le tient **hors du chemin automatique**.

### Tractabilité du blocage

Le blocage par nom au grain **identité** (`author_identifying_keys`, ~645 k lignes) plutôt qu'au grain **signature** (~15,6 M) divise le nombre de comparaisons intra-bloc de près de quatre ordres de grandeur (de l'ordre de 6,5 milliards à moins d'un million). Les plus gros blocs de noms sont des patronymes fréquents portés surtout par des co-auteurs externes qui n'entrent jamais au référentiel. Le canal identifiant est donc tractable au grain identité, et le recalcul se cloisonne par clé de blocage.

## Décisions

- **Identité = état dérivé recalculable, en deux couches.** Le *noyau non négociable* (figé) : lien RH, identifiant `confirmed`, forme de nom `confirmed`/`rejected`, `distinct_persons`, paires `(publication, personne)` rejetées. La *couche fluide* (recalculable) : tout le moissonné, résolu par recalcul depuis le snapshot — graphe transitif pour le canal identifiant, recherche par bloc pour le canal nominal — et réattribuable à chaque passe. `status='confirmed'` sur une forme de nom désigne sans ambiguïté une validation humaine ; l'appartenance d'une forme au nom canonique se lit `'persons' = ANY(sources)`.
- **Le canal identifiant est le moteur.** Les identités partageant une valeur d'identifiant fort, gardées par compatibilité de nom, forment les composantes connexes d'un graphe ; chaque composante est recoupée par le cannot-link du noyau, puis incarnée en une personne. Regroupements et séparations sont des issues de ce recalcul, pas des opérations dédiées.
- **Attribution par consensus, pas par premier arrivé.** Le détenteur d'une valeur d'identifiant et le nom canonique d'une composante sont ceux que soutient la pluralité des signatures, une forme validée admin l'emportant sur la pluralité. Une majorité postérieure peut renverser une attribution devenue minoritaire, sans jamais déloger une attribution `confirmed`.
- **Le canal nominal est conservateur.** Une forme de nom qui ne matche qu'une seule personne se rattache ; une forme qui matche deux personnes distinctes ou plus laisse la signature **orpheline** (`person_id` NULL) et signalée pour contrôle admin, jamais un rattachement deviné. Aucune garde de contexte ni départage automatique n'entre dans le chemin du pipeline. Un chemin de rattachement manuel existant (authorships orphelines) absorbe ces cas.
- **Le départage contextuel est hors périmètre.** Choisir entre deux homonymes pour une forme ambiguë relève, si jamais utile, d'une suggestion admin ultérieure — jamais d'une décision du pipeline.
- **Support et grain.** Le support d'appartenance est `source_authorships.person_id`, au grain signature : lui seul porte les affectations divergentes d'une même forme nominale et les détachements. Le grain identité (`author_identifying_keys`) sert le canal identifiant, où la résolution est fonctionnelle.
- **Recalcul incrémental cloisonné.** Le marquage à recalculer porte sur les records d'entrée (signatures, identités), jamais sur la personne. Le recalcul se limite au composant touché, borné par la clé de blocage (nom de famille normalisé). Deux personnes du noyau dans une même composante ne fusionnent pas : c'est un signal d'erreur à remonter, pas à trancher.

## Phasage

### Phase 1 — Canal identifiant recalculable

Livre l'ordre-indépendance et le consensus d'attribution pour les personnes ancrées par identifiant.

- [ ] Arêtes : paires d'identités (`author_identifying_keys`) partageant une valeur d'identifiant fort, gardées par la compatibilité de nom déjà codée dans la corroboration.
- [ ] Clustering en composantes connexes, recoupé par le cannot-link du noyau (`distinct_persons`, paires rejetées) selon le `person_id` courant.
- [ ] Attribution : chaque composante franche prend un `person_id` par pluralité, priorité au noyau ; nom canonique = forme validée admin sinon pluralité ; une composante douteuse reste orpheline.
- [ ] Écriture de `source_authorships.person_id` depuis les composantes ; une valeur minoritaire délogée ne déloge jamais une attribution `confirmed`.
- [ ] Substitution de ce graphe aux barreaux identifiant de `decide_person_match` (canaux nom et cross-source inchangés à ce stade).
- [ ] Tests : ordre-indépendance des rattachements par identifiant ; une attribution erronée ingérée en premier est renversée par la majorité correcte ; cannot-link et noyau respectés ; non-régression des rattachements existants.

### Phase 2 — Canal nominal conservateur

Livre l'ordre-indépendance du canal nominal sans heuristique. Le canal se résout par recalcul du bloc depuis le snapshot, sans opération de fusion ni de défusion : sous-regroupement et sur-regroupement sont deux issues du même recalcul.

- [ ] Recalcul d'un bloc de noms au grain identité : les formes les plus complètes ancrent les personnes ; une forme réduite se rattache à une ancre si et seulement si elle n'en désigne qu'une, sinon la signature reste **orpheline** (`person_id` NULL) et signalée. Aucune garde de contexte, aucun départage.
- [ ] Tests, comme cas du même recalcul : « initiale ↔ pleine » regroupe (« j martin » et « jean martin », sans autre candidat) ; « homonyme tardif » sépare (« h chanal » orphelin dès que « hervé chanal » et « hélène chanal » coexistent) ; l'ordre d'ingestion ne change pas le résultat ; une forme ambiguë ne s'incarne jamais en rattachement.

### Phase 3 — Recalcul incrémental cloisonné

Livre l'exécution incrémentale bornée et sa convergence.

- [ ] Marquage à recalculer porté par les signatures et identités, jamais par la personne.
- [ ] Recalcul limité au composant touché (clé de blocage = nom de famille normalisé) : recomposition de `source_authorships.person_id`, incarnation des composantes franches, orphelinage des douteuses, suppression des personnes vidées, préservation du noyau.
- [ ] Repérage des changements de regroupement (regroupements, séparations, orphelinages) pour contrôle admin.
- [ ] Vérification de la convergence multi-run (une œuvre peut rester sous-résolue jusqu'à la passe suivante).

## Questions ouvertes

- **Clé de blocage nominale.** Le nom de famille normalisé suffit-il, ou faut-il absorber les variantes (translittération, noms composés, accents) ? Une clé trop fine rate des rapprochements (conservateur, acceptable) ; trop large, elle gonfle le coût de comparaison.
- **Matérialisation du résultat identifiant.** Faut-il porter le `person_id` résolu sur `author_identifying_keys` (colonne à créer) pour optimiser le canal identifiant, ou le support signature suffit-il ? À trancher au moment de la Phase 1.

## Liens

- Phase personnes : `application/pipeline/persons/create_persons_from_source_authorships.py`, `domain/persons/matching.py`, `application/pipeline/persons/populate_person_name_forms.py`.
- Modèle de référence : phase publications, `domain/publications/reconciliation.py`, `domain/entity_resolution.py`, `docs/pipeline/07-publications.md`.
