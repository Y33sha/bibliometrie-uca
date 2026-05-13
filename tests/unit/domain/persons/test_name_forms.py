"""Tests unitaires du VO `PersonNameForm` + helpers `persons` JSONB."""

import dataclasses

import pytest

from domain.errors import ValidationError
from domain.persons.name_forms import (
    PersonNameForm,
    add_person_source,
    all_sources,
    is_ambiguous,
    merge,
    person_ids,
    remove_person,
    remove_person_source,
)


class TestPersonNameFormConstruction:
    def test_valid_string(self) -> None:
        form = PersonNameForm("jean dupont")
        assert form.value == "jean dupont"
        assert str(form) == "jean dupont"

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValidationError):
            PersonNameForm("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ValidationError):
            PersonNameForm("   ")


class TestPersonNameFormSemantics:
    def test_equality_by_value(self) -> None:
        assert PersonNameForm("jean dupont") == PersonNameForm("jean dupont")
        assert PersonNameForm("jean dupont") != PersonNameForm("jean martin")

    def test_hashable(self) -> None:
        forms = {PersonNameForm("jean dupont"), PersonNameForm("jean dupont")}
        assert len(forms) == 1

    def test_frozen(self) -> None:
        form = PersonNameForm("jean dupont")
        with pytest.raises(dataclasses.FrozenInstanceError):
            form.value = "autre"  # type: ignore[misc]


class TestAddPersonSource:
    def test_new_key(self) -> None:
        assert add_person_source({}, 1, "hal") == {"1": ["hal"]}

    def test_existing_key_new_source(self) -> None:
        assert add_person_source({"1": ["hal"]}, 1, "openalex") == {"1": ["hal", "openalex"]}

    def test_existing_source_idempotent(self) -> None:
        assert add_person_source({"1": ["hal"]}, 1, "hal") == {"1": ["hal"]}

    def test_sources_sorted(self) -> None:
        # Ordre alphabétique : openalex avant wos.
        result = add_person_source({"1": ["wos"]}, 1, "openalex")
        assert result == {"1": ["openalex", "wos"]}

    def test_does_not_mutate_input(self) -> None:
        original = {"1": ["hal"]}
        add_person_source(original, 1, "openalex")
        assert original == {"1": ["hal"]}

    def test_preserves_other_keys(self) -> None:
        assert add_person_source({"2": ["wos"]}, 1, "hal") == {"1": ["hal"], "2": ["wos"]}


class TestRemovePersonSource:
    def test_removes_source(self) -> None:
        assert remove_person_source({"1": ["hal", "openalex"]}, 1, "hal") == {"1": ["openalex"]}

    def test_drops_key_when_last_source(self) -> None:
        assert remove_person_source({"1": ["hal"]}, 1, "hal") == {}

    def test_absent_key_noop(self) -> None:
        assert remove_person_source({"1": ["hal"]}, 2, "hal") == {"1": ["hal"]}

    def test_absent_source_noop(self) -> None:
        assert remove_person_source({"1": ["hal"]}, 1, "wos") == {"1": ["hal"]}

    def test_does_not_mutate_input(self) -> None:
        original = {"1": ["hal", "openalex"]}
        remove_person_source(original, 1, "hal")
        assert original == {"1": ["hal", "openalex"]}


class TestRemovePerson:
    def test_removes_key(self) -> None:
        assert remove_person({"1": ["hal"], "2": ["wos"]}, 1) == {"2": ["wos"]}

    def test_absent_noop(self) -> None:
        assert remove_person({"1": ["hal"]}, 2) == {"1": ["hal"]}


class TestMerge:
    def test_disjoint_keys(self) -> None:
        assert merge({"1": ["hal"]}, {"2": ["wos"]}) == {"1": ["hal"], "2": ["wos"]}

    def test_overlapping_keys_union_sources(self) -> None:
        assert merge({"1": ["hal"]}, {"1": ["openalex"]}) == {"1": ["hal", "openalex"]}

    def test_dedup_and_sort(self) -> None:
        result = merge({"1": ["wos", "hal"]}, {"1": ["openalex", "hal"]})
        assert result == {"1": ["hal", "openalex", "wos"]}

    def test_empty_left(self) -> None:
        assert merge({}, {"1": ["hal"]}) == {"1": ["hal"]}

    def test_empty_right(self) -> None:
        assert merge({"1": ["hal"]}, {}) == {"1": ["hal"]}


class TestIsAmbiguous:
    def test_empty_not_ambiguous(self) -> None:
        assert is_ambiguous({}) is False

    def test_single_key_not_ambiguous(self) -> None:
        assert is_ambiguous({"1": ["hal"]}) is False

    def test_two_keys_ambiguous(self) -> None:
        assert is_ambiguous({"1": ["hal"], "2": ["wos"]}) is True


class TestPersonIds:
    def test_returns_ints_sorted(self) -> None:
        assert person_ids({"3": [], "1": [], "2": []}) == [1, 2, 3]

    def test_empty(self) -> None:
        assert person_ids({}) == []


class TestAllSources:
    def test_union_dedup_sorted(self) -> None:
        persons = {"1": ["wos", "hal"], "2": ["openalex", "hal"]}
        assert all_sources(persons) == ["hal", "openalex", "wos"]

    def test_empty(self) -> None:
        assert all_sources({}) == []
