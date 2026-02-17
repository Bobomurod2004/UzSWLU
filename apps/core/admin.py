from django.contrib import admin
from django.utils.html import format_html
from .models import APIRequestLog


@admin.register(APIRequestLog)
class APIRequestLogAdmin(admin.ModelAdmin):
    """
    API so'rovlarini ko'rish uchun admin panel.
    Frontchi qanday so'rov yuborayotganini real-time kuzatish mumkin.
    """
    list_display = (
        'created_at', 'colored_method', 'path', 'user',
        'colored_status', 'duration_ms', 'ip_address'
    )
    list_filter = ('method', 'response_status', 'created_at', 'user')
    search_fields = ('path', 'user__email', 'ip_address', 'request_body', 'response_body')
    readonly_fields = (
        'user', 'method', 'path', 'query_params',
        'formatted_request_body', 'response_status', 'formatted_response_body',
        'ip_address', 'user_agent', 'duration_ms', 'created_at'
    )
    list_per_page = 50
    ordering = ('-created_at',)
    date_hierarchy = 'created_at'

    # Qo'shish/tahrirlash/o'chirish bloklash — faqat ko'rish
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def colored_method(self, obj):
        """HTTP metodni rangli ko'rsatish"""
        colors = {
            'GET': '#2196F3',
            'POST': '#4CAF50',
            'PUT': '#FF9800',
            'PATCH': '#FF9800',
            'DELETE': '#F44336',
        }
        color = colors.get(obj.method, '#999')
        return format_html(
            '<span style="color:{}; font-weight:bold; font-family:monospace;">{}</span>',
            color, obj.method
        )
    colored_method.short_description = 'Metod'
    colored_method.admin_order_field = 'method'

    def colored_status(self, obj):
        """Status kodni rangli ko'rsatish"""
        if obj.response_status is None:
            return '-'
        code = obj.response_status
        if 200 <= code < 300:
            color = '#4CAF50'
        elif 300 <= code < 400:
            color = '#2196F3'
        elif 400 <= code < 500:
            color = '#FF9800'
        else:
            color = '#F44336'
        return format_html(
            '<span style="color:{}; font-weight:bold; font-family:monospace;">{}</span>',
            color, code
        )
    colored_status.short_description = 'Status'
    colored_status.admin_order_field = 'response_status'

    def formatted_request_body(self, obj):
        """Request body ni ko'rish uchun formatlash"""
        if not obj.request_body:
            return '-'
        return format_html('<pre style="white-space:pre-wrap; max-width:800px;">{}</pre>', obj.request_body)
    formatted_request_body.short_description = "So'rov tanasi"

    def formatted_response_body(self, obj):
        """Response body ni ko'rish uchun formatlash"""
        if not obj.response_body:
            return '-'
        return format_html('<pre style="white-space:pre-wrap; max-width:800px;">{}</pre>', obj.response_body)
    formatted_response_body.short_description = "Javob tanasi"

    fieldsets = (
        ("So'rov ma'lumotlari", {
            'fields': ('created_at', 'user', 'ip_address', 'user_agent')
        }),
        ("HTTP So'rov", {
            'fields': ('method', 'path', 'query_params', 'formatted_request_body')
        }),
        ("HTTP Javob", {
            'fields': ('response_status', 'formatted_response_body', 'duration_ms')
        }),
    )
