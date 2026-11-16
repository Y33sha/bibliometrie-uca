# Chantier — Vérification des affiliations des sources

## Contexte

Une contribution source appartient au périmètre par ses indices (`perimeter_evidence`) : adresse, structure HAL, ROR, fiche RH, établissement de thèse. Chaque source donne ses indices pour sa propre contribution source. Une source attribue parfois à un auteur l'affiliation d'un autre auteur, ou une affiliation fausse. Une personne hors RH entrée dans le périmètre par une telle affiliation est une fausse personne du périmètre.

Le chantier [alignement des auteurs](archived/2026-10-24_DATA_alignement-auteurs.md) a relu les liens au périmètre établis par la seule contribution source scanR. Le lien était faux dans 12 cas sur 25 pour une structure, dans 10 cas sur 15 pour une adresse.

## Décisions

- Une contribution dont certaines contributions sources donnent un indice de périmètre et d'autres une affiliation hors périmètre est un cas conflictuel. Une file d'administration la présente pour décision.
- INSPIRE-HEP est moissonné seulement par institution (numéro d'institution INSPIRE, à défaut chaîne d'affiliation). La phase `fetch_missing` l'ignore, tant que le premier moissonnage ne révèle pas de manques importants.
- L'ORCID d'INSPIRE-HEP sert au rattachement des personnes et à l'indice de fiche RH (`ORCID_MATCH_SOURCES`).
- Le moissonnage demande seulement les champs utiles : ni nombre de citations, ni références.
- L'adresse d'une contribution source INSPIRE est le nom de l'institution rattachée par INSPIRE, avec son ROR quand INSPIRE le donne. L'affiliation brute est écartée : elle reproduit les décalages d'affiliations de l'éditeur. 0,2 % des auteurs ont une affiliation brute sans institution.
- L'identifiant CDS est un type d'identifiant d'enregistrement source et une clé de confirmation de la réconciliation. La normalisation d'OpenAlex le reprend des URL de localisation.
- Une adresse concaténée, à au moins deux groupes d'initiales d'auteurs, est sans indice de périmètre.
- Quand une contribution a une contribution source dans l'enregistrement OpenAlex éditeur, au DOI de la publication, les indices d'adresse et de ROR de ses autres enregistrements OpenAlex sont écartés. La décision porte sur la contribution, à la recomposition de ses attributs. Les indices des contributions sources restent ceux de leur enregistrement.
- Une affiliation contraire dans un autre enregistrement OpenAlex de la contribution laisse ses indices en place.
- Un enregistrement source OpenAlex est sans contributions sources quand il partage un DOI, un DOI arXiv, un hal-id ou un identifiant CDS (CERN Document Server) avec un enregistrement source INSPIRE. La condition se décide sur les identifiants des enregistrements sources, connus dès la normalisation, de rôle autre que `related`, quel que soit leur statut.

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
- [x] Enregistrements sources OpenAlex dont toutes les contributions sources ont les mêmes adresses, le 2026-11-16 (`openalex_same_addresses.sql`). Sur 63 502 enregistrements OpenAlex de plusieurs auteurs, 3 670 donnent à tous la même adresse et 1 216 le même ensemble de plusieurs adresses. Ils ont presque tous 10 auteurs au plus. Une autre source de la contribution confirme leurs indices de périmètre dans 89 % et 92 % des cas, contre 90 % pour les autres enregistrements OpenAlex. Ce motif est sans lien avec les erreurs d'affiliation.
- [x] Adresses concaténées par une erreur de parsing, le 2026-11-16 (`concatenated_addresses.sql`). Dans la publication 106296, l'adresse OpenAlex est la note d'affiliations entière, avec les initiales des auteurs (« (D.S., P.C.) »). Elle met 28 auteurs dans le périmètre. Une adresse à au moins deux groupes d'initiales est concaténée : 178 adresses, dans Crossref, OpenAlex et scanR.
  - Dans 420 contributions de 30 publications, une contribution source est du périmètre par une adresse concaténée seule. Une autre source, sans adresse concaténée, en confirme 142.
  - 278 contributions restent sans confirmation. Elles sont le seul appui au périmètre de 234 personnes hors RH. Les 30 publications sont du périmètre par d'autres indices.

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

- [x] Migration : source `inspire`, type d'identifiant `cds`. 8763385ca
- [x] Profil de la source, adaptateur, client de l'API, moissonnage par institution. 8763385ca
- [x] Normalisation : enregistrement source (DOI, DOI arXiv, identifiant CDS), contributions sources (nom, ORCID, institution). 8763385ca
- [x] Relecture par numéro de fiche (`fetch_stale`). 8763385ca
- [x] Numéros d'institution INSPIRE dans `api_ids` et noms d'institution INSPIRE dans les formes de nom des structures du périmètre.

  | Structure | Numéros d'institution INSPIRE (nom INSPIRE) |
  |---|---|
  | UCA | 1598522 (U. Clermont Auvergne), 1306651 (université Blaise Pascal) |
  | IP | 1691275 (Institut Pascal, Clermont-Ferrand) |
  | LIMOS | 2676525 (LIMOS, Clermont-Ferrand) |
  | LPCA | 902740 (Clermont-Ferrand U.), 2093671 (LPC, Clermont-Ferrand) |
  | LMV | 1595893 (LMV, Clermont-Ferrand) |
  | OPGC | 1692893 (OPGC, Clermont-Ferrand) |
  | ISIMA | 912510 (ISIMA, Aubiere) |

  Formes de nom de l'UCA : `clermont ferrand u` (mot entier), `u clermont auvergne`, `u blaise pascal` (mot entier), `iut montlucon`. Les formes de nom des autres structures reconnaissent leur nom INSPIRE.
- [x] Documentation de la source. 8763385ca
- [x] Publications du périmètre absentes du moissonnage d'INSPIRE, le 2026-11-07 sur la base locale (`inspire_missing.py`). Le moissonnage par institution ramène 2 717 fiches, la recherche par ORCID 216 autres.
  - Recherche par ORCID (`inspire_orcid_rh.py`) : 211 des 217 contributions sources de personnes RH datent d'avant l'arrivée de la personne, dont 203 pour une seule personne. Les 6 autres sont sans institution.
  - ORCID d'INSPIRE (`inspire_orcid_agreement.py`) : 1 531 051 contributions sources ont le même ORCID qu'une source de confiance de leur contribution, 8 135 un autre. Les écarts relus viennent de l'alignement d'homonymes de même initiale, ou de l'ORCID d'un homonyme dans HAL, sur une liste d'auteurs de collaboration.
  - Publications HEP du périmètre trouvées dans INSPIRE par DOI : 164 sur 2 436 sont sans enregistrement INSPIRE. 75 ont une fiche moissonnée, rattachée à une autre publication : 69 sont des errata, et la fiche est rattachée à l'article. Pour 63 des 89 autres, le périmètre vient de WoS seul : des actes de Quark Matter 2018, avec la collaboration ALICE entière dans WoS et l'orateur seul dans INSPIRE.
  - 135 publications du périmètre ont une localisation OpenAlex vers CDS (130) ou INSPIRE (5), sans enregistrement INSPIRE. 50 sont du périmètre par OpenAlex seul.
  - 23 fiches ont plusieurs DOI propres. 4 forment avec la prépublication arXiv une publication à côté de celle de l'article. La correction des natures de DOI (c4a452c20) en laisse 9, dont 4 errata sans nature dans INSPIRE.
  - 5 fiches de la fenêtre ont pour seule institution clermontoise l'université Blaise Pascal (1306651).
- [x] Recherche par ORCID retirée, ORCID d'INSPIRE de confiance. Script ponctuel de suppression des 216 fiches ramenées par ORCID (`delete_inspire_person_harvest`). 66a807c47
  - Effet mesuré le 2026-11-07 (`inspire_hr_gain_contributions.py`) : 131 contributions sources INSPIRE entrent dans le périmètre par la fiche RH, toutes dans des publications du périmètre. Pour 86, la contribution est déjà du périmètre par l'ORCID d'une autre source. Les 45 autres contributions entrent dans le périmètre : elles sont de deux personnes RH, affiliées par INSPIRE au CERN et à l'université de Cincinnati.
- [x] Enregistrements sources OpenAlex du même document qu'un enregistrement source INSPIRE : normalisation sans contributions sources, empreinte du bloc auteurs vide. La tâche `normalize.withhold_openalex_authors` supprime les contributions sources des enregistrements OpenAlex normalisés avant l'arrivée de l'enregistrement INSPIRE, stock compris. 0d1e64f82
  - Mesure à blanc le 2026-11-07 sur la base locale (`withhold_dry_run.py`) : 3 674 enregistrements OpenAlex, 4 911 163 contributions sources, 2 692 publications, 217 épinglages.

### Phase 4 — Règles

- [x] Audit des désaccords entre sources, le 2026-11-16 (`audit_population.py`, `audit_sample.py`), après un instantané du périmètre (`perimeter_20261116_1148.json.gz`). 7 511 contributions reposent sur une seule source du périmètre, contredite par une autre source, sans indice RH. 120 cas jugés, 15 par source du périmètre (OpenAlex, HAL, WoS, scanR) et par situation de la personne : 34 justes, 6 douteux, 80 faux. Aucune fonction de décision générale.
  - La personne a une autre contribution confirmée par plusieurs sources : 30 justes sur 60. La confirmation est elle-même faussée par les grandes collaborations (centaines de contributions « confirmées » de fausses personnes) et par des homonymes fusionnés.
  - La personne est sans autre contribution confirmée : 52 faux sur 60, soit 3 132 contributions et 2 504 personnes. Les justes sont des personnes peu publiantes (doctorant CIFRE, ancien du LASMEA).
  - Causes des faux : tutelle multisite atteinte par la hiérarchie HAL (LBBE et TIMC par VetAgro Sup), formes de nom en collision, adresses concaténées hors de la règle, LPC donné par WoS dans les grandes collaborations.
  - Faux désaccords : l'autre source donne la même structure, par une adresse ou une structure HAL non rattachée (CHU, QuaPA, TSCF).
- [x] Formes de nom en collision : `gred` (iGReD), `u1095` (GDEC), `umr 547` (PIAF), `umr 6024` (LAPSCO), `umr 1019` (UNH).
- [ ] Faux désaccords : identifiants HAL à rattacher (QuaPA : 1 450 contributions, TSCF : 194) et formes de nom manquantes (CHU, LASMEA, SEESIB, PFEM, abréviations du WoS).
- [ ] Détection élargie des adresses concaténées : noms entre parenthèses, initiales espacées, listes d'affiliations d'un essai multicentrique.
- [x] Adresse concaténée sans indice de périmètre : colonne `addresses.is_concatenated`, tâche `affiliations.detect_concatenated_addresses`. 0dd031ae5. Simulation le 2026-11-16 (`concat_rule.py`) : 365 contributions de 29 publications sortent du périmètre, et aucune publication.
  - 301 personnes hors RH sortent du périmètre. L'adresse place les initiales de 189 d'entre elles dans une affiliation hors périmètre. Les initiales des 112 autres sont absentes de l'adresse, tronquée par la source à 500 ou 1 000 caractères.
  - Une personne RH perd une contribution : celle d'une homonyme toulousaine.
  - 5 contributions justes sortent. 3 sont sans personne. Les 2 autres personnes restent du périmètre par d'autres contributions.
- [x] Règle « OpenAlex écarté quand il se contredit », non retenue. Simulation le 2026-11-16 (`contradiction.sql`) : 645 contributions où une contribution source OpenAlex est du périmètre et une autre donne une affiliation hors périmètre.
  - 151 contributions sortent, avec 85 personnes hors RH et 10 publications. Un nom seul non rattaché (« Territoires ») compte comme affiliation contraire.
  - Sans les adresses en nom seul : 116 contributions, 67 personnes hors RH, 4 publications. Environ 5 pertes justes sûres et 8 douteuses sur une soixantaine de cas lus : mobilité et doubles affiliations (LMBP puis Caen, LMV et IPGP).
- [x] Seul l'enregistrement OpenAlex éditeur donne des indices d'affiliation OpenAlex. a75d604b4, 6d0d1ddb9. Simulation le 2026-11-16 (`publisher.sql`) : 3 234 contributions ont un indice d'un enregistrement OpenAlex non éditeur. 88 sortent du périmètre, avec 50 personnes hors RH, aucune personne RH et 5 publications.
  - Les sorties relues sont presque toutes fausses : affiliation d'un coauteur dans une prépublication, liste d'affiliations réunies, enregistrement de dépôt LHCb ou ATLAS, membre de jury de thèse. 3 ou 4 cas sont douteux.
  - Dans 3 des 5 publications sortantes, un coauteur clermontois existe probablement, sans indice dans aucune source : un article d'ATLAS sans affiliations dans l'enregistrement éditeur, un article de l'ICCF déposé dans HAL, un jeu de données Zenodo.
  - Le rattachement des personnes lit le périmètre de la contribution (`contributions.in_perimeter`), seul calcul de ce périmètre. Une publication dont le DOI change met ses contributions en file de recomposition.
  - La variante qui écarte toujours les enregistrements OpenAlex non éditeurs ferait sortir 2 877 contributions dans 1 107 publications, surtout des prépublications sans enregistrement éditeur.
- [x] Recomposition des contributions du stock concernées par la règle de l'enregistrement OpenAlex éditeur (`requeue_openalex_preprint_evidence`), le 2026-11-16. Le run applique aussi la règle des adresses concaténées : 687 contributions sources sortent du périmètre, 350 personnes sont supprimées, 71 publications sont purgées, dont les 5 annoncées par la simulation. Les résidus des deux règles sont nuls après le run.
- [ ] File d'administration des contributions aux affiliations conflictuelles. Elle dépend du chantier [résolution des personnes](archived/2026-10-24_DATA_resolution-personnes.md).
- [ ] Tutelles et unités multisites : VetAgro Sup, EHIC, LIMOS (site de Saint-Étienne), IHRIM, GEOLAB, EPIA, LMV (site de Saint-Étienne). Une tutelle multisite fait-elle entrer tous ses laboratoires, et une unité multisite tous ses sites ?

### Phase 5 — Fin de chantier

- [ ] Mise à jour de la documentation.

## Questions ouvertes

- Une adresse OpenAlex à plusieurs pays, que les autres sources de la contribution ne confirment pas, cesse-t-elle d'être un indice de périmètre ? Sur les 60 cas jugés de la relecture du 2026-10-19, la règle perd 3 doubles affiliations réelles.
- Les affiliations décalées ou fausses qui ne donnent pas plusieurs pays.
- Un acte publié au nom d'une collaboration est-il une publication du périmètre, quand WoS donne toute la liste d'auteurs et INSPIRE seulement l'orateur ?
- Les enregistrements sources scanR rattachés à un enregistrement source INSPIRE sont-ils aussi sans contributions sources ? Et ceux des autres sources (HAL, WoS, Crossref, DataCite) ? Cela réduit le stockage et la durée de l'alignement des auteurs.
- Les enregistrements OpenAlex de dépôt, rattachés à la publication par le titre seul, échappent à la condition sur les identifiants.
- La phase `affiliations` pose les indices des contributions sources. Les décisions entre enregistrements sources portent sur la contribution, à la fin d'`author_grouping`. Faut-il scinder `affiliations` en une phase par niveau ?
