# flake8: noqa
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from .models import User

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("id",'email', 'get_full_name', 'get_role_label', 'phone', 'is_staff', 'is_active', 'date_joined')
    list_filter = ('role', 'is_staff', 'is_active', 'date_joined')
    search_fields = ('email', 'first_name', 'last_name', 'phone', 'external_id')
    ordering = ('-date_joined', 'email')

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Shaxsiy ma\'lumotlar', {'fields': ('first_name', 'last_name', 'phone')}),
        ('Ruxsatlar', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Muhim sanalar', {'fields': ('last_login', 'date_joined')}),
        ('Qo\'shimcha ma\'lumotlar', {'fields': ('role', 'external_id', 'deleted_at')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'password1', 'password2', 'first_name', 'last_name', 'role', 'phone', 'external_id'),
        }),
    )

    def get_role_label(self, obj):
        colors = {
            'SUPERADMIN': 'red',
            'MANAGER': 'blue',
            'SECRETARY': 'green',
            'REVIEWER': 'orange',
            'CITIZEN': 'gray'
        }
        color = colors.get(obj.role, 'black')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_role_display()
        )
    get_role_label.short_description = 'Rol'
