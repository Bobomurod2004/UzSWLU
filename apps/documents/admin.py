from django.contrib import admin
from mptt.admin import DraggableMPTTAdmin
from .models import Category, Document, DocumentAssignment, Review, DocumentHistory


@admin.register(Category)
class CategoryAdmin(DraggableMPTTAdmin):
    mptt_indent_field = "name"
    list_display = ('tree_actions', 'indented_title', 'id')
    list_display_links = ('indented_title',)


class DocumentAssignmentInline(admin.TabularInline):
    model = DocumentAssignment
    extra = 0
    readonly_fields = ('reviewer', 'assigned_by', 'status', 'created_at')
    can_delete = False


class ReviewInline(admin.StackedInline):
    model = Review
    extra = 0
    readonly_fields = ('reviewer', 'document',
                       'review_file', 'score', 'comment')


class DocumentHistoryInline(admin.TabularInline):
    model = DocumentHistory
    extra = 0
    readonly_fields = ('user', 'old_status',
                       'new_status', 'comment', 'created_at')
    can_delete = False


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ('title', 'owner', 'category', 'status', 'created_at')
    list_filter = ('status', 'category', 'created_at')
    search_fields = ('title', 'owner__email')
    inlines = [DocumentAssignmentInline, ReviewInline, DocumentHistoryInline]
    readonly_fields = ('created_at', 'updated_at', 'deleted_at')


@admin.register(DocumentAssignment)
class DocumentAssignmentAdmin(admin.ModelAdmin):
    list_display = ('document', 'reviewer', 'assigned_by', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('document__title', 'reviewer__email', 'assigned_by__email')
    readonly_fields = ('document', 'reviewer', 'assigned_by', 'status', 'created_at')


@admin.register(DocumentHistory)
class DocumentHistoryAdmin(admin.ModelAdmin):
    list_display = ('document', 'user', 'old_status',
                    'new_status', 'created_at')
    list_filter = ('new_status', 'created_at')
    readonly_fields = ('document', 'user', 'old_status',
                       'new_status', 'comment', 'created_at')
