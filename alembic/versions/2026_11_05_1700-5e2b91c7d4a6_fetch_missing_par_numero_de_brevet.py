"""Recherche des brevets manquants par numéro

La phase `fetch_missing` cherche dans ScanR brevets les familles par numéro de publication ou de demande. `failed_lookups` reçoit ses recherches vaines, et `staging.entry_mode` sa voie d'entrée `fetch_missing_patent_number`.

Revision ID: 5e2b91c7d4a6
Revises: a7c3e9f15b28
Create Date: 2026-11-05 17:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "5e2b91c7d4a6"
down_revision: str | Sequence[str] | None = "a7c3e9f15b28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LOOKUP_ID_TYPES = ("doi", "hal_id", "nnt")
_PATENT_ID_TYPES = ("patent_publication_number", "patent_application_number")
_ENTRY_MODES = (
    "bulk",
    "fetch_missing_doi",
    "manual_export",
    "person_identifier",
    "fetch_missing_hal_id",
    "fetch_missing_nnt",
)
_PATENT_ENTRY_MODE = "fetch_missing_patent_number"


def _array(values: Sequence[str]) -> str:
    return "ARRAY[" + ", ".join(f"'{v}'::text" for v in values) + "]"


def _replace_checks(id_types: Sequence[str], entry_modes: Sequence[str]) -> None:
    op.execute(f"""
        ALTER TABLE sources.failed_lookups DROP CONSTRAINT failed_lookups_id_type_check;
        ALTER TABLE sources.failed_lookups ADD CONSTRAINT failed_lookups_id_type_check
            CHECK (id_type = ANY ({_array(id_types)}));
        ALTER TABLE sources.staging DROP CONSTRAINT staging_entry_mode_check;
        ALTER TABLE sources.staging ADD CONSTRAINT staging_entry_mode_check
            CHECK (entry_mode = ANY ({_array(entry_modes)}));
    """)


def upgrade() -> None:
    _replace_checks((*_LOOKUP_ID_TYPES, *_PATENT_ID_TYPES), (*_ENTRY_MODES, _PATENT_ENTRY_MODE))


def downgrade() -> None:
    op.execute(f"""
        DELETE FROM sources.failed_lookups WHERE id_type IN {tuple(_PATENT_ID_TYPES)};
        UPDATE sources.staging SET entry_mode = 'bulk' WHERE entry_mode = '{_PATENT_ENTRY_MODE}';
    """)
    _replace_checks(_LOOKUP_ID_TYPES, _ENTRY_MODES)
