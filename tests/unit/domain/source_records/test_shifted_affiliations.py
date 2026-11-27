"""Affiliations décalées d'OpenAlex (`domain.source_records.shifted_affiliations`). Les cas reprennent des œuvres OpenAlex réelles, affiliations abrégées."""

from domain.source_records.shifted_affiliations import unshifted_affiliations


def test_auteur_insere_collectif_en_tete():
    """W2982537460 : le collectif reçoit l'affiliation du suivant, chaque auteur la sienne et celle du suivant."""
    affiliations = [
        ["CHU Grenoble"],
        ["CHU Grenoble", "Agence de la Biomédecine"],
        ["Agence de la Biomédecine", "Institut Paoli Calmette"],
        ["Institut Paoli Calmette", "CHU de Bordeaux"],
        ["CHU de Bordeaux", "CHRU de Lille"],
        ["CHRU de Lille", "CHU de Montpellier"],
        ["CHU de Montpellier", "CHU Saint-Louis"],
    ]
    collective = [True] + [False] * 6

    assert unshifted_affiliations(affiliations, collective) == [
        [],
        ["CHU Grenoble"],
        ["Agence de la Biomédecine"],
        ["Institut Paoli Calmette"],
        ["CHU de Bordeaux"],
        ["CHRU de Lille"],
        ["CHU de Montpellier"],
    ]


def test_auteur_insere_plus_loin_et_ecritures_differentes():
    """W4407421416 : les auteurs avant le collectif gardent leurs affiliations ; une affiliation recopiée sans virgules reste la même."""
    affiliations = [
        ["University of Exeter"],
        ["University of Exeter"],
        ["MPI EVA, Leipzig, Germany", "University of Leipzig, Leipzig, Germany"],
        [
            "MPI EVA Leipzig Germany",
            "University of Leipzig  Leipzig Germany",
            "Adam Mickiewicz University, Poznan",
        ],
        ["Adam Mickiewicz University Poznan", "UC Davis, Davis, USA"],
        ["UC Davis Davis USA", "Université de Strasbourg"],
        ["Université de Strasbourg", "University at Buffalo"],
    ]
    collective = [False, False, True, False, False, False, False]

    assert unshifted_affiliations(affiliations, collective) == [
        ["University of Exeter"],
        ["University of Exeter"],
        [],
        ["MPI EVA Leipzig Germany", "University of Leipzig  Leipzig Germany"],
        ["Adam Mickiewicz University Poznan"],
        ["UC Davis Davis USA"],
        ["Université de Strasbourg"],
    ]


def test_auteur_manquant_sans_collectif():
    """W4310125553 : un auteur manque avant le cinquième ; chaque auteur reçoit la sienne et celle du précédent. Le cinquième auteur perd celle de l'auteur manquant."""
    affiliations = [
        ["1 Bordeaux"],
        ["2 Paris"],
        ["3 Toulouse"],
        ["4 Toulouse IUCT"],
        ["6 Lyon Sud", "5 Paoli-Calmettes"],
    ]
    affiliations += [
        [f"{n} Hôpital {n}", f"{n - 1} Hôpital {n - 1}" if n > 7 else "6 Lyon Sud"]
        for n in range(7, 13)
    ]
    collective = [False] * len(affiliations)

    kept = unshifted_affiliations(affiliations, collective)

    assert kept is not None
    assert kept[:4] == affiliations[:4]
    assert kept[4] == ["6 Lyon Sud"]
    assert kept[5:] == [[f"{n} Hôpital {n}"] for n in range(7, 13)]


def test_decalage_avant_le_collectif():
    """W3197636785 : le décalage précède le collectif, sans affiliation, placé en fin de liste."""
    affiliations = [
        ["X"],
        ["A", "B"],
        ["B", "C"],
        ["C", "D"],
        ["D", "E"],
        ["E", "F"],
        ["G"],
        [],
    ]
    collective = [False] * 7 + [True]

    assert unshifted_affiliations(affiliations, collective) == [
        ["X"],
        ["A"],
        ["B"],
        ["C"],
        ["D"],
        ["E"],
        ["G"],
        [],
    ]


def test_equipe_aux_affiliations_partagees():
    """W3137107832 : des auteurs voisins partagent la même affiliation des deux côtés, sans chaînon."""
    affiliations = [["Institut Pascal", "Nagoya University"]] + [
        ["IMaSS Nagoya", "Nagoya University"]
    ] * 5

    assert unshifted_affiliations(affiliations, [False] * 6) is None


def test_auteur_sans_affiliation_au_milieu():
    """Après un auteur sans affiliation, l'auteur suivant garde ses affiliations moins celles du suivant."""
    affiliations = [
        ["A"],
        ["A", "B"],
        ["B", "C"],
        ["C", "D"],
        [],
        ["E", "F"],
        ["F", "G"],
        ["G", "H"],
    ]
    collective = [True] + [False] * 7

    assert unshifted_affiliations(affiliations, collective) == [
        [],
        ["A"],
        ["B"],
        ["C"],
        [],
        ["E"],
        ["F"],
        ["G"],
    ]
