# Chantier — Types de document

## Contexte

Le type d'une publication (`doc_type`) se décide par arbitrage entre ses enregistrements sources (`domain/publications/aggregation.py`). Le premier type renseigné dans l'ordre de priorité des sources l'emporte, et un sous-type d'article l'emporte sur `article`. La correspondance des types bruts de chaque source est dans `domain/source_records/doc_types.py`. Les familles d'affichage (`DOC_TYPE_FAMILIES`) rangent les types en Publications, Prépublications, Thèses, Données et Annexes et divers.

### Mesures du 2026-10-28

Publications du périmètre, par type : `conference` 10 031, `conference_paper` 4 544, `other` 3 025, `poster` 2 200, `media` 844, `erratum` 301, `data_paper` 73, `proceedings` 41, `retraction` 11.

- 182 errata sur 301 sont reliés à la publication corrigée (`is_correction_of`). Aucune rétractation n'est reliée à une publication.
- `media` réunit surtout des interventions dans la presse, typées par correction (type de la revue, préfixe du titre).
- Les 128 enregistrements DataCite `Audiovisual` sont typés `media` : pièces numérotées d'un corpus Nakala (45 publications), captations de séminaires et de conférences, vidéos jointes à un article.
- HAL `VIDEO` et `SON`, DataCite `Sound` donnent `other`. HAL `VIDEO` réunit surtout des captations de conférences, mais aussi des films et des interviews. HAL `SON` réunit surtout des podcasts et des émissions de radio.
- 404 publications sont typées `other` alors qu'une source moins prioritaire donne un type précis. Le `other` vient surtout de DataCite `Text` et de Crossref (`other`, `journal-issue`, `posted-content_other`). Le type précis vient surtout d'OpenAlex (`article`), sans revue.
- 349 publications sont typées `article` d'après OpenAlex seul, sans revue. Un échantillon mêle de vrais articles déposés en entrepôt et des documents d'une autre nature (communication de congrès, introduction).

### Mesures du 2026-10-29 (base locale)

Les 11 047 publications `conference` du périmètre se répartissent ainsi :

| Origine | Publications |
|---|---|
| Communication HAL sans texte publié | 9 099 |
| Résumé OpenAlex ou WoS | 1 482 |
| Recueil de résumés HAL | 226 |
| DataCite `Presentation` | 40 |
| Crossref, présentation orale (EGU) | 4 |
| Autre | 196 |

Deux tiers des enregistrements sources HAL de ces communications sont sans résumé ni fichier. 13 % ont un fichier déposé : diaporama, résumé ou texte, indiscernables par les métadonnées.

Les 2 116 enregistrements sources HAL de DUMAS (`dumas-`) sont de type HAL `MEM`, donc `memoir`, type exclu des publications. Le diplôme est dans le TEI (`label_xml`, `<note type="degree" n="…">`), présent dans le raw store pour 2 110 d'entre eux. Les libellés des codes sont dans le référentiel HAL (`ref/metadataList`, `metaName_s:dumas_degreeType`).

| Diplôme (code) | Enregistrements sources |
|---|---|
| Thèse d'exercice de médecine (12) | 1 058 |
| Thèse d'exercice de pharmacie (13) | 375 |
| Mémoire du diplôme d'État de sage-femme (14) | 206 |
| Thèse d'exercice en chirurgie dentaire (30) | 170 |
| Mémoire du certificat de capacité d'orthophoniste (37) | 108 |
| Mémoire du diplôme d'État d'ergothérapeute (52) | 89 |
| Mémoire de master 2 (1) | 88 |
| Mémoire du certificat de capacité d'orthoptiste (53) | 11 |
| Autres mémoires (2, 3, 10) | 5 |

OpenAlex et ScanR ont 1 468 enregistrements sources `memoir` avec une URL DUMAS.

## Décisions

- Les libellés des types, les familles et leur ordre sont définis dans le domaine. L'API les sert au frontend.
- Une famille « Conférences » réunit `recorded_talk` (« Conférence filmée »), `conference` (« Communication ») et `poster`. Elle suit la famille Publications dans l'ordre d'affichage.
- `conference_paper` reste dans la famille Publications.
- HAL `VIDEO` et DataCite `Audiovisual` donnent `recorded_talk`. Les règles de correction par le titre (interview, fichiers complémentaires) s'appliquent à ce type.
- HAL `SON` et DataCite `Sound` donnent `media`.
- `data_paper` rejoint la famille des données et logiciels.
- Erratum et rétractation quittent les listes de documents. Ils sont rattachés à la publication concernée.

## Phasage

### Phase 1 — Types et familles

- [x] Libellés et familles des types servis par l'API depuis le domaine, chargés par le frontend avant l'affichage. 626a9c589
- [x] Type `recorded_talk`. Correspondance de HAL `VIDEO` et DataCite `Audiovisual`. Règles de correction par le titre étendues à ce type, préfixes de vidéos complémentaires. 81a80a286
- [x] HAL `SON` et DataCite `Sound` vers `media`. HAL `PRESCONF` vers `conference`. c2e424844
- [x] `conference` libellé « Communication ». 418245fae
- [x] Famille « Conférences ». 6e834b66d
- [x] Palette des couleurs des types et des familles.
- [x] `data_paper` dans la famille des données et logiciels.
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

- Pièces d'un corpus Nakala (257102) : publications distinctes, ou éléments d'un jeu de données.
- Films, bandes-annonces et MOOC en `recorded_talk` par la correspondance de HAL `VIDEO` et DataCite `Audiovisual`.
- « Meeting report » publié en revue, typé `article` par toutes les sources (176417, 180148, 16340).
