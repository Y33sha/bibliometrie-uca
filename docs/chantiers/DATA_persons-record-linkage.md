# Chantier — Résolution des personnes par record linkage incrémental

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

### Modèle cible

Deux couches, séparées par la force de garde de leurs signaux.

**Noyau non négociable — figé, jamais remis en cause par le recalcul.** Personnes liées à un export RH, identifiants au statut `confirmed` par action admin, verdicts admin sur les formes de nom (`confirmed`/`rejected`), paires `distinct_persons` (cannot-link entre deux personnes), paires `(publication, personne)` rejetées (cannot-link contextuel). Seul ce qui a été décidé par un humain ou issu des ressources humaines épingle une identité. La confirmation automatique des formes `source='persons'` n'en fait pas partie : elle est régénérable et suit le nom canonique.

**Couche fluide — dérivée, recalculable.** Tout ce qui est moissonné des sources. Les identités d'auteur en sont les nœuds ; les arêtes sont de deux forces. Les identifiants forts moissonnés forment des arêtes à fort a priori (garde légère : compatibilité de nom, ou consensus). Les formes de nom forment des arêtes à faible a priori, armées seulement sur corroboration de contexte. Les deux alimentent un même clustering en composantes connexes. Le cannot-link (`distinct_persons` et paires rejetées) partitionne les composantes, comme le DOI partitionne les publications.

### Grain de nœud : l'identité d'auteur

La résolution opère sur les **identités d'auteur** dédupliquées (environ 645 000), non sur les signatures (15,57 M). C'est ce grain qui rend le canal d'arête gardée abordable. Il est produit par le chantier de séparation de `source_authorships` en table d'identités et table de liaison, qui est donc une **dépendance amont** de ce chantier et non un préalable optionnel.

### Canal d'arête gardée pour les noms

Le nom n'est jamais une arête d'égalité. Le blocage par forme de nom (lossy, sur-groupe les homonymes) génère les candidats ; une **garde pairwise** tranche dans le bloc en armant ou non l'arête, sur preuve de contexte : co-signataires déjà résolus à la même personne, structure partagée, proximité d'une composante déjà ancrée par un identifiant, compatibilité de nom avec expansion d'initiale. Une signature nominale n'est jamais nue : elle porte sa publication, ses co-auteurs et son affiliation, que la garde compare. Ce canal généralise le signal cross-source déjà présent (même publication, même position, nom compatible), qui en est un cas particulier.

### Filet contre la sur-fusion

La fermeture transitive du clustering mord dès que la garde est trop permissive. Deux protections : une garde calibrée conservatrice, et un **contrôle de cohérence de composante** — une composante qui se scinde en sous-groupes de noms mutuellement incompatibles est suspecte, et l'élément aberrant est éjecté (son arête faible est coupée) plutôt que d'entraîner la fusion. Ce même contrôle répond au défaut d'autorité au premier arrivé : dans une composante ancrée par un identifiant, le nom canonique se décide par la **pluralité** des signatures, pas par la première ; une signature au nom minoritaire est l'aberration à éjecter, pas l'autorité.

### Machinerie à bâtir

La phase publications marque à recalculer les `source_publications` qui changent — jamais la publication dérivée — et la réconciliation traite leur voisinage, rafraîchissant les publications concernées (recompose depuis les sources, supprime les publications vidées) ; un primitif fusion/scission complète l'ensemble. La phase personnes n'a aucun équivalent. Par symétrie, le marquage à recalculer porte sur les **records d'entrée** — les signatures `source_authorships`, ou les identités d'auteur une fois `source_authorships` scindée —, jamais sur la personne : le pipeline ne sait pas a priori qu'une personne a changé, il sait qu'une signature a été insérée, re-normalisée ou ré-identifiée, ou qu'une action admin a touché son voisinage. Le recalcul en déduit les personnes à rafraîchir : recomposer depuis les identités membres (nom canonique par consensus), ou supprimer si vidées. À construire donc : ce marquage sur les records d'entrée, un rafraîchissement qui **préserve le noyau non négociable** (le nom canonique confirmé par admin prime sur le consensus ; les cannot-link sont respectés), et le primitif fusion/scission. La contrainte de préservation est plus forte que côté publications, où les métadonnées d'une publication sont une pure agrégation sans décision humaine à ménager.

### Ordonnancement et convergence

La garde de contexte est plus robuste sur des co-auteurs déjà résolus en personnes, or c'est précisément ce que la phase calcule : dépendance circulaire. La réponse tient dans la machinerie de recalcul : garde sur noms bruts au premier passage, puis marquage à recalculer et convergence au run suivant à mesure que l'identité se fige. Une œuvre peut rester sous-résolue jusqu'au run n+1 ; c'est le compromis simplicité contre immédiateté déjà retenu ailleurs dans le pipeline.

## Phasage

### Phase 1 — Corriger le défaut d'ancrage, indépendamment de la refonte

- [ ] Autorité au premier arrivé : documenter le mécanisme et son empreinte, mesurer le sur-éclatement induit (personnes nominales créées faute d'avoir pu récupérer un identifiant capté).

### Phase 2 — Couche identifiée en graphe recalculable

- [ ] Nœuds = identités d'auteur (dépend du chantier de séparation de `source_authorships`).
- [ ] Arêtes par identifiant fort moissonné, clustering en composantes connexes, cannot-link `distinct_persons` en contrainte de partition.
- [ ] Nom canonique par consensus des signatures, nom validé en admin prioritaire.
- [ ] Ancrage des composantes sur le noyau non négociable.

### Phase 3 — Canal nominal par arête gardée

- [ ] Blocage par forme de nom sur les identités.
- [ ] Garde de contexte pairwise (co-signataires résolus, structure, proximité d'ancre, compatibilité initiale/plein).
- [ ] Contrôle de cohérence de composante et éjection d'aberrant.

### Phase 4 — Machinerie incrémentale et contrôles

- [ ] Marquage à recalculer sur les records d'entrée (signatures ou identités), rafraîchissement des personnes concernées préservant le noyau non négociable, primitif fusion/scission.
- [ ] Convergence multi-run.
- [ ] Détecteur de fusions et scissions suspectes pour contrôle admin a posteriori.

## Questions ouvertes

- **Forme exacte de la garde nominale** : quels signaux de contexte, quels seuils, quelle combinaison. Le matching de noms sous-jacent (compatibilité avec initiales, noms composés, translittération, accents) reste heuristique et devient ici porteur ; il conditionne la précision du canal nominal pour un tiers du référentiel.
- **Règle d'éjection d'aberrant** : à partir de quel écart une signature est-elle jugée aberrante dans sa composante, et que devient son arête faible coupée (orpheline, ou re-candidate à un autre bloc).
- **Nom canonique en l'absence de validation admin et de consensus clair** : départage quand les signatures se répartissent sans majorité.
- **Ordonnancement** : convergence au run n+1 (simple, différée) contre seconde passe immédiate après la phase personnes (cohérence immédiate, coût d'une passe supplémentaire).
- **Empreinte du sur-éclatement** : non mesurée à ce stade ; conditionne l'urgence de la Phase 1.

## Liens

- Phase personnes : `application/pipeline/persons/create_persons_from_source_authorships.py`, `domain/persons/matching.py`, `application/pipeline/persons/populate_person_name_forms.py`.
- Modèle de référence : phase publications, `domain/publications/reconciliation.py`, `domain/entity_resolution.py`, `docs/pipeline/07-publications.md`.
- Dépendance amont : [DATA_scinder-source-authorships](archived/2026-07-03_DATA_scinder-source-authorships.md) (terminé).
- Chantier lié : [DATA_personnes-dedoublonnage-assiste](DATA_personnes-dedoublonnage-assiste.md).
- Cadre token / garde pairwise : [archived/2026-06-26_DATA_dedup-pairwise-gated](archived/2026-06-26_DATA_dedup-pairwise-gated.md).
