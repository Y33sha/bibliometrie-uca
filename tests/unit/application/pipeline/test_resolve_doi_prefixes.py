"""Tests de l'orchestrateur `run_resolve_doi_prefixes`.

Utilisent des fakes pour les ports et des callables locales pour les clients HTTP — pas de réseau, pas de DB.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from application.pipeline.publishers_journals.resolve_doi_prefixes import (
    run_resolve_doi_prefixes,
)
from application.ports.repositories.doi_prefix_repository import UnmatchedPrefix


@dataclass
class FakeDoiPrefixRepo:
    """Repo de test : on lui fournit les préfixes à résoudre, on collecte les inserts."""

    unresolved: list[tuple[str, list[str]]] = field(default_factory=list)
    unmatched_existing: list[UnmatchedPrefix] = field(default_factory=list)
    inserted: list[dict] = field(default_factory=list)
    updates: list[tuple[str, int]] = field(default_factory=list)

    def get_unresolved_prefixes_with_samples(
        self, *, n_samples_per_prefix: int
    ) -> list[tuple[str, list[str]]]:
        return [(p, dois[:n_samples_per_prefix]) for p, dois in self.unresolved]

    def insert_doi_prefix(
        self,
        *,
        prefix: str,
        ra: str,
        publisher_id: int | None,
        publisher_name_raw: str | None,
        publisher_name_normalized: str | None,
        crossref_member_id: int | None,
        client_name_raw: str | None,
        client_name_normalized: str | None,
        datacite_client_symbol: str | None,
    ) -> bool:
        self.inserted.append(
            {
                "prefix": prefix,
                "ra": ra,
                "publisher_id": publisher_id,
                "publisher_name_raw": publisher_name_raw,
                "publisher_name_normalized": publisher_name_normalized,
                "crossref_member_id": crossref_member_id,
                "client_name_raw": client_name_raw,
                "client_name_normalized": client_name_normalized,
                "datacite_client_symbol": datacite_client_symbol,
            }
        )
        return True

    def get_unmatched_prefixes(self) -> list[UnmatchedPrefix]:
        return list(self.unmatched_existing)

    def update_publisher_id(self, prefix: str, publisher_id: int) -> None:
        self.updates.append((prefix, publisher_id))


@dataclass
class FakePublisherRepo:
    """Repo publisher minimal pour les passes 1 et 2.

    `find_publisher_by_name_form` lit `name_to_id` ; `create_publisher`
    incrémente un compteur d'id ; `add_publisher_name_form` enrichit
    `name_to_id` pour que les appels suivants dans la même run retombent
    sur le publisher fraîchement créé (dédoublonnage naturel).
    """

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

    # Méthodes non utilisées par la phase mais présentes au Protocol.
    def find_by_id(self, publisher_id):  # pragma: no cover
        raise NotImplementedError

    def find_publisher_by_openalex_id(self, openalex_id):  # pragma: no cover
        raise NotImplementedError

    def set_publisher_openalex_id_if_missing(self, publisher_id, openalex_id):  # pragma: no cover
        raise NotImplementedError

    def publisher_exists(self, publisher_id):  # pragma: no cover
        raise NotImplementedError

    def update_publisher_fields(self, publisher_id, fields):  # pragma: no cover
        raise NotImplementedError

    def merge_publisher_into(self, target_id, source_id):  # pragma: no cover
        raise NotImplementedError


@dataclass
class StubResolveRa:
    """Stub `resolve_ra_fn` : map DOI → RA (ou None)."""

    answers: dict[str, str | None] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def __call__(self, doi: str) -> str | None:
        self.calls.append(doi)
        return self.answers.get(doi)


@dataclass
class StubCrossref:
    """Stub `fetch_crossref_prefix_fn` : map prefix → (name, member_id) ou None."""

    answers: dict[str, tuple[str, int | None] | None] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def __call__(self, prefix: str) -> tuple[str, int | None] | None:
        self.calls.append(prefix)
        return self.answers.get(prefix)


@dataclass
class StubDataCite:
    """Stub `fetch_datacite_prefix_fn` : map prefix → (provider_name, client_name, client_symbol) ou None."""

    answers: dict[str, tuple[str, str, str] | None] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def __call__(self, prefix: str) -> tuple[str, str, str] | None:
        self.calls.append(prefix)
        return self.answers.get(prefix)


def _run(repo, publisher_repo, ra_fn, crossref_fn, datacite_fn=None, **kw):
    return run_resolve_doi_prefixes(
        logging.getLogger("test"),
        repo=repo,
        publisher_repo=publisher_repo,
        resolve_ra_fn=ra_fn,
        fetch_crossref_prefix_fn=crossref_fn,
        fetch_datacite_prefix_fn=datacite_fn if datacite_fn is not None else StubDataCite(),
        **kw,
    )


# ── Cas heureux ────────────────────────────────────────────────────


def test_crossref_prefix_matched_publisher():
    repo = FakeDoiPrefixRepo(unresolved=[("10.1038", ["10.1038/a"])])
    pubrepo = FakePublisherRepo(name_to_id={"nature publishing group": 42})
    ra = StubResolveRa(answers={"10.1038/a": "Crossref"})
    cr = StubCrossref(answers={"10.1038": ("Nature Publishing Group", 297)})

    metrics = _run(repo, pubrepo, ra, cr)

    assert len(repo.inserted) == 1
    row = repo.inserted[0]
    assert row["prefix"] == "10.1038"
    assert row["ra"] == "Crossref"
    assert row["publisher_id"] == 42
    assert row["publisher_name_raw"] == "Nature Publishing Group"
    assert row["publisher_name_normalized"] == "nature publishing group"
    assert row["crossref_member_id"] == 297
    assert metrics.new == 1
    assert metrics.extras.get("publisher_matched") == 1


def test_crossref_prefix_no_match_creates_publisher():
    """Aucun publisher existant → on crée le publisher depuis le nom Crossref
    plutôt que de laisser publisher_id NULL."""
    repo = FakeDoiPrefixRepo(unresolved=[("10.99999", ["10.99999/x"])])
    pubrepo = FakePublisherRepo(name_to_id={})
    ra = StubResolveRa(answers={"10.99999/x": "Crossref"})
    cr = StubCrossref(answers={"10.99999": ("Obscure Publisher", 12345)})

    metrics = _run(repo, pubrepo, ra, cr)

    assert len(pubrepo.created) == 1
    new_pub = pubrepo.created[0]
    assert new_pub["name"] == "Obscure Publisher"
    assert new_pub["name_normalized"] == "obscure publisher"
    # La forme normalisée est ajoutée → futurs matches retombent dessus.
    assert pubrepo.name_to_id["obscure publisher"] == new_pub["id"]

    row = repo.inserted[0]
    assert row["publisher_id"] == new_pub["id"]
    assert row["publisher_name_raw"] == "Obscure Publisher"
    assert row["publisher_name_normalized"] == "obscure publisher"
    assert row["crossref_member_id"] == 12345
    assert metrics.extras.get("publisher_created") == 1
    assert metrics.extras.get("publisher_matched", 0) == 0


def test_two_prefixes_same_name_dedup_via_name_form_cache():
    """Deux préfixes différents avec le même nom Crossref → un seul publisher créé,
    le 2e retombe dessus via le name_form fraîchement ajouté."""
    repo = FakeDoiPrefixRepo(unresolved=[("10.aaaa", ["10.aaaa/x"]), ("10.bbbb", ["10.bbbb/x"])])
    pubrepo = FakePublisherRepo()
    ra = StubResolveRa(answers={"10.aaaa/x": "Crossref", "10.bbbb/x": "Crossref"})
    cr = StubCrossref(
        answers={
            "10.aaaa": ("Wiley & Sons", 311),
            "10.bbbb": ("Wiley & Sons", 311),
        }
    )

    metrics = _run(repo, pubrepo, ra, cr)

    assert len(pubrepo.created) == 1, "publisher unique attendu"
    created_id = pubrepo.created[0]["id"]
    assert repo.inserted[0]["publisher_id"] == created_id
    assert repo.inserted[1]["publisher_id"] == created_id
    assert metrics.extras.get("publisher_created") == 1
    assert metrics.extras.get("publisher_matched") == 1


# ── Passe 2 : rattrapage des rows existantes ───────────────────────


def test_pass_2_creates_publisher_for_existing_unmatched():
    """Une row doi_prefixes connue de Crossref sans publisher_id → crée le publisher et UPDATE la row."""
    repo = FakeDoiPrefixRepo(
        unmatched_existing=[
            UnmatchedPrefix(
                prefix="10.5433",
                publisher_name_raw="Universidade Estadual de Londrina",
                publisher_name_normalized="universidade estadual de londrina",
            )
        ]
    )
    pubrepo = FakePublisherRepo()
    ra = StubResolveRa()
    cr = StubCrossref()

    metrics = _run(repo, pubrepo, ra, cr)

    assert len(pubrepo.created) == 1
    new_id = pubrepo.created[0]["id"]
    assert repo.updates == [("10.5433", new_id)]
    assert metrics.extras.get("retried") == 1
    assert metrics.extras.get("publisher_created") == 1


def test_pass_2_matches_existing_publisher_no_creation():
    """Si un publisher est apparu en base depuis le run précédent, la passe 2 rattache la row existante sans créer."""
    repo = FakeDoiPrefixRepo(
        unmatched_existing=[
            UnmatchedPrefix(
                prefix="10.1234",
                publisher_name_raw="Acme Publishing",
                publisher_name_normalized="acme publishing",
            )
        ]
    )
    pubrepo = FakePublisherRepo(name_to_id={"acme publishing": 777})
    ra = StubResolveRa()
    cr = StubCrossref()

    metrics = _run(repo, pubrepo, ra, cr)

    assert pubrepo.created == []
    assert repo.updates == [("10.1234", 777)]
    assert metrics.extras.get("publisher_matched") == 1
    assert metrics.extras.get("publisher_created", 0) == 0


def test_datacite_prefix_provider_matched_and_client_stored():
    """RA=DataCite : appel api.datacite.org, provider matché en publisher existant, client stocké à part."""
    repo = FakeDoiPrefixRepo(unresolved=[("10.5281", ["10.5281/zenodo.1"])])
    pubrepo = FakePublisherRepo(name_to_id={"cern european organization for nuclear research": 99})
    ra = StubResolveRa(answers={"10.5281/zenodo.1": "DataCite"})
    cr = StubCrossref()  # ne sera pas appelé
    dc = StubDataCite(
        answers={
            "10.5281": (
                "CERN - European Organization for Nuclear Research",
                "Zenodo",
                "cern.zenodo",
            )
        }
    )

    metrics = _run(repo, pubrepo, ra, cr, dc)

    assert cr.calls == []  # branche Crossref non touchée
    assert dc.calls == ["10.5281"]
    row = repo.inserted[0]
    assert row["ra"] == "DataCite"
    assert row["publisher_id"] == 99
    assert row["publisher_name_raw"] == "CERN - European Organization for Nuclear Research"
    assert row["publisher_name_normalized"] == "cern european organization for nuclear research"
    assert row["crossref_member_id"] is None
    assert row["client_name_raw"] == "Zenodo"
    assert row["client_name_normalized"] == "zenodo"
    assert row["datacite_client_symbol"] == "cern.zenodo"
    assert metrics.extras.get("publisher_matched") == 1


def test_datacite_prefix_creates_provider_when_unknown():
    """RA=DataCite : si le provider n'existe pas en base, on le crée comme publisher."""
    repo = FakeDoiPrefixRepo(unresolved=[("10.14758", ["10.14758/x"])])
    pubrepo = FakePublisherRepo()
    ra = StubResolveRa(answers={"10.14758/x": "DataCite"})
    cr = StubCrossref()
    dc = StubDataCite(
        answers={
            "10.14758": (
                "Institut national de recherche pour l'agriculture",
                "INRAE",
                "inist.inra",
            )
        }
    )

    metrics = _run(repo, pubrepo, ra, cr, dc)

    assert len(pubrepo.created) == 1
    new_pub = pubrepo.created[0]
    assert new_pub["name"] == "Institut national de recherche pour l'agriculture"
    row = repo.inserted[0]
    assert row["publisher_id"] == new_pub["id"]
    assert row["client_name_raw"] == "INRAE"
    assert row["datacite_client_symbol"] == "inist.inra"
    assert metrics.extras.get("publisher_created") == 1


def test_datacite_api_failure_inserts_without_provider_or_client():
    """Si api.datacite.org échoue, on insère quand même avec ra='DataCite' et le reste NULL."""
    repo = FakeDoiPrefixRepo(unresolved=[("10.5281", ["10.5281/x"])])
    pubrepo = FakePublisherRepo()
    ra = StubResolveRa(answers={"10.5281/x": "DataCite"})
    cr = StubCrossref()
    dc = StubDataCite(answers={"10.5281": None})

    _run(repo, pubrepo, ra, cr, dc)

    row = repo.inserted[0]
    assert row["ra"] == "DataCite"
    assert row["publisher_id"] is None
    assert row["publisher_name_raw"] is None
    assert row["client_name_raw"] is None
    assert row["datacite_client_symbol"] is None


def test_unknown_ra_inserted_without_publisher():
    """`unknown` est une RA valide retournée par doi.org — on insère sans appeler ni Crossref ni DataCite."""
    repo = FakeDoiPrefixRepo(unresolved=[("10.31399", ["10.31399/x"])])
    pubrepo = FakePublisherRepo()
    ra = StubResolveRa(answers={"10.31399/x": "unknown"})
    cr = StubCrossref()
    dc = StubDataCite()

    _run(repo, pubrepo, ra, cr, dc)

    row = repo.inserted[0]
    assert row["ra"] == "unknown"
    assert cr.calls == []
    assert dc.calls == []


# ── Retry multi-DOI ────────────────────────────────────────────────


def test_first_sample_fails_second_succeeds():
    repo = FakeDoiPrefixRepo(unresolved=[("10.1038", ["10.1038/bad", "10.1038/good"])])
    pubrepo = FakePublisherRepo()
    ra = StubResolveRa(answers={"10.1038/bad": None, "10.1038/good": "Crossref"})
    cr = StubCrossref(answers={"10.1038": ("Nature", None)})

    metrics = _run(repo, pubrepo, ra, cr)

    assert ra.calls == ["10.1038/bad", "10.1038/good"]
    assert len(repo.inserted) == 1
    assert repo.inserted[0]["ra"] == "Crossref"
    assert metrics.extras.get("resolved") == 1


def test_all_samples_fail_and_fallback_fails_stored_as_unknown():
    """Si tous les samples échouent ET que les endpoints prefix Crossref/DataCite
    ne répondent pas, on stocke le préfixe avec ra='unknown' (sentinelle +
    fetched_at) pour ne plus le retenter — au lieu de l'omettre."""
    repo = FakeDoiPrefixRepo(unresolved=[("10.xxx", ["10.xxx/a", "10.xxx/b", "10.xxx/c"])])
    pubrepo = FakePublisherRepo()
    ra = StubResolveRa(answers={"10.xxx/a": None, "10.xxx/b": None, "10.xxx/c": None})
    cr = StubCrossref()  # pas de réponse
    dc = StubDataCite()  # pas de réponse

    metrics = _run(repo, pubrepo, ra, cr, dc)

    assert ra.calls == ["10.xxx/a", "10.xxx/b", "10.xxx/c"]
    # Fallback tenté sur les deux endpoints prefix.
    assert cr.calls == ["10.xxx"]
    assert dc.calls == ["10.xxx"]
    # Stocké en sentinelle → ne sera plus retenté.
    assert len(repo.inserted) == 1
    assert repo.inserted[0]["ra"] == "unknown"
    assert repo.inserted[0]["publisher_id"] is None
    assert metrics.new == 1
    assert metrics.extras.get("unresolved") == 1
    assert metrics.total == 1


def test_unresolved_ra_falls_back_to_crossref_prefix():
    """RA non résolue (samples KO) mais l'endpoint prefix Crossref répond → on
    adopte ra='Crossref' et on résout l'éditeur au lieu d'abandonner."""
    repo = FakeDoiPrefixRepo(unresolved=[("10.1038", ["10.1038/bad"])])
    pubrepo = FakePublisherRepo()
    ra = StubResolveRa(answers={"10.1038/bad": None})
    cr = StubCrossref(answers={"10.1038": ("Nature Publishing Group", 297)})
    dc = StubDataCite()

    metrics = _run(repo, pubrepo, ra, cr, dc)

    assert cr.calls == ["10.1038"]
    assert dc.calls == []  # Crossref a répondu → DataCite non tenté
    row = repo.inserted[0]
    assert row["ra"] == "Crossref"
    assert row["crossref_member_id"] == 297
    assert metrics.extras.get("resolved") == 1


# ── Crossref API failure ───────────────────────────────────────────


def test_crossref_api_failure_publisher_id_null_but_insert_still_happens():
    """Si api.crossref.org échoue, on insère quand même avec publisher_id NULL."""
    repo = FakeDoiPrefixRepo(unresolved=[("10.1038", ["10.1038/x"])])
    pubrepo = FakePublisherRepo()
    ra = StubResolveRa(answers={"10.1038/x": "Crossref"})
    cr = StubCrossref(answers={"10.1038": None})

    _run(repo, pubrepo, ra, cr)

    row = repo.inserted[0]
    assert row["ra"] == "Crossref"
    assert row["publisher_id"] is None
    assert row["publisher_name_raw"] is None
    assert row["crossref_member_id"] is None


# ── Modes d'exécution ──────────────────────────────────────────────


def test_dry_run_no_calls_no_inserts():
    repo = FakeDoiPrefixRepo(unresolved=[("10.1038", ["10.1038/x"])])
    pubrepo = FakePublisherRepo()
    ra = StubResolveRa(answers={"10.1038/x": "Crossref"})
    cr = StubCrossref()

    metrics = _run(repo, pubrepo, ra, cr, dry_run=True)

    assert ra.calls == []
    assert cr.calls == []
    assert repo.inserted == []
    assert metrics.total == 1


def test_limit_caps_prefixes_processed():
    repo = FakeDoiPrefixRepo(
        unresolved=[
            ("10.a", ["10.a/x"]),
            ("10.b", ["10.b/x"]),
            ("10.c", ["10.c/x"]),
        ]
    )
    pubrepo = FakePublisherRepo()
    ra = StubResolveRa(answers={"10.a/x": "Crossref", "10.b/x": "Crossref", "10.c/x": "Crossref"})
    cr = StubCrossref()

    metrics = _run(repo, pubrepo, ra, cr, limit=2)

    assert metrics.total == 2
    assert len(repo.inserted) == 2
