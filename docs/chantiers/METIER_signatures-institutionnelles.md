# Chantier — Signatures institutionnelles

Mesurer, pour chaque personne, la part de ses publications dont l'adresse mentionne l'université.

## Contexte

Une partie des publications de l'Alliance UCA est absente des publications de l'université dans les bases bibliographiques : l'adresse de l'auteur omet l'université. Cas typique : un enseignant-chercheur de l'UCA qui exerce au CHU signe « CHU Clermont-Ferrand » seul.

Le moissonnage interroge le périmètre Alliance UCA (`perimeter_extraction`). L'entrée d'une contribution source dans le périmètre se calcule sur le périmètre UCA (`perimeter_persons`). Une contribution source dont l'adresse cite seulement le CHU est donc moissonnée, mais reste hors périmètre. Elle entre dans le périmètre par un autre indice : identifiant d'une personne RH (ORCID, idHAL, IdRef), structure HAL du laboratoire. Sans ces indices, elle reste sans personne : la phase `persons` rattache une contribution hors périmètre seulement par identifiant. Son enregistrement source reste sans publication si aucun coauteur n'est dans le périmètre.

Seules OpenAlex, Web of Science, Crossref et DataCite donnent le texte de l'adresse. Chez Crossref et DataCite, la chaîne est parfois le seul nom de l'établissement, transmis par l'éditeur. HAL, ScanR et theses.fr donnent des structures de leur référentiel.

`address_structures` rattache une adresse à chaque structure dont une forme de nom figure dans le texte : université, laboratoire, CHU, organisme. OpenAlex pose aussi des ROR sur chaque affiliation (`source_contribution_rors`). Il ajoute souvent le ROR du parent quand l'adresse cite l'enfant. Quand l'adresse cite seulement le CHU, le ROR du CHU est souvent le seul.

`hr_records` contient une fiche par personne, avec une seule période (`start_date`, `end_date`). L'export du 15/12/2025 couvre seulement les enseignants-chercheurs de l'UCA.

## Décisions

1. **Ordre du chantier** : mesurer d'abord ce qui manque, par requêtes hors pipeline, enregistrements sources sans publication compris. Publier ensuite un indicateur par personne. Inclure enfin les publications de l'Alliance absentes du périmètre.
2. **Population** : les personnes du référentiel RH.
3. **Dénominateur** : les publications de la personne parues pendant sa période RH, avec une tolérance en fin de période. Une publication dont les adresses de la personne citent seulement des structures hors Alliance est comptée à part et sort du dénominateur.
4. **Indicateur, en trois comptes par personne** : publications ; parmi elles, publications avec une adresse exploitable ; parmi celles-ci, publications dont une adresse mentionne l'université.
5. **Adresse exploitable** : texte d'affiliation d'OpenAlex ou de WoS ; de Crossref ou DataCite quand la chaîne est une adresse, et pas le seul nom de l'établissement.
6. **Mention de l'université**, sous n'importe quelle forme : `address_structures` rattache l'adresse à l'université elle-même. Un laboratoire de l'université cité seul ne vaut pas mention.
7. **Grain de la publication** : une publication compte une fois par personne. Les comptes sont aussi donnés par source.
8. **ROR d'OpenAlex** : mesure d'appoint, à côté du texte.
9. **Restitution** : tableau de bord de la personne, visible de l'administration seulement.

## Phasage

### Phase 1 — Audit

- [x] Enregistrements sources sans contribution rattachée à la personne : rapprocher par le nom les personnes RH des contributions sources hors périmètre dont l'adresse cite une structure de l'Alliance, pendant la période RH (`interfaces/cli/oneshot/measure_university_mention.py`, 41d5aab8d). Base locale, 2026-10-27 : 1 692 couples (personne, travail) absents des publications de la personne, pour 155 personnes RH, presque toutes de l'UFR de médecine. 1 808 contributions sources sont sans publication. 615 sont dans une publication, souvent du périmètre, mais sans personne : la phase `persons` rattache une contribution hors périmètre seulement par identifiant.
- [ ] Classement des adresses sans l'université, sur les publications rattachées et sur les enregistrements sources rapprochés : structure de l'Alliance hors UCA, structure hors Alliance, aucune structure reconnue.
- [ ] Sources divergentes : examiner sur pièces les publications où une source mentionne l'université et une autre non, pour la même personne. Distinguer l'erreur de source de l'erreur de fusion des enregistrements sources.
- [ ] ROR d'OpenAlex sur les adresses sans l'université : part avec le ROR de l'université, part avec le seul ROR du CHU.
- [ ] Crossref et DataCite : séparer les adresses des noms d'établissement, par comparaison avec la chaîne OpenAlex du même auteur.

### Phase 2 — Indicateur par personne

- [ ] Calcul des trois comptes par personne.
- [ ] Affichage sur le tableau de bord de la personne, réservé à l'administration.
- [ ] Liste des publications sans mention de l'université, ouverte depuis l'indicateur.

### Phase 3 — Publications de l'Alliance hors périmètre

- [ ] Choisir la voie d'inclusion. Pistes :
  - rapprochement par le nom, dans la phase `persons`, des contributions sources dont l'adresse cite une structure de l'Alliance, sans création de personne ;
  - `perimeter_persons` sur le périmètre Alliance UCA. Ce périmètre fixe aussi l'entrée des contributions sources dans le périmètre, donc le périmètre des publications et le nom de l'établissement affiché.
- [ ] Mesurer l'effet sur les publications, les contributions et les personnes du périmètre.

## Questions ouvertes

- **Indicateur et publications manquantes** : calculé sur les publications rattachées à la personne, l'indicateur omet les cas visés, restés en enregistrements sources sans contribution rattachée. L'inclusion (phase 3) doit-elle précéder la publication de l'indicateur ?
- **Sources divergentes** : quelle règle de comptage, d'après l'examen de la phase 1 ?
- **Tolérance de fin de période** : quelle durée ? L'indice `hr_record` retient les documents parus entre l'année qui suit l'arrivée et la fin du contrat.
- **Personnes hors référentiel RH** : chercheurs des organismes, doctorants, contractuels, émérites. Sans période connue, aucune attente de mention.
- **Mention reconnaissable** : quelles formes de l'université permettent à WoS de relier la publication à l'établissement ?
- **Conformité de forme** : la convention de signature (cf. Liens) impose une ligne unique, dans cet ordre : université, tutelles, laboratoire, code postal, ville, pays. Faut-il mesurer aussi les écarts de forme, d'ordre et d'éléments ?
- **Liste blanche des `doc_type`** au dénominateur : quels types retenir ?
- **Conséquences du périmètre Alliance UCA** comme `perimeter_persons` : personnes créées pour les chercheurs de l'Alliance hors UCA ; publications de l'Alliance sans auteur de l'université comptées dans les publications de l'université.
- **Périmètre d'une publication rapprochée par le nom** : la contribution d'une personne RH, rattachée par le nom sur une adresse de l'Alliance, fait-elle entrer la publication dans le périmètre ? L'indice `hr_record` suppose un identifiant.

## Liens

- Convention de signature : <https://www.uca.fr/recherche/science-ouverte-et-publication/politique-de-signature-des-publications>
- Tables : `addresses`, `source_contribution_addresses`, `address_structures`, `source_contribution_rors`, `structures`, `perimeters`, `hr_records`.
- Phase `affiliations` : `pipeline/transformation/structures/`.
