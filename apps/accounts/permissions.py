# flake8: noqa
"""
Barcha permission klasslar shu yerda markazlashtirilgan.
Boshqa app lardan import qilish: from apps.accounts.permissions import IsManager, ...
"""
from rest_framework import permissions


class IsSuperAdmin(permissions.BasePermission):
    """Faqat SUPERADMIN ruxsat"""
    message = "Faqat admin huquqiga ega foydalanuvchilar kirishi mumkin."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == 'SUPERADMIN'
        )


class IsManager(permissions.BasePermission):
    """Faqat MANAGER (Rais) ruxsat"""
    message = "Faqat Rais huquqiga ega foydalanuvchilar kirishi mumkin."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == 'MANAGER'
        )


class IsSecretary(permissions.BasePermission):
    """Faqat SECRETARY (Kotib) ruxsat"""
    message = "Faqat Kotib huquqiga ega foydalanuvchilar kirishi mumkin."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == 'SECRETARY'
        )


class IsReviewer(permissions.BasePermission):
    """Faqat REVIEWER (Tahrizchi) ruxsat"""
    message = "Faqat Tahrizchi huquqiga ega foydalanuvchilar kirishi mumkin."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == 'REVIEWER'
        )


class IsCitizen(permissions.BasePermission):
    """Faqat CITIZEN (Fuqaro) ruxsat"""
    message = "Faqat Fuqaro huquqiga ega foydalanuvchilar kirishi mumkin."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == 'CITIZEN'
        )


class IsOwnerOrAdmin(permissions.BasePermission):
    """Ob'ekt egasi yoki SUPERADMIN"""
    message = "Siz bu ob'ektga kira olmaysiz."

    def has_object_permission(self, request, view, obj):
        if request.user.role == 'SUPERADMIN':
            return True
        return obj == request.user


class IsManagerOrSecretary(permissions.BasePermission):
    """Rais yoki Kotib — birgalikda"""
    message = "Faqat Rais yoki Kotib kirishi mumkin."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role in ('MANAGER', 'SECRETARY')
        )
