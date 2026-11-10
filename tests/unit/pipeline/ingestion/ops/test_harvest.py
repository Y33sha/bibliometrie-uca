"""Moissonnage OPS (`pipeline.ingestion.ops.harvest`) et décodage des réponses (`pipeline.ingestion.ops.api`)."""

import httpx2

from pipeline.ingestion.ops.api import (
    OVERLOAD_PAUSE,
    OpsAuth,
    SearchHit,
    application_family_path,
    family_path,
    overload_refusal,
    publication_forms,
    search_page,
)
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


def test_refus_pour_surcharge_reconnu():
    overloaded = _response(
        403,
        "<code>CLIENT.RobotDetected</code>",
        {"X-Throttling-Control": "overloaded (search=black:0)"},
    )
    assert overload_refusal(overloaded) == (OVERLOAD_PAUSE, "service saturé (feu noir)")
    assert overload_refusal(_response(403, "<code>CLIENT.InvalidQuery</code>")) is None
    assert overload_refusal(_response(404, "SERVER.EntityNotFound")) is None


def test_jeton_demande_joint_puis_renouvele_sur_refus_401():
    auth = OpsAuth()
    request = httpx2.Request("GET", "https://ops.epo.org/3.2/rest-services/x")
    flow = auth.auth_flow(request)
    assert next(flow).url.path == "/3.2/auth/accesstoken"
    token = httpx2.Response(200, json={"access_token": "t1", "expires_in": "1199"})
    assert flow.send(token).headers["Authorization"] == "Bearer t1"
    assert flow.send(_response(401)).url.path == "/3.2/auth/accesstoken"
    renewed = httpx2.Response(200, json={"access_token": "t2", "expires_in": "1199"})
    assert flow.send(renewed).headers["Authorization"] == "Bearer t2"


def test_famille_d_une_publication_au_format_docdb():
    assert family_path("ES2880413") == "/rest-services/family/publication/docdb/ES.2880413/biblio"
    assert publication_forms("US2024211607") == ["US20240211607", "US2024211607"]
    assert publication_forms("US11198814") == ["US11198814"]


def test_famille_d_une_demande_au_format_docdb():
    assert application_family_path("EP20166388") == (
        "/rest-services/family/application/docdb/EP.20166388/biblio"
    )
    assert application_family_path("WO2017071490") is None
