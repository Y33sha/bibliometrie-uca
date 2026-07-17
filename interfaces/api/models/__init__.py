"""Modèles Pydantic des routers : corps des requêtes entrantes, réponses que le router compose lui-même, et corps d'erreur structurés (`errors.py`) que les handlers d'`app.py` produisent et que les routes déclarent.

Le découpage des modules suit celui des routers (`interfaces/api/routers/*`). Ce `__init__` re-expose les classes au niveau du package, qui est le point d'importation : `from interfaces.api.models import X`.

Les projections de lecture rendues par un port vivent auprès de lui, dans `application/ports/api/` : leur contrat appartient à la couche application, et un port ne peut pas importer `interfaces/`.
"""

from interfaces.api.models._common import (
    BatchUpdatedResponse,
    CreatedIdResponse,
    DeletedResponse,
    EnumOption,
    MergeRequest,
    MergeResponse,
    OkResponse,
    RemovedResponse,
    StatusResponse,
    TotalCountResponse,
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
from interfaces.api.models.errors import (
    BlockingJournalItem,
    PublisherMergeBlockedResponse,
    RejectedPairItem,
    RejectedPairsResponse,
)
from interfaces.api.models.journals import JournalTypeChange, JournalTypeChangeImpact

__all__ = [
    "AddIdentifier",
    "AddIdentifierResponse",
    "AddPerimeterStructure",
    "AddressPublicationsResponse",
    "AddressReviewResponse",
    "AssignOrphanAuthorship",
    "AuthCheckResponse",
    "BatchAssignOrphanAuthorships",
    "BatchCountryResponse",
    "BatchReviewAction",
    "BatchSetCountry",
    "BatchUpdatedResponse",
    "BlockingJournalItem",
    "ConfigValueUpdate",
    "CreatePersonName",
    "CreatedIdResponse",
    "DeletedResponse",
    "DetachAuthorships",
    "DetachAuthorshipsResponse",
    "EnumOption",
    "FeedbackStructuresResponse",
    "IdentifierReassignResponse",
    "IdentifierStatusResponse",
    "JournalTypeChange",
    "JournalTypeChangeImpact",
    "LoginRequest",
    "MarkDistinctPersons",
    "MarkDistinctPublications",
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
    "PublicationMergeResponse",
    "PublisherMergeBlockedResponse",
    "ReassignIdentifier",
    "RejectPerson",
    "RejectedPairItem",
    "RejectedPairsResponse",
    "RelationCreate",
    "RemovedResponse",
    "ReviewAction",
    "SetCountry",
    "SourceAuthorshipRef",
    "StatusResponse",
    "StructureCreate",
    "StructureRelationCreateResponse",
    "StructureUpdate",
    "TotalCountResponse",
    "UpdateIdentifierStatus",
    "UpdateNameFormStatus",
    "UpdatePersonName",
]
