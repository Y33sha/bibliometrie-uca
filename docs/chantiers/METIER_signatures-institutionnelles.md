# Chantier — Signatures institutionnelles

Mesurer, par auteur et par structure, le taux de publications portant une signature correcte.

## Contexte

Une signature est une chaîne d'affiliation portée par la publication. Seules OpenAlex, Web of Science, Crossref et DataCite en donnent le texte. HAL, ScanR et theses.fr donnent des noms de structures issus de leur référentiel : la mesure les exclut.

La convention de signature de l'établissement (cf. Liens) impose une ligne unique, dans cet ordre : université, tutelles, laboratoire, code postal, ville, pays. L'acronyme du laboratoire est attendu, son numéro d'unité écarté. Les partenaires associés figurent seulement si un coauteur en relève.

Deux critères font la justesse d'une signature.

1. **Présence de l'université** là où elle est attendue.
2. **Conformité de forme** à la convention : les bons éléments, sous la bonne forme, dans le bon ordre.

`persons_rh` fonde l'attente : une personne dont la fiche RH couvre l'année de publication relève de l'établissement, donc sa signature doit mentionner l'université. La fiche donne un service (`department_name`), pas un laboratoire. Le texte de l'adresse fournit d'autres signaux : un laboratoire du périmètre mentionné sans l'université, un partenaire associé mentionné seul.

La base porte le reste du matériau : `addresses` stocke le texte des signatures, `address_structures` les structures reconnues dans chacune, `structures.structure_type` leur type (`universite`, `labo`, `onr`, `chu`, `ecole`), `perimeters.root_structure_ids` les racines de l'établissement.

Rien ne porte la convention. `structure_name_forms` liste les formes reconnues d'un nom de structure, sans forme recommandée ni ordre des éléments.

Côté interface, `admin/addresses` liste et filtre les adresses, affiche le nombre de publications de chacune et ouvre la liste de ces publications. `admin/structures` gère les structures et leurs formes de nom.

## Décisions

Orientations à confirmer ou amender.

1. **Juger le référencement de l'université.** L'identité du laboratoire mentionné reste hors critère : le référentiel RH donne un département, pas un laboratoire.
2. **Deux critères mesurés séparément** : présence attendue et conformité de forme.
3. **La convention est une donnée d'établissement**, donc un référentiel plutôt qu'une règle en dur.
4. **Grain de la publication.** Une publication porte parfois plusieurs signatures pour un même auteur. Le taux compte chaque publication une fois par auteur et une fois par structure.
5. **Sources restreintes** à celles qui portent le texte de la signature.
6. **Dénominateur restreint** aux `doc_type` d'une liste blanche.
7. **Attente de mention établie empiriquement**, depuis les cas observés.
8. **Restitution** : les taux dans les tableaux de bord, le détail par adresse dans l'administration seulement.

## Phasage

### Phase 1 — Attente de mention

- [ ] Rapprocher les signatures des fiches RH, en confrontant la période de la fiche à l'année de publication.
- [ ] Compléter par les signaux tirés du texte : laboratoire du périmètre mentionné seul, partenaire associé mentionné seul, autre tutelle mentionnée seule.
- [ ] Inventorier les signatures où l'université manque alors qu'elle est attendue.
- [ ] Séparer le défaut de signature de la forme absente de `structure_name_forms`.

### Phase 2 — Conformité de forme

- [ ] Modéliser la convention : éléments attendus, forme de chacun, ordre.
- [ ] Contrôler une signature contre la convention.
- [ ] Qualifier les écarts par gravité : ordre des éléments, forme du nom de l'université, code postal, numéro d'unité présent.

### Phase 3 — Taux

- [ ] Taux de signatures correctes par auteur et par structure, au grain de la publication.
- [ ] Liste blanche de `doc_type` au dénominateur.

### Phase 4 — Restitution

- [ ] Taux dans les tableaux de bord personne et laboratoire.
- [ ] Liste des publications à signature incorrecte dans l'administration.

## Questions ouvertes

- **Couverture du référentiel RH** : quelles populations les exports couvrent-ils ? Doctorants, contractuels et émérites signent aussi.
- **Période RH et année de publication** : une publication paraît souvent après le travail qu'elle rapporte. Faut-il élargir la fenêtre au-delà des dates de la fiche ?
- **Sources divergentes** : deux sources donnent parfois des chaînes différentes pour le même auteur sur la même publication. Laquelle fait foi ?
- **Publications sans chaîne d'affiliation**, connues seulement de HAL, ScanR ou theses.fr : exclues du dénominateur, ou comptées comme non signées ?
- **Liste blanche des `doc_type`** : quels types retenir ?
- **Gravité des écarts de forme** : un taux unique, ou un taux par niveau de gravité ?

## Liens

- Convention de signature : <https://www.uca.fr/recherche/science-ouverte-et-publication/politique-de-signature-des-publications>
- Tables : `addresses`, `source_authorship_addresses`, `address_structures`, `structures`, `structure_name_forms`, `perimeters`, `persons_rh`.
- Phase `affiliations` : `application/pipeline/affiliations/`.
- Administration : `interfaces/frontend/src/routes/admin/addresses/`, `interfaces/frontend/src/routes/admin/structures/`.
