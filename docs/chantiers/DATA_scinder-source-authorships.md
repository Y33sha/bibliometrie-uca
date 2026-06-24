# Chantier — Scinder `source_authorships` (identité ⊥ liaison)

Étudier la décomposition de `source_authorships` en deux tables : une table des **éléments d'identification** des auteurs (formes de nom et identifiants, dédupliqués), et une table de **liaison** pure entre authorships sources et publications (position, rôles, correspondant, pays issus des adresses). L'enjeu n'est pas tant le gain de place — réel mais modéré — que la possibilité de ramener le matching personnes et les diagnostics de dédoublonnage à l'échelle des identités distinctes (centaines de milliers) plutôt qu'à celle des lignes (dizaines de millions). Gros impact sur le pipeline, donc à instruire avant de décider.

## Contexte

### La table et sa redondance

`source_authorships` porte une ligne par authorship source : la relation (`source`, `source_publication_id`, `author_position`, `in_perimeter`, `is_corresponding`, `roles`, `countries`, `authorship_id`) et l'identification de l'auteur (`person_id`, `author_name_normalized`, `raw_author_name`, `person_identifiers`). Les colonnes d'identification sont massivement répétées : une même personne y figure en moyenne une cinquantaine de fois, autant que de signatures qu'elle a déposées.

### Mesures sur une base de travail (≈ 16,75 M lignes ; ≈ 19 M en production)

La table pèse environ 3,3 Go : ≈ 2,58 Go de heap et ≈ 0,74 Go d'index, dont la clé primaire (≈ 0,36 Go) et l'unique `(source_publication_id, author_position)` (≈ 0,36 Go) à eux seuls. Les identités distinctes au sens `(author_name_normalized, person_identifiers)` sont ≈ 645 000 (≈ 657 000 en ajoutant `person_id` à la clé), soit un facteur de répétition d'environ 25. Le `person_id` est `NULL` sur ≈ 95 % des lignes (≈ 764 000 lignes liées, ≈ 16 500 personnes distinctes). Le `person_identifiers` est `NULL` sur ≈ 64 % des lignes ; ≈ 218 000 identités distinctes portent un identifiant fort.

### Ce que mesure la cascade de matching

La résolution personne enchaîne, du plus fiable au moins fiable : ORCID déposé par l'auteur, `hal_person_id`, IdRef (chacun corroboré par compatibilité de nom), puis cross-source par `(publication_id, author_position)`, puis forme de nom (match unique / ambigu / création). Deux régimes s'en dégagent. Les barreaux **sans contexte** — identifiants forts corroborés par le nom, forme de nom unique, création — ne dépendent que de la signature `(nom, identifiants)` : ils sont calculables une fois par identité distincte. Les barreaux **contextuels** — cross-source, et la garde de rejet d'une paire personne × publication — dépendent de la publication et de la position, irréductibles à l'identité seule. Les variantes `_dubious` d'identifiants (identifiant porté par deux positions d'auteur d'un même enregistrement, donc corruption) ne sont jamais signal : invisibles au matching dès la normalisation.

## Décisions

Ces décisions sont des orientations proposées, à confirmer ou amender ; seul le contexte ci-dessus est factuel.

1. **Modèle à deux niveaux.** Une table `author_identifying_keys` des identités distinctes `(formes de nom, identifiants)`, indépendante du contexte ; une table `source_authorships` allégée portant la liaison (publication, position, rôles, correspondant, pays, périmètre) et une référence vers l'identité.

2. **Le `person_id` de la table d'identités est un index de matching recalculable, pas la donnée autoritaire.** L'autorité reste sur `source_authorships` (puis `authorships`). La table d'identités matérialise le verdict des barreaux sans contexte pour accélérer et factoriser leur calcul ; elle est recalculable depuis les statuts d'identifiants et les formes de nom.

3. **Une colonne `matched_by` trace la provenance du verdict** et sert de clé d'invalidation : ses valeurs reprennent les raisons de la cascade calculables au niveau identité (`orcid`, `hal_person_id`, `idref`, `single_name`, `new`). Le `cross_source` et la garde de rejet par publication restent au niveau de la liaison, contextuels.

4. **Invalidation maîtrisée, sans écrasement.** Le rejet d'un identifiant invalide les identités résolues par cet identifiant (recalcul, repli sur le signal suivant). L'ajout d'une personne sur une forme de nom déjà résolue rend la forme ambiguë et annule le verdict des identités résolues par cette forme. Dans tous les cas, le `NULL` d'une identité ne redescend jamais sur le `person_id` déjà posé sur `source_authorships` : les rattachements existants (souvent confirmés) ne sont révisés que par le mécanisme de rejet, pas par une simple ré-ambiguïsation.

5. **Vue matérialisée d'abord, migration ensuite.** Avant toute migration structurelle, une vue matérialisée en lecture seule `(author_name_normalized, person_identifiers, person_id)` rafraîchie à la demande donne l'essentiel du bénéfice diagnostique pour le dédoublonnage, sans toucher au write-path ni installer de machinerie d'invalidation, et entièrement réversible. La décomposition permanente n'est tranchée que si le pipeline lui-même y gagne assez — calculer le matching par identifiant et par nom une fois par identité distincte plutôt qu'une fois par ligne.

## Gains attendus et limites

- **Place : ≈ 1 Go (≈ 30 %), pas le facteur 25 que suggère le ratio de lignes.** Les deux plus gros index (clé primaire et unique `(source_publication_id, author_position)`, ≈ 0,72 Go) indexent des colonnes qui restent sur la liaison et ne rétrécissent pas ; la liaison garde ses 16-19 M de lignes avec leur surcoût de tuple ; les données déplacées sont creuses (identifiants absents sur 64 % des lignes, `person_id` sur 95 %).
- **Matching : un gain de coût de calcul.** Les barreaux sans contexte (identifiants forts corroborés, forme de nom, création) se calculent une fois par identité distincte (≈ 645 000 au total, ≈ 218 000 portant un identifiant fort) au lieu d'une fois par ligne (16-19 M). C'est le coût du calcul qui chute, pas le nombre de rattachements. Le résiduel ambigu, seul cas réellement à l'échelle de la liaison, est isolé et traité au niveau contextuel.
- **Diagnostics de dédoublonnage : accélération et bon grain.** Le grain « lignes par personne » mélange auteur prolifique et sur-agglomération (jusqu'à plusieurs milliers de lignes pour une personne), là où le grain « identités distinctes par personne » isole le suspect (quelques dizaines au plus). Les diagnostics « même identifiant porté par plusieurs personnes » et « variantes `_dubious` corroborées par un jumeau non-dubious » deviennent des requêtes triviales sur une table de quelques centaines de milliers de lignes.
- **Limites.** La remédiation (lever en masse des `_dubious`, re-lier des paires) réécrit toujours la liaison à grande échelle : seule la détection rétrécit. Le `matched_by` n'est pas stocké aujourd'hui ; le persister est une modification de schéma, et c'est là que vit la complexité d'invalidation. Les diagnostics cités ci-dessus, eux, n'en ont pas besoin : ils portent sur les faits `(nom, identifiant, person_id)` seuls, d'où l'intérêt de la vue matérialisée comme première étape.

## Phasage

### Phase 0 — Vue matérialisée diagnostique (réversible, sans write-path)

- [ ] Vue matérialisée `(author_name_normalized, person_identifiers, person_id)` avec index sur `person_id`, rafraîchie à la demande.
- [ ] Valider sur cette vue les diagnostics de dédoublonnage (identités par personne, identifiant partagé entre personnes, `_dubious` corroborables).

### Phase 1 — Instruction de l'impact

- [ ] Tracer exhaustivement producteurs et consommateurs de `source_authorships` (normalisation qui écrit, phase personnes, interfaces API et frontend, scripts ponctuels).
- [ ] Chiffrer le coût de migration et confirmer le gain de place sur le volume de production.

### Phase 2 — Schéma

- [ ] Table `author_identifying_keys` (formes de nom, identifiants, `person_id`, `matched_by`) et référence depuis `source_authorships` allégée.
- [ ] Migration des données existantes vers le modèle à deux niveaux.

### Phase 3 — Réécriture de la résolution

- [ ] Résoudre les barreaux sans contexte au niveau identité (identifiants forts corroborés, forme de nom, création) puis propager vers la liaison.
- [ ] Conserver `cross_source` et la garde de rejet par publication au niveau de la liaison.

### Phase 4 — Invalidation

- [ ] Recalcul des identités sur rejet d'identifiant et sur ambiguïsation d'une forme de nom, sans écraser les `person_id` posés sur `source_authorships`.

## Questions ouvertes

- **`raw_author_name` : sur l'identité ou sur la liaison ?** L'inclure dans la clé d'identité fait passer le décompte de ≈ 645 000 à ≈ 743 000 ; à arbitrer selon qu'on veut conserver toutes les formes brutes par identité.
- **`person_id` dérivé ou matérialisé ?** Le propager et le matérialiser sur `source_authorships` garde le contrat de lecture inchangé pour les consommateurs (aucune jointure imposée) ; la dérivation au read-time par jointure évite la redondance mais impose la jointure partout. Recommandation : matérialiser, la table d'identités restant un accélérateur interne.
- **Gain de place réel en production** (≈ 19 M de lignes) à mesurer avant décision.
- **Périmètre de la Phase 0** : la vue matérialisée suffit-elle à valider le bénéfice, ou faut-il aller jusqu'au `matched_by` matérialisé pour certains diagnostics ?

## Liens

- Tables : `source_authorships`, `source_authorship_addresses`, `authorships`, `persons`, `person_name_forms`, `person_identifiers`.
- Phase personnes : `application/pipeline/persons/create_persons_from_source_authorships.py`.
- Règles de matching : `domain/persons/matching.py`, `domain/persons/identifiers.py`.
- Chantier lié : [DATA_personnes-dedoublonnage-assiste](DATA_personnes-dedoublonnage-assiste.md).
