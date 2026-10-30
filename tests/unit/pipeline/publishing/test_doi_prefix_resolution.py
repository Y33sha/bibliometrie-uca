"""Tests des deux passes de résolution des préfixes DOI : `ResolveRaPhase` (agence d'enregistrement, par doi.org) et les étapes Crossref et DataCite de `resolve_publishers` (éditeur, par les API /prefixes).

Faux repositories pour les ports, fonctions locales pour les clients HTTP, sans réseau ni base de données.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from unittest.mock import MagicMock

from pipeline.http.circuit_breaker import SourceUnavailableError
from pipeline.http.lookup import NOT_FOUND, UNAVAILABLE
from pipeline.transformation.publishing.doi_prefixes import PendingPublisherPrefix
from pipeline.transformation.publishing.publishers.resolve_publishers import (
    run_resolve_crossref_publishers,
    run_resolve_datacite_publishers,
)
from pipeline.transformation.publishing.resolve_ra import ResolveRaPhase


@dataclass
class _Row:
    prefix: str
    ra: str
    publisher_id: int | None = None
    publisher_name_raw: str | None = None
    publisher_name_normalized: str | None = None
    crossref_member_id: int | None = None
    client_name_raw: str | None = None
    client_name_normalized: str | None = None
    datacite_client_symbol: str | None = None
    crossref_checked: bool = False
    datacite_checked: bool = False


@dataclass
class FakeDoiPrefixRepo:
    """Faux repository : `candidates` (préfixes des DOI candidats) alimente `resolve_ra` ; `rows` simule la table `doi_prefixes`, indexée par préfixe."""

    candidates: list[str] = field(default_factory=list)
    rows: dict[str, _Row] = field(default_factory=dict)
    ra_breakdown: list[tuple[str, int, int]] = field(default_factory=list)

    def get_prefixes_to_resolve(self) -> list[str]:
        return sorted(p for p in self.candidates if p not in self.rows)

    def insert_ra(self, *, prefix: str, ra: str) -> bool:
        if prefix in self.rows:
            return False
        self.rows[prefix] = _Row(prefix=prefix, ra=ra)
        return True

    def find_doi_with_prefix(self, prefix: str) -> str | None:
        return f"{prefix}/temoin" if prefix in self.rows else None

    def breakdown_by_registration_agency(self) -> list[tuple[str, int, int]]:
        return list(self.ra_breakdown)

    def get_prefixes_pending_publisher(self, agency: str) -> list[PendingPublisherPrefix]:
        def pending(r: _Row) -> bool:
            if agency == "Crossref":
                return not r.crossref_checked and r.ra in ("Crossref", "unknown")
            return not r.datacite_checked and (
                r.ra == "DataCite" or (r.ra == "unknown" and r.crossref_checked)
            )

        return [
            PendingPublisherPrefix(
                r.prefix, r.ra, r.publisher_name_raw, r.publisher_name_normalized
            )
            for r in sorted(self.rows.values(), key=lambda r: r.prefix)
            if r.publisher_id is None and pending(r)
        ]

    def set_prefix_publisher_metadata(
        self,
        *,
        prefix: str,
        ra: str,
        publisher_name_raw: str | None,
        publisher_name_normalized: str | None,
        crossref_member_id: int | None,
        client_name_raw: str | None,
        client_name_normalized: str | None,
        datacite_client_symbol: str | None,
    ) -> None:
        r = self.rows[prefix]
        r.ra = ra
        r.publisher_name_raw = publisher_name_raw
        r.publisher_name_normalized = publisher_name_normalized
        r.crossref_member_id = crossref_member_id
        r.client_name_raw = client_name_raw
        r.client_name_normalized = client_name_normalized
        r.datacite_client_symbol = datacite_client_symbol

    def update_publisher_id(self, prefix: str, publisher_id: int) -> None:
        self.rows[prefix].publisher_id = publisher_id

    def mark_checked(self, prefix: str, agency: str) -> None:
        if agency == "Crossref":
            self.rows[prefix].crossref_checked = True
        else:
            self.rows[prefix].datacite_checked = True


@dataclass
class FakePublisherRepo:
    """Faux repository des éditeurs : `name_to_id` associe une forme de nom à un éditeur, enrichi par chaque création pour dédoublonner au sein du run."""

    name_to_id: dict[str, int] = field(default_factory=dict)
    created: list[dict] = field(default_factory=list)
    _next_id: int = 1000

    def find_publisher_by_name_form(self, form_normalized: str) -> int | None:
        return self.name_to_id.get(form_normalized)

    def create_publisher(self, *, name: str, name_normalized: str, openalex_id):
        new_id = self._next_id
        self._next_id += 1
        self.created.append({"id": new_id, "name": name, "name_normalized": name_normalized})
        return new_id

    def add_publisher_name_form(self, publisher_id: int, form_normalized: str) -> None:
        self.name_to_id[form_normalized] = publisher_id

    def match_or_create_by_name_form(
        self, name_raw: str, name_normalized: str, name_key: str
    ) -> tuple[int, bool]:
        existing = self.find_publisher_by_name_form(name_key)
        if existing is not None:
            return existing, False
        new_id = self.create_publisher(
            name=name_raw, name_normalized=name_normalized, openalex_id=None
        )
        self.add_publisher_name_form(new_id, name_key)
        return new_id, True


@dataclass
class StubResolveRas:
    """Répond pour les préfixes de `answers` ; un préfixe absent de `answers` reste sans réponse, comme ceux d'un lot en échec."""

    answers: dict[str, str | None] = field(default_factory=dict)
    calls: list[list[str]] = field(default_factory=list)

    def __call__(self, prefixes):
        self.calls.append(list(prefixes))
        return [(p, self.answers[p]) for p in prefixes if p in self.answers]


@dataclass
class StubCrossref:
    """Renvoie la réponse déclarée pour un préfixe, `NOT_FOUND` sinon."""

    answers: dict[str, object] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    sample_dois: list[str | None] = field(default_factory=list)

    async def __call__(self, client, prefix: str, sample_doi: str | None = None):  # noqa: ARG002
        self.calls.append(prefix)
        self.sample_dois.append(sample_doi)
        return self.answers.get(prefix, NOT_FOUND)


@dataclass
class StubDataCite:
    """Renvoie la réponse déclarée pour un préfixe, `NOT_FOUND` sinon."""

    answers: dict[str, object] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    async def __call__(self, client, prefix: str):  # noqa: ARG002
        self.calls.append(prefix)
        return self.answers.get(prefix, NOT_FOUND)


_LOG = logging.getLogger("test")


def _run_ra(contexte, repo, ras_fn):
    return ResolveRaPhase(lambda conn: repo, ras_fn).run(contexte())  # noqa: ARG005


def _run_publication(repo, pubrepo, cr=None, dc=None):
    """Exécute l'étape Crossref puis l'étape DataCite, dans l'ordre de la phase ; renvoie les métriques des deux."""
    crossref = run_resolve_crossref_publishers(
        MagicMock(),
        _LOG,
        prefix_store=repo,
        publisher_store=pubrepo,
        fetch_prefix_fn=cr if cr is not None else StubCrossref(),
    )
    datacite = run_resolve_datacite_publishers(
        MagicMock(),
        _LOG,
        prefix_store=repo,
        publisher_store=pubrepo,
        fetch_prefix_fn=dc if dc is not None else StubDataCite(),
    )
    crossref.merge(datacite)
    return crossref


# ResolveRaPhase


def test_resolve_ra_inserts_ra_only(contexte):
    repo = FakeDoiPrefixRepo(candidates=["10.1038"])
    ras = StubResolveRas(answers={"10.1038": "Crossref"})

    metrics = _run_ra(contexte, repo, ras)

    assert ras.calls == [["10.1038"]]  # le préfixe seul, sans DOI
    assert repo.rows["10.1038"].ra == "Crossref"
    assert repo.rows["10.1038"].publisher_id is None  # resolve_ra pose seulement l'agence
    assert metrics.new == 1
    assert metrics.extras.get("resolved") == 1


def test_resolve_ra_ecarte_les_prefixes_malformes(contexte):
    """Les préfixes malformés « doi:10.5194 » et « https: » restent hors de doi_prefixes."""
    repo = FakeDoiPrefixRepo(candidates=["doi:10.5194", "https:", "10.5194"])
    ras = StubResolveRas(answers={"10.5194": "Crossref"})

    _run_ra(contexte, repo, ras)

    assert ras.calls == [["10.5194"]]
    assert set(repo.rows) == {"10.5194"}


def test_resolve_ra_expose_la_repartition_par_ra(contexte):
    repo = FakeDoiPrefixRepo(
        candidates=["10.1038"],
        ra_breakdown=[("Crossref", 80, 12), ("DataCite", 15, 4), ("unknown", 5, 2)],
    )
    ras = StubResolveRas(answers={"10.1038": "Crossref"})

    metrics = _run_ra(contexte, repo, ras)

    assert metrics.details["summary"] == {"new_prefixes": 1, "resolved": 1}
    rows = metrics.details["table"]["rows"]
    # Le préfixe Crossref inséré par le run compte sur la ligne Crossref.
    assert rows[0] == {"key": "Crossref", "dois": 80, "prefixes": 12, "new": 1}
    assert {r["key"] for r in rows} == {"Crossref", "DataCite", "unknown"}
    assert rows[1]["new"] == 0  # aucun préfixe DataCite inséré par ce run


def test_resolve_ra_unknown_when_doi_org_ignores_the_prefix(contexte):
    repo = FakeDoiPrefixRepo(candidates=["10.99999"])
    ras = StubResolveRas(answers={"10.99999": None})

    metrics = _run_ra(contexte, repo, ras)

    assert repo.rows["10.99999"].ra == "unknown"
    assert metrics.extras.get("unresolved") == 1


def test_resolve_ra_prefix_without_answer_stays_to_resolve(contexte):
    """Requête en échec : rien n'est enregistré, le run suivant soumet de nouveau le préfixe."""
    repo = FakeDoiPrefixRepo(candidates=["10.1038"])

    metrics = _run_ra(contexte, repo, StubResolveRas())

    assert repo.rows == {}
    assert metrics.total == 0
    assert repo.get_prefixes_to_resolve() == ["10.1038"]


def test_resolve_ra_doi_org_indisponible_garde_les_prefixes_inseres(open_tx, contexte):
    """doi.org indisponible en cours de résolution : la phase signale la source et sort normalement de sa transaction, qui commit les préfixes déjà insérés."""
    repo = FakeDoiPrefixRepo(candidates=["10.1038", "10.5194"])

    def ras(prefixes):
        yield prefixes[0], "Crossref"
        raise SourceUnavailableError("doi.org/ra")

    metrics = _run_ra(contexte, repo, ras)

    assert set(repo.rows) == {"10.1038"}
    assert open_tx.transactions == 1
    assert [s["code"] for s in metrics.signals] == ["source_unavailable"]


# resolve_publishers


def test_publishers_crossref_match():
    repo = FakeDoiPrefixRepo(rows={"10.1038": _Row("10.1038", "Crossref")})
    pubrepo = FakePublisherRepo(name_to_id={"nature publishing group": 42})
    cr = StubCrossref(answers={"10.1038": ("Nature Publishing Group", 297)})
    dc = StubDataCite()

    metrics = _run_publication(repo, pubrepo, cr, dc)

    assert cr.calls == ["10.1038"] and dc.calls == []  # routé par RA
    row = repo.rows["10.1038"]
    assert row.publisher_id == 42
    assert row.publisher_name_normalized == "nature publishing group"
    assert row.crossref_member_id == 297
    assert row.crossref_checked is True
    assert metrics.extras.get("publisher_matched") == 1


def test_publishers_crossref_create_when_no_match():
    repo = FakeDoiPrefixRepo(rows={"10.99999": _Row("10.99999", "Crossref")})
    pubrepo = FakePublisherRepo()
    cr = StubCrossref(answers={"10.99999": ("Obscure Publisher", 12345)})

    metrics = _run_publication(repo, pubrepo, cr)

    assert len(pubrepo.created) == 1
    assert repo.rows["10.99999"].publisher_id == pubrepo.created[0]["id"]
    assert pubrepo.name_to_id["obscure publisher"] == pubrepo.created[0]["id"]
    assert metrics.extras.get("publisher_created") == 1


def test_publishers_datacite_provider_and_client():
    repo = FakeDoiPrefixRepo(rows={"10.5281": _Row("10.5281", "DataCite")})
    pubrepo = FakePublisherRepo(name_to_id={"cern european organization for nuclear research": 99})
    cr = StubCrossref()
    dc = StubDataCite(
        answers={
            "10.5281": (
                "CERN - European Organization for Nuclear Research",
                "Zenodo",
                "cern.zenodo",
            )
        }
    )

    _run_publication(repo, pubrepo, cr, dc)

    assert cr.calls == [] and dc.calls == ["10.5281"]  # routé par RA
    row = repo.rows["10.5281"]
    assert row.publisher_id == 99
    assert row.publisher_name_normalized == "cern european organization for nuclear research"
    assert row.client_name_raw == "Zenodo"
    assert row.client_name_normalized == "zenodo"
    assert row.datacite_client_symbol == "cern.zenodo"
    assert row.crossref_member_id is None


def test_publishers_unknown_tries_both_and_corrects_ra():
    """Agence inconnue : Crossref est interrogé sans réponse, puis DataCite répond, et l'agence est corrigée."""
    repo = FakeDoiPrefixRepo(rows={"10.14758": _Row("10.14758", "unknown")})
    pubrepo = FakePublisherRepo()
    cr = StubCrossref()
    dc = StubDataCite(answers={"10.14758": ("INRAE", "INRAE Repo", "inist.inra")})

    _run_publication(repo, pubrepo, cr, dc)

    assert cr.calls == ["10.14758"] and dc.calls == ["10.14758"]
    row = repo.rows["10.14758"]
    assert row.ra == "DataCite"  # RA corrigée
    assert row.publisher_id == pubrepo.created[0]["id"]
    assert row.datacite_client_symbol == "inist.inra"


def test_publishers_unknown_both_muet_marks_checked_no_publisher():
    """Agence inconnue, sans réponse de Crossref ni de DataCite : aucun éditeur, et la ligne est marquée vérifiée par les deux agences."""
    repo = FakeDoiPrefixRepo(rows={"10.9012": _Row("10.9012", "unknown")})
    pubrepo = FakePublisherRepo()
    cr = StubCrossref()
    dc = StubDataCite()

    metrics = _run_publication(repo, pubrepo, cr, dc)

    row = repo.rows["10.9012"]
    assert row.publisher_id is None
    assert row.crossref_checked and row.datacite_checked  # marques de vérification
    assert metrics.extras.get("no_publisher") == 2  # inconnu de Crossref, puis de DataCite
    # Le run suivant ignore cette ligne.
    assert repo.get_prefixes_pending_publisher("Crossref") == []
    assert repo.get_prefixes_pending_publisher("DataCite") == []


def test_publishers_skips_already_checked_and_unmanaged_ra():
    repo = FakeDoiPrefixRepo(
        rows={
            "10.9011": _Row("10.9011", "Crossref", crossref_checked=True),
            "10.9013": _Row("10.9013", "mEDRA"),
        }
    )
    pubrepo = FakePublisherRepo()
    cr = StubCrossref(answers={"10.9011": ("X", 1), "10.9013": ("Y", 2)})

    metrics = _run_publication(repo, pubrepo, cr)

    assert cr.calls == []  # ni la ligne déjà vérifiée, ni l'agence non gérée
    assert metrics.total == 0


def test_publishers_name_present_attaches_without_fetch():
    """Une ligne au nom d'éditeur renseigné, sans éditeur rattaché, est rattachée par ce nom sans nouvel appel à /prefixes."""
    repo = FakeDoiPrefixRepo(
        rows={
            "10.1234": _Row(
                "10.1234",
                "Crossref",
                publisher_name_raw="Acme Publishing",
                publisher_name_normalized="acme publishing",
            )
        }
    )
    pubrepo = FakePublisherRepo(name_to_id={"acme publishing": 777})
    cr = StubCrossref()

    _run_publication(repo, pubrepo, cr)

    assert cr.calls == []  # aucun appel : le nom est connu
    assert repo.rows["10.1234"].publisher_id == 777


def test_publishers_dedup_same_name_one_creation():
    repo = FakeDoiPrefixRepo(
        rows={"10.9008": _Row("10.9008", "Crossref"), "10.9009": _Row("10.9009", "Crossref")}
    )
    pubrepo = FakePublisherRepo()
    cr = StubCrossref(answers={"10.9008": ("Wiley", 311), "10.9009": ("Wiley", 311)})

    metrics = _run_publication(repo, pubrepo, cr)

    assert len(pubrepo.created) == 1
    cid = pubrepo.created[0]["id"]
    assert repo.rows["10.9008"].publisher_id == cid
    assert repo.rows["10.9009"].publisher_id == cid
    assert metrics.extras.get("publisher_created") == 1
    assert metrics.extras.get("publisher_matched") == 1


def test_publishers_crossref_sample_doi_read_before_call():
    """Le DOI témoin d'un préfixe Crossref est lu juste avant de l'interroger ; un préfixe DataCite se passe de DOI témoin."""
    repo = FakeDoiPrefixRepo(
        rows={"10.1038": _Row("10.1038", "Crossref"), "10.5281": _Row("10.5281", "DataCite")}
    )
    cr = StubCrossref(answers={"10.1038": ("Nature", 297)})

    _run_publication(repo, FakePublisherRepo(), cr)

    assert cr.sample_dois == ["10.1038/temoin"]


def test_publishers_crossref_unavailable_leaves_prefix_pending():
    """API indisponible : ni métadonnées ni marque de vérification, le préfixe est repris au run suivant."""
    repo = FakeDoiPrefixRepo(rows={"10.1038": _Row("10.1038", "Crossref")})
    cr = StubCrossref(answers={"10.1038": UNAVAILABLE})

    metrics = _run_publication(repo, FakePublisherRepo(), cr)

    row = repo.rows["10.1038"]
    assert row.crossref_checked is False
    assert row.publisher_id is None
    assert metrics.errors == 1
    assert [r.prefix for r in repo.get_prefixes_pending_publisher("Crossref")] == ["10.1038"]


def test_publishers_unknown_crossref_unavailable_does_not_ask_datacite():
    """RA inconnue et Crossref indisponible : l'absence chez Crossref n'est pas établie, DataCite n'est pas interrogé et la RA reste inconnue."""
    repo = FakeDoiPrefixRepo(rows={"10.14758": _Row("10.14758", "unknown")})
    cr = StubCrossref(answers={"10.14758": UNAVAILABLE})
    dc = StubDataCite(answers={"10.14758": ("INRAE", "INRAE Repo", "inist.inra")})

    _run_publication(repo, FakePublisherRepo(), cr, dc)

    assert dc.calls == []
    row = repo.rows["10.14758"]
    assert row.ra == "unknown"
    assert row.crossref_checked is False


def test_publishers_datacite_unavailable_leaves_prefix_pending():
    repo = FakeDoiPrefixRepo(rows={"10.5281": _Row("10.5281", "DataCite")})
    dc = StubDataCite(answers={"10.5281": UNAVAILABLE})

    _run_publication(repo, FakePublisherRepo(), dc=dc)

    assert repo.rows["10.5281"].datacite_checked is False
