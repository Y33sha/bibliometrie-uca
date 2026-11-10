"""Moissonnage OPS (`pipeline.ingestion.ops.harvest`) et décodage des réponses (`pipeline.ingestion.ops.api`)."""

import httpx2

from pipeline.ingestion.ops.api import OVERLOAD_PAUSE, SearchHit, _classify, _Retry, search_page
from pipeline.ingestion.ops.harvest import kept_hit, search_forms

_FORMS = frozenset(
    {"univ clermont auvergne", "universite clermont auvergne", "the univ of clermont auvergne"}
)


def test_graphies_minimales_seules_cherchees():
    """« the univ of clermont auvergne » contient tous les mots de « univ clermont auvergne »."""
    assert search_forms(_FORMS) == ["univ clermont auvergne", "universite clermont auvergne"]


def _hit(applicants: tuple[str, ...], dates: tuple[str, ...] = ("20210302",)) -> SearchHit:
    return SearchHit(
        family_id="1", publication="FR3120309", priority_dates=dates, applicants=applicants
    )


def test_publication_gardee_par_graphie_exacte_et_annee():
    years = frozenset({2021})
    assert kept_hit(_hit(("UNIV CLERMONT AUVERGNE [FR]",)), _FORMS, years)
    assert not kept_hit(_hit(("CLERMONT AUVERGNE INP [FR]",)), _FORMS, years)
    assert not kept_hit(_hit(("UNIV CLERMONT AUVERGNE [FR]",), ("20150101",)), _FORMS, years)
    assert kept_hit(_hit(("UNIV CLERMONT AUVERGNE [FR]",), ()), _FORMS, years)


def test_page_de_recherche_a_un_seul_resultat():
    """OPS écrit un résultat seul sous forme d'objet, sans liste."""
    body = {
        "ops:world-patent-data": {
            "ops:biblio-search": {
                "@total-result-count": "1",
                "ops:search-result": {
                    "exchange-documents": {
                        "exchange-document": {
                            "@family-id": "57137175",
                            "@country": "FR",
                            "@doc-number": "3055338",
                            "bibliographic-data": {
                                "priority-claims": {
                                    "priority-claim": {"document-id": {"date": {"$": "20160901"}}}
                                },
                                "parties": {
                                    "applicants": {
                                        "applicant": {
                                            "applicant-name": {
                                                "name": {"$": "UNIVERSITE CLERMONT AUVERGNE"}
                                            }
                                        }
                                    }
                                },
                            },
                        }
                    }
                },
            }
        }
    }
    total, hits = search_page(body)
    assert total == 1
    assert hits == [
        SearchHit("57137175", "FR3055338", ("20160901",), ("UNIVERSITE CLERMONT AUVERGNE",))
    ]


def _response(
    status: int, text: str = "", headers: dict[str, str] | None = None
) -> httpx2.Response:
    return httpx2.Response(
        status, text=text, headers=headers, request=httpx2.Request("GET", "https://ops.epo.org/3.2")
    )


def test_surcharge_attendue_puis_retentee():
    outcome = _classify(
        _response(
            403,
            "<code>CLIENT.RobotDetected</code>",
            {"X-Throttling-Control": "overloaded (search=black:0)"},
        ),
        0,
    )
    assert isinstance(outcome, _Retry) and outcome.overload and outcome.pause == OVERLOAD_PAUSE


def test_absence_et_jeton_expire():
    assert _classify(_response(404, "SERVER.EntityNotFound"), 0) is None
    outcome = _classify(_response(401, "invalid_access_token"), 0)
    assert isinstance(outcome, _Retry) and not outcome.overload
