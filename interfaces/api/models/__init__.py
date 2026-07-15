"""Modèles Pydantic des routers, regroupés par domaine fonctionnel.

Le découpage suit les routers (`interfaces/api/routers/*`). Pour éviter de
casser les imports historiques (`from interfaces.api.models import X`),
ce `__init__` re-expose toutes les classes au niveau du package.
"""

from interfaces.api.models._common import (
    BatchUpdatedResponse,
    CreatedIdResponse,
    DashboardOa,
    DeletedResponse,
    EnumOption,
    FacetValueCount,
    MergeRequest,
    MergeResponse,
    OkResponse,
    PubYearCount,
    RemovedResponse,
    StatusResponse,
    StructureRef,
    TotalCountResponse,
    ValueConfirmedOut,
    YesNoCount,
)
from interfaces.api.models.admin.addresses import (
    AddressPublicationsResponse,
    AddressReviewResponse,
    BatchCountryResponse,
    BatchReviewAction,
    BatchSetCountry,
    ReviewAction,
    SetCountry,
)
from interfaces.api.models.admin.authorships import (
    AssignOrphanAuthorship,
    AuthorshipExcludeResponse,
    BatchAssignOrphanAuthorships,
    CreatePersonName,
    OrphanAssignResponse,
    OrphanBatchAssignResponse,
    SourceAuthorshipRef,
)
from interfaces.api.models.admin.feedback import FeedbackStructuresResponse
from interfaces.api.models.admin.perimeters import (
    AddPerimeterStructure,
    PerimeterCreate,
)
from interfaces.api.models.admin.persons import (
    AddIdentifier,
    AddIdentifierResponse,
    DetachAuthorships,
    DetachAuthorshipsResponse,
    IdentifierReassignResponse,
    IdentifierStatusResponse,
    MarkPersonsDistinct,
    MergePersons,
    NameFormStatusResponse,
    ReassignIdentifier,
    RejectPerson,
    UpdateIdentifierStatus,
    UpdateNameFormStatus,
    UpdatePersonName,
)
from interfaces.api.models.admin.pipeline_config import ConfigValueUpdate
from interfaces.api.models.admin.pipeline_logs import (
    PipelinePhaseLog,
    PipelineStatus,
)
from interfaces.api.models.admin.publication_duplicates import (
    MarkDistinctPublications,
    MergePublications,
    PubMergeResponse,
)
from interfaces.api.models.admin.structures import (
    NameFormCreate,
    NameFormUpdate,
    RelationCreate,
    StructureCreate,
    StructureRelationCreateResponse,
    StructureUpdate,
)
from interfaces.api.models.auth import AuthCheckResponse, LoginRequest
from interfaces.api.models.journals import JournalTypeChangeImpact

__all__ = [
    "AddIdentifier",
    "AddIdentifierResponse",
    "AddPerimeterStructure",
    "AddressPublicationsResponse",
    "AddressReviewResponse",
    "AssignOrphanAuthorship",
    "AuthCheckResponse",
    "AuthorshipExcludeResponse",
    "BatchAssignOrphanAuthorships",
    "BatchCountryResponse",
    "BatchReviewAction",
    "BatchSetCountry",
    "BatchUpdatedResponse",
    "ConfigValueUpdate",
    "CreatePersonName",
    "CreatedIdResponse",
    "DashboardOa",
    "DeletedResponse",
    "DetachAuthorships",
    "DetachAuthorshipsResponse",
    "EnumOption",
    "FacetValueCount",
    "FeedbackStructuresResponse",
    "IdentifierReassignResponse",
    "IdentifierStatusResponse",
    "JournalTypeChangeImpact",
    "LoginRequest",
    "MarkDistinctPublications",
    "MarkPersonsDistinct",
    "MergePersons",
    "MergePublications",
    "MergeRequest",
    "MergeResponse",
    "NameFormCreate",
    "NameFormStatusResponse",
    "NameFormUpdate",
    "OkResponse",
    "OrphanAssignResponse",
    "OrphanBatchAssignResponse",
    "PerimeterCreate",
    "PipelinePhaseLog",
    "PipelineStatus",
    "PubMergeResponse",
    "PubYearCount",
    "ReassignIdentifier",
    "RejectPerson",
    "RelationCreate",
    "RemovedResponse",
    "ReviewAction",
    "SetCountry",
    "SourceAuthorshipRef",
    "StatusResponse",
    "StructureCreate",
    "StructureRef",
    "StructureRelationCreateResponse",
    "StructureUpdate",
    "TotalCountResponse",
    "UpdateIdentifierStatus",
    "UpdateNameFormStatus",
    "UpdatePersonName",
    "ValueConfirmedOut",
    "YesNoCount",
]
