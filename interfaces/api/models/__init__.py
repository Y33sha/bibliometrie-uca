"""Modèles Pydantic des routers : corps des requêtes entrantes, et réponses que le router compose lui-même.

Le découpage des modules suit celui des routers (`interfaces/api/routers/*`). Ce `__init__` re-expose les classes au niveau du package, qui est le point d'importation : `from interfaces.api.models import X`.

Les projections de lecture rendues par un port vivent auprès de lui, dans `application/ports/api/` : leur contrat appartient à la couche application, et un port ne peut pas importer `interfaces/`.
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
    MarkDistinctPersons,
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
    PublicationMergeResponse,
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
    "MarkDistinctPersons",
    "MarkDistinctPublications",
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
    "PubYearCount",
    "PublicationMergeResponse",
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
