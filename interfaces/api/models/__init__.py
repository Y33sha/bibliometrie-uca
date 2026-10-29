"""Modèles Pydantic des routers : corps des requêtes entrantes, réponses que le router compose lui-même, et corps d'erreur structurés (`errors.py`) que les handlers d'`app.py` produisent et que les routes déclarent.

Le découpage des modules suit celui des routers (`interfaces/api/routers/*`). Le package réexpose les classes : `from interfaces.api.models import X`.

Les modèles de réponse des lectures sont déclarés avec leur requête, dans `infrastructure/read_models/<lecture>/models.py`.
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
from interfaces.api.models.publications import (
    DocTypeFamilyOut,
    DocTypeOut,
    PublicationMergeRequest,
    PublicationMergeResult,
)
from interfaces.api.models.serials import SerialTypeChange, SerialTypeChangeImpact
from interfaces.api.models.structures import (
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
    "DocTypeFamilyOut",
    "DocTypeOut",
    "EnumOption",
    "IdentifierStatusResponse",
    "SerialTypeChange",
    "SerialTypeChangeImpact",
    "LoginRequest",
    "MarkDistinctPersons",
    "MergeRequest",
    "MergeResponse",
    "NameFormStatusResponse",
    "OkResponse",
    "OrphanAssignResponse",
    "OrphanBatchAssignResponse",
    "PerimeterCreate",
    "PublicationMergeRequest",
    "PublicationMergeResult",
    "PublisherMergeBlockedResponse",
    "SetPersonExclusion",
    "RejectedPairItem",
    "RejectedPairsResponse",
    "TutelleCreate",
    "ReviewAction",
    "SetCountry",
    "SourceContributionRef",
    "StructureTutelleCreateResponse",
    "TotalCountResponse",
    "UpdateIdentifierStatus",
    "UpdateNameFormStatus",
    "UpdatePersonName",
]
