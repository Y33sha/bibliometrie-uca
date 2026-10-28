# Chantier — Types de document

## Contexte

Le type d'une publication (`doc_type`) se décide par arbitrage entre ses enregistrements sources (`domain/publications/aggregation.py`). Le premier type renseigné dans l'ordre de priorité des sources l'emporte, et un sous-type d'article l'emporte sur `article`. La correspondance des types bruts de chaque source est dans `domain/source_records/doc_types.py`. Les familles d'affichage (`DOC_TYPE_FAMILIES`, `docTypeFamilies` côté frontend) rangent les types en Publications, Prépublications, Thèses, Données et Annexes et divers.

### Mesures du 2026-10-28

Publications du périmètre, par type : `conference` 10 031, `conference_paper` 4 544, `other` 3 025, `poster` 2 200, `media` 844, `erratum` 301, `data_paper` 73, `proceedings` 41, `retraction` 11.

- 182 errata sur 301 sont reliés à la publication corrigée (`is_correction_of`). Aucune rétractation n'est reliée à une publication.
- `media` réunit surtout des interventions dans la presse, typées par correction (type de la revue, préfixe du titre).
- Les 128 enregistrements DataCite `Audiovisual` sont aussi typés `media` : pièces numérotées d'un corpus Nakala (45 publications), captations de séminaires et de conférences, vidéos jointes à un article.
- DataCite `Sound` donne `other`, HAL `SON` et `VIDEO` donnent `media`.
- 404 publications sont typées `other` alors qu'une source moins prioritaire donne un type précis. Le `other` vient surtout de DataCite `Text` et de Crossref (`other`, `journal-issue`, `posted-content_other`). Le type précis vient surtout d'OpenAlex (`article`), sans revue.
- 349 publications sont typées `article` d'après OpenAlex seul, sans revue. Un échantillon mêle de vrais articles déposés en entrepôt et des documents d'une autre nature (communication de congrès, introduction).

## Décisions

- Une famille « Conférences » réunit les communications : communication filmée, poster, présentation ou résumé.
- `data_paper` rejoint la famille des données et logiciels.
- Erratum et rétractation quittent les listes de documents. Ils sont rattachés à la publication concernée.

## Phasage

### Phase 1 — Types et familles

- [ ] Type de la communication filmée. Correspondance de DataCite `Audiovisual` et `Sound`, de HAL `VIDEO` et `SON`.
- [ ] Famille « Conférences ».
- [ ] posters et communications réunis sous un même DOI
- [ ] `data_paper` dans la famille des données et logiciels.
- [ ] Libellé de `media`, réservé aux interventions dans la presse.
- [ ] DUMAS: comment distinguer mémoires et thèses d'exercice?

### Phase 2 — Errata et rétractations

- [ ] Erratum et rétractation hors des listes de documents, affichés sur la publication concernée.
- [ ] Relation entre une rétractation et la publication rétractée.

### Phase 3 — Arbitrage

- [ ] `other` d'une source prioritaire face au type précis d'une autre source, compte tenu du type `article` qu'OpenAlex attribue par défaut.

### Phase 4 — Cas particuliers

- [ ] 100685 : typée preprint.
- [ ] 107270 et 869915 « Computing Pivot-Minors » : article typé preprint par OpenAlex. Déduction du DOI depuis l'identifiant arXiv, et inversement.
- [ ] 206476 : communication de congrès déposée en entrepôt, typée `article` par OpenAlex seul.
* [ ] 165068 type "commmentary"; 86931 type "meeting report" => comment prendre en compte ces types (et empêcher openalex d'imposer le type article)
* [ ] règle à créer: si DOI de forme ISBN + _n => conference_paper ou chapitre / si forme ISBN: proceedings ou book (trancher selon type du "journal")
* [ ] doc_types souvent suspects, à investiguer: "preprint", "autre" (voir aussi si le type "article" peut être affiné selon des critères objectifs: ie la revue)
* [ ] goldschmidt abstracts: faire un nouveau type abstract, ou le mettre comme "conférence"?
* "(No longer) Hiking hypothetical trails in one direction: How unidirectional comparisons hinder theoretical progress in social psychology, and how reversing the direction of comparisons can advance it" => openalex type "article"

### Phase 5 — Documentation

- [ ] Mise à jour de la documentation.

## Questions ouvertes

- `conference_paper` : famille Publications (texte publié) ou famille Conférences.
- Pièces d'un corpus Nakala (257102) : publications distinctes, ou éléments d'un jeu de données.
- « Meeting report » publié en revue, typé `article` par toutes les sources (176417, 180148, 16340).
