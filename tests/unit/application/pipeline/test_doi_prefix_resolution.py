"""Tests des deux passes de résolution des préfixes DOI :
`run_resolve_ra` (RA seule, via doi.org) et `run_resolve_publishers` (publisher via
les API /prefixes). Fakes pour les ports, callables locales pour les clients HTTP —
pas de réseau, pas de DB.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from application.pipeline.publishers_journals.resolve_publishers import run_resolve_publishers
from application.pipeline.resolve_ra.run import run_resolve_ra
from application.ports.repositories.doi_prefix_repository import PendingPublisherPrefix


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
    checked: bool = False


@dataclass
class FakeDoiPrefixRepo:
    """Repo de test : `unresolved` alimente `resolve_ra` ; `rows` modélise la table
    `doi_prefixes` (clé = prefix) pour le volet publisher."""

    unresolved: list[tuple[str, list[str]]] = field(default_factory=list)
    rows: dict[str, _Row] = field(default_factory=dict)
    ra_breakdown: list[tuple[str, int, int]] = field(default_factory=list)

    def get_unresolved_prefixes_with_samples(
        self, *, n_samples_per_prefix: int
    ) -> list[tuple[str, list[str]]]:
        return [(p, dois[:n_samples_per_prefix]) for p, dois in self.unresolved]

    def insert_ra(self, *, prefix: str, ra: str) -> bool:
        if prefix in self.rows:
            return False
        self.rows[prefix] = _Row(prefix=prefix, ra=ra)
        return True

    def breakdown_by_registration_agency(self) -> list[tuple[str, int, int]]:
        return list(self.ra_breakdown)

    def get_prefixes_pending_publisher(self) -> list[PendingPublisherPrefix]:
        return [
            PendingPublisherPrefix(
                r.prefix, r.ra, r.publisher_name_raw, r.publisher_name_normalized
            )
            for r in sorted(self.rows.values(), key=lambda r: r.prefix)
            if r.publisher_id is None
            and not r.checked
            and r.ra in ("Crossref", "DataCite", "unknown")
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

    def mark_publisher_checked(self, prefix: str) -> None:
        self.rows[prefix].checked = True


@dataclass
class FakePublisherRepo:
    """`find_publisher_by_name_form` lit `name_to_id` ; `create_publisher` incrémente un
    id ; `add_publisher_name_form` enrichit `name_to_id` (dédoublonnage intra-run)."""

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


@dataclass
class StubResolveRa:
    answers: dict[str, str | None] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def __call__(self, doi: str) -> str | None:
        self.calls.append(doi)
        return self.answers.get(doi)


@dataclass
class StubCrossref:
    answers: dict[str, tuple[str, int | None] | None] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def __call__(self, prefix: str) -> tuple[str, int | None] | None:
        self.calls.append(prefix)
        return self.answers.get(prefix)


@dataclass
class StubDataCite:
    answers: dict[str, tuple[str, str, str] | None] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def __call__(self, prefix: str) -> tuple[str, str, str] | None:
        self.calls.append(prefix)
        return self.answers.get(prefix)


_LOG = logging.getLogger("test")


def _run_ra(repo, ra_fn, **kw):
    return run_resolve_ra(_LOG, repo=repo, resolve_ra_fn=ra_fn, **kw)


def _run_pub(repo, pubrepo, cr=None, dc=None, **kw):
    return run_resolve_publishers(
        _LOG,
        repo=repo,
        publisher_repo=pubrepo,
        fetch_crossref_prefix_fn=cr if cr is not None else StubCrossref(),
        fetch_datacite_prefix_fn=dc if dc is not None else StubDataCite(),
        **kw,
    )


# ── run_resolve_ra ─────────────────────────────────────────────────


def test_resolve_ra_inserts_ra_only():
    repo = FakeDoiPrefixRepo(unresolved=[("10.1038", ["10.1038/a"])])
    ra = StubResolveRa(answers={"10.1038/a": "Crossref"})

    metrics = _run_ra(repo, ra)

    assert repo.rows["10.1038"].ra == "Crossref"
    assert repo.rows["10.1038"].publisher_id is None  # aucun publisher en resolve_ra
    assert metrics.new == 1
    assert metrics.extras.get("resolved") == 1


def test_resolve_ra_expose_la_repartition_par_ra():
    repo = FakeDoiPrefixRepo(
        unresolved=[("10.1038", ["10.1038/a"])],
        ra_breakdown=[("Crossref", 80, 12), ("DataCite", 15, 4), ("unknown", 5, 2)],
    )
    ra = StubResolveRa(answers={"10.1038/a": "Crossref"})

    metrics = _run_ra(repo, ra)

    assert metrics.details["summary"] == {"new_prefixes": 1, "resolved": 1}
    rows = metrics.details["table"]["rows"]
    # Le run a inséré le préfixe Crossref → +1 sur la ligne Crossref.
    assert rows[0] == {"key": "Crossref", "dois": 80, "prefixes": 12, "new": 1}
    assert {r["key"] for r in rows} == {"Crossref", "DataCite", "unknown"}
    assert rows[1]["new"] == 0  # DataCite non touché ce run


def test_resolve_ra_unknown_when_all_samples_fail():
    repo = FakeDoiPrefixRepo(unresolved=[("10.xxx", ["10.xxx/a", "10.xxx/b"])])
    ra = StubResolveRa(answers={"10.xxx/a": None, "10.xxx/b": None})

    metrics = _run_ra(repo, ra)

    assert ra.calls == ["10.xxx/a", "10.xxx/b"]
    assert repo.rows["10.xxx"].ra == "unknown"
    assert metrics.extras.get("unresolved") == 1


def test_resolve_ra_first_sample_fails_second_succeeds():
    repo = FakeDoiPrefixRepo(unresolved=[("10.1038", ["10.1038/bad", "10.1038/good"])])
    ra = StubResolveRa(answers={"10.1038/bad": None, "10.1038/good": "DataCite"})

    _run_ra(repo, ra)

    assert ra.calls == ["10.1038/bad", "10.1038/good"]
    assert repo.rows["10.1038"].ra == "DataCite"


def test_resolve_ra_limit():
    repo = FakeDoiPrefixRepo(unresolved=[("10.a", ["10.a/x"]), ("10.b", ["10.b/x"])])
    ra = StubResolveRa(answers={"10.a/x": "Crossref", "10.b/x": "Crossref"})

    metrics = _run_ra(repo, ra, limit=1)
    assert len(repo.rows) == 1 and metrics.total == 1


# ── run_resolve_publishers ─────────────────────────────────────────


def test_publishers_crossref_match():
    repo = FakeDoiPrefixRepo(rows={"10.1038": _Row("10.1038", "Crossref")})
    pubrepo = FakePublisherRepo(name_to_id={"nature publishing group": 42})
    cr = StubCrossref(answers={"10.1038": ("Nature Publishing Group", 297)})
    dc = StubDataCite()

    metrics = _run_pub(repo, pubrepo, cr, dc)

    assert cr.calls == ["10.1038"] and dc.calls == []  # routé par RA
    row = repo.rows["10.1038"]
    assert row.publisher_id == 42
    assert row.publisher_name_normalized == "nature publishing group"
    assert row.crossref_member_id == 297
    assert row.checked is True
    assert metrics.extras.get("publisher_matched") == 1


def test_publishers_crossref_create_when_no_match():
    repo = FakeDoiPrefixRepo(rows={"10.99999": _Row("10.99999", "Crossref")})
    pubrepo = FakePublisherRepo()
    cr = StubCrossref(answers={"10.99999": ("Obscure Publisher", 12345)})

    metrics = _run_pub(repo, pubrepo, cr)

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

    _run_pub(repo, pubrepo, cr, dc)

    assert cr.calls == [] and dc.calls == ["10.5281"]  # routé par RA
    row = repo.rows["10.5281"]
    assert row.publisher_id == 99
    assert row.publisher_name_normalized == "cern european organization for nuclear research"
    assert row.client_name_raw == "Zenodo"
    assert row.client_name_normalized == "zenodo"
    assert row.datacite_client_symbol == "cern.zenodo"
    assert row.crossref_member_id is None


def test_publishers_unknown_tries_both_and_corrects_ra():
    """ra=unknown → tente crossref (muet) puis datacite (répond) → RA corrigée."""
    repo = FakeDoiPrefixRepo(rows={"10.14758": _Row("10.14758", "unknown")})
    pubrepo = FakePublisherRepo()
    cr = StubCrossref(answers={"10.14758": None})
    dc = StubDataCite(answers={"10.14758": ("INRAE", "INRAE Repo", "inist.inra")})

    _run_pub(repo, pubrepo, cr, dc)

    assert cr.calls == ["10.14758"] and dc.calls == ["10.14758"]
    row = repo.rows["10.14758"]
    assert row.ra == "DataCite"  # RA corrigée
    assert row.publisher_id == pubrepo.created[0]["id"]
    assert row.datacite_client_symbol == "inist.inra"


def test_publishers_unknown_both_muet_marks_checked_no_publisher():
    """ra=unknown, /prefixes muet partout → pas de publisher, mais row marquée vérifiée
    (garde : ne sera plus reprise au run suivant)."""
    repo = FakeDoiPrefixRepo(rows={"10.dead": _Row("10.dead", "unknown")})
    pubrepo = FakePublisherRepo()
    cr = StubCrossref(answers={"10.dead": None})
    dc = StubDataCite(answers={"10.dead": None})

    metrics = _run_pub(repo, pubrepo, cr, dc)

    row = repo.rows["10.dead"]
    assert row.publisher_id is None
    assert row.checked is True  # garde anti-réinterrogation
    assert metrics.extras.get("no_publisher") == 1
    # Un second run ne reprend plus cette row.
    assert repo.get_prefixes_pending_publisher() == []


def test_publishers_skips_already_checked_and_unmanaged_ra():
    repo = FakeDoiPrefixRepo(
        rows={
            "10.checked": _Row("10.checked", "Crossref", checked=True),
            "10.medra": _Row("10.medra", "mEDRA"),
        }
    )
    pubrepo = FakePublisherRepo()
    cr = StubCrossref(answers={"10.checked": ("X", 1), "10.medra": ("Y", 2)})

    metrics = _run_pub(repo, pubrepo, cr)

    assert cr.calls == []  # ni la row déjà vérifiée, ni la RA non gérée
    assert metrics.total == 0


def test_publishers_name_present_attaches_without_fetch():
    """Row héritée avec nom déjà renseigné mais publisher NULL → match/attache sans
    re-fetch /prefixes."""
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

    _run_pub(repo, pubrepo, cr)

    assert cr.calls == []  # pas de fetch, nom déjà là
    assert repo.rows["10.1234"].publisher_id == 777


def test_publishers_dedup_same_name_one_creation():
    repo = FakeDoiPrefixRepo(
        rows={"10.aaaa": _Row("10.aaaa", "Crossref"), "10.bbbb": _Row("10.bbbb", "Crossref")}
    )
    pubrepo = FakePublisherRepo()
    cr = StubCrossref(answers={"10.aaaa": ("Wiley", 311), "10.bbbb": ("Wiley", 311)})

    metrics = _run_pub(repo, pubrepo, cr)

    assert len(pubrepo.created) == 1
    cid = pubrepo.created[0]["id"]
    assert repo.rows["10.aaaa"].publisher_id == cid
    assert repo.rows["10.bbbb"].publisher_id == cid
    assert metrics.extras.get("publisher_created") == 1
    assert metrics.extras.get("publisher_matched") == 1
