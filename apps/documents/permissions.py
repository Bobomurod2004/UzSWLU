"""
Documents app permissionlari.
Barcha role-based permissionlar accounts app dan import qilinadi (DRY).
"""
from apps.accounts.permissions import (  # noqa: F401
    IsCitizen,
    IsSecretary,
    IsManager,
    IsReviewer,
    IsManagerOrSecretary,
    IsSuperAdmin,
)
