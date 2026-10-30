# Résolution et création des personnes

*À jour le 2026-10-26.*

La phase `persons` rattache chaque [contribution](../donnees/04-contributions.md) à une [personne](../donnees/05-persons.md). Elle décide la personne à partir de toutes les contributions sources alignées dans la contribution.

Une contribution du périmètre au nom inconnu fonde une personne, d'après le nom d'une de ses contributions sources. Les contributions au même nom, dans d'autres publications, la rejoignent dans le même passage.

## Rattacher une contribution à une personne

Les critères sont interrogés dans l'ordre, du plus fiable au moins fiable. Le premier qui désigne une personne l'emporte. Deux personnes désignées par le même critère laissent la contribution sans personne.

- **Épinglage** : une contribution source alignée est épinglée à une personne par l'administration.

- **ORCID déposé par l'auteur** : ORCID présent dans les métadonnées Crossref ou DataCite de la publication, dans le `raw_orcid` d'OpenAlex, ou dans le TEI HAL (`label_xml`). Les ORCID qu'une source attribue par algorithme (OpenAlex `author.orcid`, WoS) sont écartés.

- **Compte HAL** : `hal_person_id`, attaché à la contribution source dans le TEI.

- **Identifiant IdRef** : PPN SUDOC (HAL TEI, ScanR, theses.fr), référentiel personnes de l'ESR.

- **Forme de nom** : le nom normalisé d'une contribution source désigne une seule personne dans `person_name_forms`, ou, à défaut, une seule personne aux initiales compatibles. Les formes de nom sont régénérées à chaque exécution, à partir du nom de chaque personne et du nom des contributions sources de ses contributions. Un nom qui désigne plusieurs personnes laisse la contribution sans personne.

Dans une publication, une personne revient à une seule contribution : la mieux appuyée (épinglage, puis identifiant, puis nom).

> **Corroboration par le nom.** Un rattachement par identifiant (ORCID, `hal_person_id`, IdRef) est retenu seulement si le nom de la contribution source qui le contient est compatible avec celui du titulaire de la valeur : un identifiant recopié sur le mauvais co-auteur est refusé.

> **Garde de rejet.** Les personnes rejetées pour la publication (`rejected_contributions`) sont écartées des candidats de chaque critère. Ce retrait peut lever l'ambiguïté d'un nom partagé.

### Contributions hors périmètre

Une contribution sans contribution source du périmètre est rattachée seulement par épinglage ou par identifiant. Le critère de nom vaut seulement pour les contributions du périmètre.

## Rattachements conservés d'un run à l'autre

La phase décide les contributions sans personne. Une contribution rattachée garde sa personne d'un run à l'autre. Elle entre dans une file de redécision dans quatre cas :

- ses contributions sources alignées changent (phase `author_grouping`) ;
- l'arbitrage des identifiants neutralise l'identifiant qui l'a rattachée, ou le transfère à une autre personne ;
- l'administration rejette l'identifiant ou la forme de nom qui l'a rattachée ;
- la forme de nom qui fonde un rattachement par nom désigne plusieurs personnes (purge).

La phase redécide les contributions de la file, sauf les contributions épinglées. Une contribution qui désigne encore sa personne la garde, sans écriture. Une contribution qui en désigne une autre en change. Une contribution que rien ne soutient plus perd sa personne. Une contribution perd aussi sa personne quand celle-ci est supprimée.

## Données préservées

Les saisies manuelles (épinglage d'une contribution source, formes de nom confirmées ou rejetées, personnes déclarées distinctes) et les données importées (fiches du référentiel RH) sont des entrées fixes, jamais réinitialisées.

Une personne sans contribution du périmètre est supprimée, sauf si elle est présente dans le référentiel RH ou fait l'objet d'une décision humaine. Ses contributions perdent leur personne.
