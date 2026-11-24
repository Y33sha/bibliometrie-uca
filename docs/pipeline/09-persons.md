# Résolution et création des personnes

*À jour le 2026-11-24.*

La phase `persons` rattache chaque [contribution](../donnees/04-contributions.md) à une [personne](../donnees/05-persons.md). Elle décide la personne à partir de toutes les contributions sources alignées dans la contribution.

Une contribution du périmètre au nom inconnu fonde une personne, d'après le nom d'une de ses contributions sources. Les contributions au même nom, dans d'autres publications, la rejoignent dans le même passage. Une contribution aux seuls rôles de jury de thèse ou d'inventeur ne fonde pas de personne.

- **`resolve_contributions`** — rattache les contributions à une personne, et crée les personnes des noms inconnus.
- **`populate_person_name_forms`** — régénère les formes de nom des personnes, à partir du nom de chaque personne et du nom des contributions sources de ses contributions.
- **`purge_persons`** — met en file de redécision les contributions rattachées par le nom dont la décision change, puis supprime les personnes sans contribution du périmètre.

## Rattacher une contribution à une personne

Les critères sont interrogés dans l'ordre, du plus fiable au moins fiable. Le premier qui désigne une personne l'emporte. À chaque critère, les candidats de la contribution sont l'intersection des candidats non vides de ses contributions sources. Une intersection vide ou de plusieurs personnes laisse la contribution sans personne.

- **Épinglage** : une contribution source alignée est épinglée à une personne par l'administration.

- **ORCID** : ORCID présent dans les métadonnées Crossref, DataCite ou INSPIRE-HEP de la publication, dans le `raw_orcid` d'OpenAlex, ou dans le TEI HAL (`label_xml`). Les ORCID attribués par algorithme (OpenAlex `author.orcid`, WoS, ScanR) sont écartés.

- **Compte HAL** : `hal_person_id`, attaché à la contribution source dans le TEI.

- **Identifiant IdRef** : PPN SUDOC (HAL TEI, ScanR, theses.fr), référentiel personnes de l'ESR.

- **Forme de nom** : le nom normalisé d'une contribution source désigne une seule personne dans `person_name_forms`, ou, à défaut, une seule personne aux initiales compatibles.

- **Départage** : quand le nom désigne plusieurs personnes, une cascade d'indices compare la publication aux autres publications de chaque personne candidate. Indices, dans l'ordre : coauteurs (un partagé, puis deux), laboratoire du référentiel, structure HAL (laboratoire, équipe, département), revue, années d'activité. Le premier indice partagé par une seule personne candidate la désigne (`domain/persons/tie_break.py`).

Dans une publication, une personne revient à une seule contribution : la mieux appuyée (épinglage, puis identifiant, puis nom, puis départage).

> **Corroboration par le nom.** Un rattachement par identifiant (ORCID, `hal_person_id`, IdRef) est retenu seulement si le nom de la contribution source qui le contient est compatible avec celui du titulaire de la valeur : un identifiant recopié sur le mauvais co-auteur est refusé.

> **Garde de rejet.** Les personnes rejetées pour la publication (`rejected_contributions`) sont écartées des candidats de chaque critère. Ce retrait peut lever l'ambiguïté d'un nom partagé.

### Contributions hors périmètre

Une contribution sans contribution source du périmètre est rattachée seulement par épinglage ou par identifiant. Le critère de nom vaut seulement pour les contributions du périmètre. Une personne marquée hors périmètre gagne des contributions hors périmètre seulement par épinglage.

## Rattachements conservés d'un run à l'autre

La phase décide les contributions sans personne. Une contribution rattachée garde sa personne d'un run à l'autre. Elle entre dans une file de redécision dans quatre cas :

- ses contributions sources alignées changent (phase `author_grouping`) ;
- l'arbitrage des identifiants neutralise l'identifiant qui l'a rattachée ;
- l'administration rejette l'identifiant ou la forme de nom qui l'a rattachée ;
- la décision d'un rattachement par le nom ou par départage change, face à la forme de nom d'une autre personne (purge).

La phase redécide les contributions de la file, sauf les contributions épinglées. Une contribution qui désigne encore sa personne la garde, sans écriture. Une contribution qui en désigne une autre en change. Une contribution que rien ne soutient plus perd sa personne. Une contribution perd aussi sa personne quand celle-ci est supprimée.

## Données préservées

Les saisies manuelles (épinglage d'une contribution source, formes de nom confirmées ou rejetées, personnes déclarées distinctes) et les données importées (fiches du référentiel RH) sont des entrées fixes, jamais réinitialisées.

Une personne sans contribution du périmètre est supprimée, sauf si elle est présente dans le référentiel RH ou fait l'objet d'une décision humaine. Ses contributions perdent leur personne.

## Attributions suspectes (`suspect_attributions`)

La phase `suspect_attributions` suit `persons`. Elle recalcule à chaque run la file des attributions suspectes (`suspect_contributions`), soumise à l'administration. Deux motifs :

- **cluster isolé** : les publications d'une personne à fiche RH forment un graphe. Deux publications sont reliées par leurs indices partagés : coauteurs, laboratoires, structures HAL, revue, thèmes OpenAlex, domaines HAL. Chaque indice est pondéré par sa rareté. La partition de Leiden découpe le graphe en clusters. Un cluster est signalé hors du cluster principal, sans contribution ancrée (ORCID, épinglage), avec peu de liens vers le reste, et au moins deux publications signalables ;
- **ressemblance aux rejets** : pour une personne ayant au moins un rejet, la cascade de départage compare chaque publication au profil de la personne et au profil de ses publications rejetées. Une publication désignée par le profil des rejets est signalée.

Sont signalables les contributions rattachées par IdRef, idHAL ou un ORCID donné par HAL seul, et celles rattachées par le nom dans une publication de plus de 100 contributions. Une adresse rattachée à une structure du périmètre protège la contribution. L'administration tranche : le rejet détache la contribution, la confirmation l'épingle (`domain/persons/suspect_attributions.py`).

## Arbitrage des identifiants (`normalize.arbitrate_identifiers`)

La tâche clôt la normalisation, avant le périmètre et l'alignement des auteurs. Une valeur d'identifiant (ORCID, IdRef, `hal_person_id`) contenue dans des contributions sources sous des noms différents va au nom majoritaire. Les contributions sources qui la contiennent sous un autre nom la neutralisent : la valeur ne rattache plus la contribution à une personne, et ne la fait plus entrer dans le périmètre. Les collectifs et les doublons d'auteur ne votent pas.
