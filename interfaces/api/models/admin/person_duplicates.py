"""Modèles Pydantic pour la déduplication de personnes (admin)."""

from pydantic import BaseModel


class PersonDedupIdentifier(BaseModel):
    id: int
    id_type: str
    id_value: str
    source: str
    status: str


class PersonDedupPublication(BaseModel):
    id: int
    title: str
    pub_year: int | None
    doi: str | None
    doc_type: str
    sources: list[str]


class PersonDedupLab(BaseModel):
    id: int
    acronym: str | None
    name: str


class PersonDedupDetail(BaseModel):
    """Profil d'une personne pour la page de déduplication."""

    id: int
    last_name: str
    first_name: str
    last_name_normalized: str
    first_name_normalized: str
    has_rh: bool
    role_title: str | None
    department_name: str | None
    identifiers: list[PersonDedupIdentifier]
    publications: list[PersonDedupPublication]
    pub_count: int
    labs: list[PersonDedupLab]


class PersonDuplicatePair(BaseModel):
    person_a: PersonDedupDetail
    person_b: PersonDedupDetail


class PersonConflictPub(BaseModel):
    id: int
    title: str
    pub_year: int | None
    doc_type: str
    position: int


class PersonConflictPair(BaseModel):
    person_a: PersonDedupDetail
    person_b: PersonDedupDetail
    conflict_pubs: list[PersonConflictPub]


class PersonDuplicatePairResponse(BaseModel):
    pair: PersonDuplicatePair | None


class PersonConflictPairResponse(BaseModel):
    pair: PersonConflictPair | None
