from rest_framework import permissions
from apps.accounts.permissions import (  # noqa: F401
    IsCitizen,
    IsSecretary,
    IsManager,
    IsManagerOrSecretary,
    IsSuperAdmin,
)


class IsAssignedToDocument(permissions.BasePermission):
    """
    Faqat hujjatga biriktirilgan foydalanuvchi uchun ruxsat.
    Bu foydalanuvchi endi 'REVIEWER' roli bo'lishi shart emas.
    """
    message = "Siz bu hujjatga biriktirilmagansiz."

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        # obj bu yerda Document model instance
        return obj.assignments.filter(reviewer=request.user).exists()
