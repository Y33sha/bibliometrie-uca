# Chantier — Résolution des personnes par record linkage incrémental

Abandonné le 2026-07-04: mauvaise idée. Remplacé par [Cascade personnes : ordre-indépendance et consensus d'attribution](../DATA_persons-cascade-ordre-independante.md)

Aligner la résolution des personnes sur le modèle de la phase publications : une appartenance dérivée, recalculable à chaque passe, où fusions et scissions découlent d'un même primitif de clustering, et où seules les décisions humaines constituent un noyau non négociable. Aujourd'hui la phase personnes procède par cascade monotone : elle rattache ou crée, jamais ne remet en jeu une entité existante, ne fusionne ni ne scinde. L'identité d'ancrage est implicite et dépend de l'ordre d'arrivée des signatures.

## Contexte

### L'asymétrie avec les publications

La phase publications traite l'appartenance d'une `source_publication` à une `publication` comme un **état dérivé** : les `source_publications` reliées par une clé de confirmation partagée forment les composantes connexes d'un graphe (`domain/entity_resolution.py`), chaque composante est partitionnée par DOI (le DOI fait identité, cannot-link), et chaque partition aboutit sur une publication. Rattachement, création, fusion et scission sont les facettes d'une seule opération, recalculée sur le voisinage des `source_publications` marquées à recalculer. Rien n'est figé sauf le cannot-link DOI.

La phase personnes procède autrement : une boucle sur les `source_authorships` sans `person_id`, une cascade de cinq signaux du plus fiable au moins fiable (identifiant ORCID déposé, compte HAL, IdRef, cross-source par position, forme de nom), et pour chacune soit un rattachement, soit une création. L'opération est **append seulement** : une personne créée n'est jamais reconsidérée, aucun signal ultérieur ne peut la fusionner avec une autre ni la scinder. Le résultat dépend de l'ordre : une signature « j. martin » sans identifiant crée une personne, une signature « jean martin » rencontrée ensuite en crée une seconde, car les deux formes normalisées diffèrent et rien ne recalcule le regroupement de zéro.

### Pourquoi le modèle publications ne se transplante pas tel quel

Dans les publications, **toutes** les clés de liaison sont de haute précision : DOI, NNT, HAL id, PMID par égalité directe, et le bloc de métadonnées (`type | titre normalisé | année`) verrouillé par une garde de longueur de titre. Aucune arête faible n'existe, donc la fermeture transitive du clustering ne peut pas sur-fusionner.

Côté personnes, le signal le plus répandu est la **forme de nom** — présente sur toutes les signatures, seule disponible pour une part importante d'entre elles, elle porte l'essentiel du volume de rattachement —, or c'est aussi le plus faible : non transitif et de fiabilité inégale. En faire une arête de graphe close transitivement produirait une sur-fusion catastrophique : « j. smith » relie « john smith » et « jane smith », la transitivité fond les deux. De plus, même un identifiant fort n'est pas un token pur : sa **valeur** est fiable, mais son **attachement** à une signature est posé par la source, faillible. Un ORCID est intrinsèque à une personne mais porté par une signature ; le lien signature→ORCID relève de la désambiguïsation propre à la source. Le bon cadre n'est donc pas « token contre arête gardée » mais un **gradient de force de garde**, du plus sûr au moins sûr : les décisions admin s'imposent; un identifiant moissonné nécessite une garde légère (compatibilité de nom permissive); une simple forme de nom demande une garde de contexte lourde.

### Mesures sur la base de travail

- Référentiel : 13 942 personnes. **32,7 % sont purement nominales** (aucun identifiant fort non rejeté) : elles dépendent entièrement du canal nominal. 67,3 % sont ancrées par au moins un identifiant fort.
- `source_authorships` : 15,57 M de signatures pour **616 627 identités distinctes** au sens `(nom normalisé, identifiants)`, soit un facteur de répétition d'environ 25.
- Coût du blocage par nom, somme des `C(n,2)` intra-bloc : **6,56 milliards** de comparaisons au grain signature (bloc le plus gros : 6485), contre **828 000** au grain identité (bloc le plus gros : 199). Le passage au grain identité divise le coût par près de 7900 et rend le canal d'arête gardée tractable. Les plus gros blocs de noms sont des patronymes romanisés fréquents, portés surtout par des co-auteurs externes qui n'entrent jamais au référentiel.

### Le défaut d'ancrage par identifiant : priorité au premier arrivé

Le nom-autorité comparé lors de la corroboration d'un match par identifiant est le nom canonique de la personne (`persons.last_name_normalized`), **figé à la création** depuis la première signature qui a créé l'entité, et les tables de correspondance identifiant→personne sont préchargées une fois par run. Une signature corrompue portant un identifiant erroné, ingérée avant les signatures correctes, capte l'identifiant et en devient le nom-autorité. La contrainte `UNIQUE (id_type, id_value)` empêche ensuite tout autre rattachement de cette valeur. Les signatures correctes ultérieures, dont le nom ne correspond pas au nom capté, voient leur match refusé par corroboration et retombent sur une création nominale. L'identifiant reste collé à la mauvaise personne jusqu'à correction admin, et les signatures correctes s'éparpillent en doublons.

## Décisions

### Deux couches

- **Noyau non négociable** (figé) : lien RH, identifiant `confirmed`, forme de nom `confirmed`, `distinct_persons`, paires `(publication, personne)` rejetées. Le modèle retire l'auto-`confirmed` des formes dérivées du nom canonique et remet le stock déjà auto-confirmé à `pending` (leur appartenance au nom canonique se lit dans `sources`, `'persons' = ANY(sources)`) : `status='confirmed'` désigne alors sans ambiguïté une validation humaine. Les lecteurs qui distinguaient « appartient au nom canonique » lisent `'persons' = ANY(sources)`.
- **Couche fluide** (recalculable) : le moissonné. Arêtes fortes (identifiant, garde légère de nom déjà codée dans la corroboration) + arêtes faibles (nom, gardées par contexte). Clustering en composantes connexes ; cannot-link du noyau en partition.

### Grain et support

- Identité (`author_identifying_keys`, ~645 k, produite par la scission de `source_authorships` — **dépendance amont**) = grain du **canal identifiant**, où la résolution est fonctionnelle (identité identifiant-ancrée → une personne). **Pas** fonctionnel pour le nominal : un nom nu (« j smith ») porté par deux homonymes appartient à plusieurs personnes.
- Support d'appartenance = `source_authorships.person_id`, grain **signature** : seul à porter des affectations divergentes d'une identité nominale et les détachements contextuels. Un `person_id` sur l'identité ne vaut qu'en optimisation du canal identifiant, pas comme support du modèle.

### Incarnation conservatrice

Asymétrie avec les publications : un chemin de rattachement manuel existe (authorships orphelines). Donc une arête cassée ou une partition douteuse **reste orpheline** (`person_id` NULL) au lieu de s'incarner en personne — la création est conservatrice, jamais l'issue du doute. Restent orphelins : forme partagée sans critère pour trancher entre homonymes ; match identifiant cassé par corroboration (pas de retombée en création nominale — corrige une source directe du sur-éclatement mesuré).

### Réconciliation avec l'existant

- **Cannot-link** (`distinct_persons`, rejets) : partition **post-clustering**, composante recoupée selon le `person_id` courant, comme le DOI partitionne une publication (robuste à la transitivité).
- **Noyau** : must-link / cannot-link en entrée du clustering (une passe, pas de réparation après coup). Forme validée admin > consensus pour le nom canonique.
- **Stabilité `person_id`** : composante incarnée = id de la pluralité ; personne du noyau garde son id même minoritaire. Fusion vide l'id perdant (signatures repointées, personne vide supprimée), scission laisse l'id au plus gros. Deux personnes du noyau dans une composante ne fusionnent pas (signal d'erreur admin à remonter, pas à trancher).

### Filet contre la sur-fusion

Contrôle de cohérence de composante : des sous-groupes de noms incompatibles → éjection de l'aberrant (arête faible coupée), pas fusion. Vaut aussi pour l'autorité de nom, décidée à la pluralité et non au premier arrivé.

### Trois canaux, par sûreté croissante

La cascade actuelle (priorité + premier match) n'est pas un graphe ; le passage en graphe change le comportement (sur-fusion transitive), assumé car recalculable — une sur-fusion se résorbe au resserrement des gardes.

1. **Identifiant → graphe d'abord** : arête forte, fermeture transitive légitime sous la garde de nom déjà codée. La machinerie s'y bâtit et se valide (composantes, cannot-link en partition, ancrage noyau, marquage, fusion/scission, incarnation conservatrice).
2. **Nom → arête gardée ensuite** : blocage par forme au grain identité, garde de contexte pairwise (forme ouverte, cf. Questions).
3. **Cross-source → passe de réconciliation ensembliste** : au grain signature (même publication × position, nom compatible, hors méga-papers > 50), il **fusionne des composantes** après clustering plutôt que d'entrer dans le graphe de nœuds. Le rejet contextuel reste un détachement de signature sur `sa.person_id`.

### Machinerie incrémentale

Marquage à recalculer sur les **records d'entrée** (signatures/identités), jamais la personne : le pipeline sait qu'une signature a bougé, pas qu'une personne a changé. Le recalcul recompose `sa.person_id` depuis les composantes, incarne les franches, laisse orphelines les douteuses, supprime les personnes vidées, et **préserve le noyau** (nom validé prioritaire, cannot-link respectés). Convergence multi-run : garde sur noms bruts au premier passage, resserrement et re-résolution ensuite (une œuvre peut rester sous-résolue jusqu'au run n+1).

## Phasage

### Phase 1 — Regroupement par identifiant

- [x] Prérequis : retirer l'auto-`confirmed` des formes `persons` (les lecteurs lisent `'persons' = ANY(sources)`) + remise à `pending` du stock déjà auto-confirmé, pour que `status='confirmed'` désigne sans ambiguïté une validation humaine. (`af2c6e28`, migration `b2f5c9d8a41e`)
- [ ] Arêtes : paires d'identités partageant une valeur d'identifiant fort, gardées par compatibilité de nom (corroboration existante réutilisée).
- [ ] Clustering en composantes connexes (`connected_components`), recoupé par cannot-link (`distinct_persons`, rejets) selon le `person_id` courant.
- [ ] Affectation : chaque composante franche prend un `person_id` (pluralité, priorité au noyau), les douteuses restent orphelines ; nom canonique par consensus, forme validée admin prioritaire ; fusion (vider l'id perdant) / scission (id au plus gros).
- [ ] Écrire `sa.person_id` depuis les composantes, moins les détachements contextuels.
- [ ] Substituer ce graphe aux barreaux identifiant de `decide_person_match` (nom et cross-source inchangés à ce stade).
- [ ] Tests : indépendance à l'ordre d'ingestion, non-régression des rattachements par identifiant, cannot-link et noyau respectés.

### Phase 2 — Regroupement par le nom

- [ ] Candidats par blocage sur forme de nom, tranchés par une garde de contexte pairwise (co-auteurs déjà résolus, labo partagé, proximité d'une composante identifiant-ancrée, compatibilité initiale/plein).
- [ ] Contrôle de cohérence de composante : éjecter l'élément aberrant plutôt que fusionner.

### Phase 3 — Recalcul incrémental

- [ ] Marquage à recalculer sur les signatures/identités (jamais la personne), rafraîchissement préservant le noyau, primitif fusion/scission.
- [ ] Convergence multi-run.
- [ ] Repérage des fusions/scissions douteuses pour contrôle admin.

## Questions ouvertes

- **Forme exacte de la garde nominale** : quels signaux de contexte, quels seuils, quelle combinaison. Le matching de noms sous-jacent (compatibilité avec initiales, noms composés, translittération, accents) reste heuristique et devient ici porteur ; il conditionne la précision du canal nominal pour un tiers du référentiel.
- **Règle d'éjection d'aberrant** : à partir de quel écart une signature est-elle jugée aberrante dans sa composante, et que devient son arête faible coupée (orpheline, ou re-candidate à un autre bloc).
- **Nom canonique en l'absence de validation admin et de consensus clair** : départage quand les signatures se répartissent sans majorité.

## Liens

- Phase personnes : `application/pipeline/persons/create_persons_from_source_authorships.py`, `domain/persons/matching.py`, `application/pipeline/persons/populate_person_name_forms.py`.
- Modèle de référence : phase publications, `domain/publications/reconciliation.py`, `domain/entity_resolution.py`, `docs/pipeline/07-publications.md`.
- Dépendance amont : [DATA_scinder-source-authorships](archived/2026-07-03_DATA_scinder-source-authorships.md) (terminé).
- Chantier lié : [DATA_personnes-dedoublonnage-assiste](DATA_personnes-dedoublonnage-assiste.md).
- Cadre token / garde pairwise : [archived/2026-06-26_DATA_dedup-pairwise-gated](archived/2026-06-26_DATA_dedup-pairwise-gated.md).
