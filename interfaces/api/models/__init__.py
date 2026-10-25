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
    TotalCountResponse,
)
from interfaces.api.models.addresses import (
    AddressPublicationsResponse,
    AddressReviewResponse,
    BatchCountryResponse,
    BatchReviewAction,
    BatchSetCountry,
    ReviewAction,
    SetCountry,
)
from interfaces.api.models.auth import AuthCheckResponse, LoginRequest
from interfaces.api.models.config import ConfigValueUpdate
from interfaces.api.models.contributions import (
    AssignOrphanContribution,
    BatchAssignOrphanContributions,
    CreatePersonName,
    OrphanAssignResponse,
    OrphanBatchAssignResponse,
    SourceContributionRef,
)
from interfaces.api.models.errors import (
    BlockingSerialItem,
    PublisherMergeBlockedResponse,
    RejectedPairItem,
    RejectedPairsResponse,
)
from interfaces.api.models.perimeters import (
    PerimeterCreate,
)
from interfaces.api.models.persons import (
    AddIdentifier,
    AddIdentifierResponse,
    DetachContributions,
    DetachContributionsResponse,
    IdentifierStatusResponse,
    MarkDistinctPersons,
    NameFormStatusResponse,
    SetPersonExclusion,
    UpdateIdentifierStatus,
    UpdateNameFormStatus,
    UpdatePersonName,
)
from interfaces.api.models.serials import SerialTypeChange, SerialTypeChangeImpact
from interfaces.api.models.structures import (
    NameFormCreate,
    StructureCreate,
    StructureTutelleCreateResponse,
    TutelleCreate,
)

__all__ = [
    "AddIdentifier",
    "AddIdentifierResponse",
    "AddressPublicationsResponse",
    "AddressReviewResponse",
    "AssignOrphanContribution",
    "AuthCheckResponse",
    "BatchAssignOrphanContributions",
    "BatchCountryResponse",
    "BatchReviewAction",
    "BatchSetCountry",
    "BatchUpdatedResponse",
    "BlockingSerialItem",
    "ConfigValueUpdate",
    "CreatePersonName",
    "CreatedIdResponse",
    "DeletedResponse",
    "DetachContributions",
    "DetachContributionsResponse",
    "EnumOption",
    "IdentifierStatusResponse",
    "SerialTypeChange",
    "SerialTypeChangeImpact",
    "LoginRequest",
    "MarkDistinctPersons",
    "MergeRequest",
    "MergeResponse",
    "NameFormCreate",
    "NameFormStatusResponse",
    "OkResponse",
    "OrphanAssignResponse",
    "OrphanBatchAssignResponse",
    "PerimeterCreate",
    "PublisherMergeBlockedResponse",
    "SetPersonExclusion",
    "RejectedPairItem",
    "RejectedPairsResponse",
    "TutelleCreate",
    "ReviewAction",
    "SetCountry",
    "SourceContributionRef",
    "StructureCreate",
    "StructureTutelleCreateResponse",
    "TotalCountResponse",
    "UpdateIdentifierStatus",
    "UpdateNameFormStatus",
    "UpdatePersonName",
]
