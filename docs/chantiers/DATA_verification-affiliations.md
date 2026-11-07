# Chantier — Vérification des affiliations des sources

## Contexte

Une contribution source appartient au périmètre par ses indices (`perimeter_evidence`) : adresse, structure HAL, ROR, fiche RH, établissement de thèse. Chaque source donne ses indices pour sa propre contribution source. Une source attribue parfois à un auteur l'affiliation d'un autre auteur, ou une affiliation fausse. Une personne hors RH entrée dans le périmètre par une telle affiliation est une fausse personne du périmètre.

Le chantier [alignement des auteurs](archived/2026-10-24_DATA_alignement-auteurs.md) a relu les liens au périmètre établis par la seule contribution source scanR. Le lien était faux dans 12 cas sur 25 pour une structure, dans 10 cas sur 15 pour une adresse.

## Décisions

- Une contribution dont certaines contributions sources donnent un indice de périmètre et d'autres une affiliation hors périmètre est un cas conflictuel. Une file d'administration la présente pour décision.
- INSPIRE-HEP est moissonné par institution (numéro d'institution INSPIRE, à défaut chaîne d'affiliation) et par ORCID des personnes. La phase `fetch_missing` l'ignore, tant que le premier moissonnage ne révèle pas de manques importants.
- Le moissonnage demande seulement les champs utiles : ni nombre de citations, ni références.
- L'adresse d'une contribution source INSPIRE est le nom de l'institution rattachée par INSPIRE, avec son ROR quand INSPIRE le donne. L'affiliation brute est écartée : elle reproduit les décalages d'affiliations de l'éditeur. 0,2 % des auteurs ont une affiliation brute sans institution.
- L'identifiant CDS est un type d'identifiant d'enregistrement source.
- Un enregistrement source OpenAlex est sans contributions sources quand il partage un DOI, un DOI arXiv ou un identifiant CDS (CERN Document Server) avec un enregistrement source INSPIRE. La condition se décide sur les identifiants des enregistrements sources, connus dès la normalisation.

## Phasage

### Phase 1 — Mesure

- [x] Contributions sources OpenAlex du périmètre dont les adresses donnent la France et un autre pays, le 2026-10-19 (`measure_openalex_two_countries.sql`) : 11 624, dans 6 160 publications. OpenAlex réunit souvent dans une contribution source les affiliations de deux auteurs.
  - Autres contributions sources de la contribution : France ou indice de périmètre dans 8 850 cas, autres pays seulement dans 1 650, aucun pays dans 1 001. OpenAlex est seul dans la contribution dans 123 cas.
  - 565 personnes hors RH ont pour seul appui au périmètre des contributions sources de ce type, sans confirmation. Le périmètre compte 15 024 personnes hors RH.
  - Les enregistrements sources de plus de 500 auteurs contiennent 1 780 des 2 774 contributions sources sans confirmation. 244 des 565 personnes signent ainsi dans un enregistrement source de 10 auteurs au plus.
  - Exemple g5296946 : une université chinoise et un laboratoire du périmètre. La contribution source HAL du dépôt in2p3, de 54 auteurs, donne aussi ce laboratoire.
  - Relecture de 65 de ces 565 personnes, le 2026-10-19 (`build_multicountry_review.py`) : 57 fausses personnes du périmètre, 3 doubles affiliations réelles, 5 cas indéterminables. Par plus petit enregistrement source concerné : 18 fausses sur 25 jusqu'à 10 auteurs, 19 sur 20 de 11 à 500 auteurs, 20 sur 20 au-delà. L'adresse française appartient à un autre auteur, ou l'adresse est fausse.
- [x] Personnes hors RH dont aucune contribution source du périmètre n'est confirmée par une autre source de sa contribution, le 2026-10-19 (`measure_unconfirmed_perimeter.sql`) : 5 794 sur 15 024. Une contribution source est confirmée quand une contribution source d'une autre source de la même contribution est aussi du périmètre.

  | Source des indices | Personnes | Dont autre affiliation dans une autre source |
  |---|---|---|
  | OpenAlex | 3 429 | 1 636 |
  | plusieurs sources | 649 | 413 |
  | WoS | 639 | 523 |
  | HAL | 539 | 304 |
  | theses.fr | 348 | 1 |
  | scanR | 182 | 135 |
  | Crossref, DataCite | 8 | 5 |

  - 991 de ces personnes ont une contribution source OpenAlex aux adresses de la France et d'un autre pays.
- [x] Échantillon de 70 de ces personnes relu à la main, hors adresses OpenAlex à plusieurs pays, le 2026-10-19 (`build_perimeter_review.py`).

  | Source des indices | Autres sources | Relues | Fausses | Justes | Indéterminables |
  |---|---|---|---|---|---|
  | OpenAlex | autre affiliation | 12 | 12 | 0 | 0 |
  | OpenAlex | aucune affiliation | 10 | 2 | 2 | 6 |
  | HAL | autre affiliation | 8 | 6 | 2 | 0 |
  | HAL | aucune affiliation | 8 | 0 | 0 | 8 |
  | WoS | autre affiliation | 8 | 4 | 4 | 0 |
  | scanR | toutes | 8 | 7 | 0 | 1 |
  | plusieurs sources | autre affiliation | 6 | 4 | 2 | 0 |
  | plusieurs sources | aucune affiliation | 4 | 0 | 4 | 0 |
  | theses.fr | aucune affiliation | 6 | 0 | 6 | 0 |

  - Une thèse en préparation a pour seul enregistrement source celui de theses.fr. Ses indices sont justes, mais aucune autre source ne peut les confirmer.
  - HAL seul : surtout des publications antérieures à 2017, d'auteurs partis depuis longtemps.
  - WoS se trompe sur la ville d'une adresse de l'université Côte d'Azur, dont le sigle est aussi UCA.
  - Cas limites de périmètre : CHU, laboratoire homonyme d'une autre ville.
- [x] Contributions à plusieurs contributions sources OpenAlex, le 2026-11-07 sur la base locale (`openalex_records.py`). OpenAlex se contredit quand une de ses contributions sources est du périmètre et une autre donne une autre affiliation. L'enregistrement éditeur est l'enregistrement OpenAlex au DOI de la publication. Contributions du périmètre à indice OpenAlex :

  | Contributions sources OpenAlex | OpenAlex seul | Avec d'autres sources |
  |---|---|---|
  | une seule | 13 283 | 125 527 |
  | plusieurs, toutes du périmètre | 63 | 3 828 |
  | plusieurs, les autres sans affiliation | 1 662 | 7 444 |
  | plusieurs, OpenAlex se contredit | 1 905 | 755 |

  - Échantillon INSPIRE de la phase 2 : quand OpenAlex donne seul l'indice, INSPIRE le confirme pour 12 contributions sur 321, toutes par l'enregistrement éditeur. Les enregistrements arXiv et de dépôt donnent 71 indices, tous faux.
  - Quand OpenAlex se contredit, l'enregistrement éditeur a raison dans 96 cas sur 119, les enregistrements arXiv et de dépôt dans 7 cas sur 84.
  - Règles simulées sur l'échantillon INSPIRE, où OpenAlex donne seul 309 indices faux :

  | Règle | Contributions fausses retirées | Contributions justes retirées |
  |---|---|---|
  | OpenAlex écarté quand il se contredit | 75 | 0 |
  | seul l'enregistrement éditeur compte | 71 | 0 |
  | les deux règles | 89 | 0 |
  | OpenAlex jamais seul | 309 | 12 |
- [ ] Enregistrements sources OpenAlex dont toutes les contributions sources ont les mêmes affiliations, confrontés aux autres sources de la publication.
- [ ] Adresses issues d'une erreur de parsing (publication 106296).

### Phase 2 — INSPIRE-HEP

- [x] Couverture d'INSPIRE-HEP sur les publications de physique des hautes énergies du stock, selon le nombre d'auteurs, le 2026-11-06 sur la base locale (`inspire_coverage.py`). Publications du périmètre depuis 2017, classées en physique des hautes énergies par HAL ou OpenAlex, cherchées dans INSPIRE par leur DOI :

  | Auteurs | Avec DOI | Dans INSPIRE |
  |---|---|---|
  | 1 à 10 | 318 | 170 (53 %) |
  | 11 à 50 | 140 | 107 (76 %) |
  | 51 à 500 | 230 | 192 (83 %) |
  | plus de 500 | 2 139 | 1 962 (92 %) |

  - INSPIRE affilie 2 608 articles depuis 2017 à une institution clermontoise. 264 sont sans DOI et 15 sont absents du stock. Les autres sont tous du périmètre.
  - Pour 90 publications du tableau, INSPIRE affilie tous les auteurs hors de Clermont. 64 sont des actes de Nuclear Physics A (Quark Matter 2017 et 2018). INSPIRE garde seulement l'orateur, WoS donne toute la collaboration. Pour 63 de ces actes, l'indice de périmètre vient seulement de WoS.
- [x] Affiliations d'INSPIRE-HEP confrontées à celles des sources, le 2026-11-06 sur la base locale (`inspire_affiliations.py`). L'échantillon compte 567 publications : celles de 500 auteurs au plus présentes dans INSPIRE, et 100 tirées au hasard au-delà. 96 % des contributions du périmètre sont rattachées à un auteur d'INSPIRE, par ORCID ou par nom de famille et initiale du prénom. L'auteur est affilié d'après l'institution rattachée par INSPIRE, à défaut d'après l'affiliation brute.
  - Personnes RH en poste à la date de la publication : INSPIRE affilie à Clermont 496 contributions sur 504. Il affilie 6 autres contributions au CERN ou à Cincinnati, et 2 sont sans affiliation.
  - Indices de périmètre confirmés par INSPIRE, selon la source : HAL 1 904 sur 1 921, WoS 1 781 sur 1 812, scanR 265 sur 280, OpenAlex 1 824 sur 2 164.

  | Source des indices | Autres sources | INSPIRE Clermont | INSPIRE ailleurs |
  |---|---|---|---|
  | plusieurs sources | aucune affiliation | 1 758 | 15 |
  | plusieurs sources | autre affiliation | 217 | 5 |
  | OpenAlex | autre affiliation | 1 | 279 |
  | OpenAlex | aucune affiliation | 11 | 30 |
  | HAL | autre affiliation | 13 | 15 |
  | HAL | aucune affiliation | 28 | 0 |
  | WoS | autre affiliation | 4 | 15 |
  | WoS | aucune affiliation | 1 | 1 |
  | scanR | toutes | 0 | 13 |

  - INSPIRE affilie à Clermont 28 auteurs absents du périmètre, tous dans des publications de plus de 500 auteurs.
  - INSPIRE omet parfois la part clermontoise d'une double affiliation. Pour 21 auteurs de l'échantillon, l'affiliation brute contredit l'institution rattachée. Les rapports techniques du CERN sont sans affiliations.
- [x] Contributions sources OpenAlex écartées des publications présentes dans INSPIRE, simulé le 2026-11-07 sur la base locale (`inspire_without_openalex.py`). Dans ces 2 431 publications, 5 117 contributions du périmètre reposent sur OpenAlex seul. D'après l'échantillon, environ 5 026 sont fausses et 92 justes. Au-delà de 500 auteurs, le taux vient de 100 publications tirées au hasard.
  - 6 de ces publications sont du périmètre par OpenAlex seul. INSPIRE en affilie 5 à Clermont.
  - ORCID des contributions sources OpenAlex (`inspire_openalex_orcids.py`) : 14 941 sur 15 285 sont aussi dans une autre source de la contribution du périmètre, Crossref surtout. Hors périmètre, la part est de 1 813 104 sur 1 857 619. Dans les publications de l'échantillon, INSPIRE donne 609 des 615 autres.
  - Personnes (`inspire_without_openalex_persons.py`) : 880 personnes hors RH sur 16 547 sortent du périmètre, et 341 perdent une partie de leurs contributions. L'échantillon juge 156 des 880 personnes sorties : 154 sont fausses. Aucune personne RH ne sort. 12 personnes RH perdent 14 contributions, et INSPIRE en affilie 13 à Clermont. Les contributions sources de ces 14 contributions sont toutes sans ORCID.
  - Périmètre entier : 4 263 publications sur 75 065 sont du périmètre par OpenAlex seul. Pour 5 200 publications, OpenAlex est la seule source à donner des affiliations.
  - Rattachement direct à la fiche INSPIRE (`direct_link.py`, `inspire_identifier_check.py`) : l'enregistrement OpenAlex contient le DOI de la publication pour 3 525 des 5 117 contributions, un DOI arXiv pour 1 065 autres, un identifiant CDS pour 87. INSPIRE donne les 108 identifiants arXiv vérifiés, et 9 identifiants CDS sur 10. Les 440 dernières viennent d'enregistrements OpenAlex de dépôt (RWTH, GSI, DESY), rattachés à la publication par le titre.
  - Ces publications contiennent 5,4 millions de contributions sources OpenAlex, soit 76 % de celles d'OpenAlex. Elles contiennent 110 339 contributions sources scanR. 95 contributions du périmètre reposent sur scanR seul ; l'échantillon en juge 13, toutes fausses.
- [x] Relecture à la main de 35 indices de périmètre contredits par INSPIRE, donnés par plusieurs sources ou par OpenAlex seul, le 2026-11-06 (`build_inspire_review.py`).
  - OpenAlex seul : INSPIRE a raison dans les 20 cas.
  - Plusieurs sources : INSPIRE a raison dans 7 cas sur 15. Dans 2 de ces cas, l'auteur est passé par Clermont à une autre période. INSPIRE a tort dans 3 cas, 2 pour des personnes RH. 5 cas sont indéterminables.
  - WoS, et parfois OpenAlex, attribue à un auteur les affiliations de ses homonymes de même initiale (Z. Xu, M. Zhang). Une double affiliation Chine et Clermont signale ce cas.
  - Les 121 contributions du périmètre de Zhihao Xu (UCAS, Pékin) sont fausses, le 2026-11-07. 114 reprennent l'adresse d'un homonyme de même initiale. Pour 6, l'éditeur APS décale les affiliations entre les homonymes. 1 vient d'une erreur d'alignement.
  - Sur les 199 915 contributions du périmètre, 185 réunissent des prénoms complets différents de même initiale. Ce sont presque tous des variantes d'orthographe.

### Phase 3 — Moissonnage d'INSPIRE-HEP

- [ ] Migration : source `inspire`, type d'identifiant `cds`.
- [ ] Profil de la source, adaptateur, client de l'API, moissonnage par institution.
- [ ] Normalisation : enregistrement source (DOI, DOI arXiv, identifiant CDS), contributions sources (nom, ORCID, institution).
- [ ] Moissonnage par ORCID, relecture par numéro de fiche (`fetch_stale`).
- [ ] Numéros d'institution INSPIRE dans `api_ids` et noms d'institution INSPIRE dans les formes de nom des structures du périmètre.
- [ ] Documentation de la source.
- [ ] Publications du périmètre absentes du moissonnage d'INSPIRE, mesurées après le premier moissonnage.
- [ ] Enregistrements sources OpenAlex rattachés à un enregistrement source INSPIRE par un identifiant : normalisation sans contributions sources. L'arrivée d'un enregistrement source INSPIRE supprime les contributions sources des enregistrements OpenAlex rattachés. Script ponctuel pour le stock.

### Phase 4 — Règles

- [ ] Règles de confirmation des indices de périmètre, choisies d'après les phases 1 et 2.
- [ ] File d'administration des contributions aux affiliations conflictuelles. Elle dépend du chantier [résolution des personnes](archived/2026-10-24_DATA_resolution-personnes.md).

### Phase 5 — Fin de chantier

- [ ] Mise à jour de la documentation.

## Questions ouvertes

- Une adresse OpenAlex à plusieurs pays, que les autres sources de la contribution ne confirment pas, cesse-t-elle d'être un indice de périmètre ? Sur les 60 cas jugés de la relecture du 2026-10-19, la règle perd 3 doubles affiliations réelles.
- Les affiliations décalées ou fausses qui ne donnent pas plusieurs pays.
- Un acte publié au nom d'une collaboration est-il une publication du périmètre, quand WoS donne toute la liste d'auteurs et INSPIRE seulement l'orateur ?
- Les enregistrements sources scanR rattachés à un enregistrement source INSPIRE sont-ils aussi sans contributions sources ? Et ceux des autres sources (HAL, WoS, Crossref, DataCite) ? Cela réduit le stockage et la durée de l'alignement des auteurs.
- Les enregistrements OpenAlex de dépôt, rattachés à la publication par le titre seul, échappent à la condition sur les identifiants.
