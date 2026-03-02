from rest_framework import serializers
from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    """Bildirishnoma serializer"""
    document_title = serializers.CharField(
        source='document.title', read_only=True
    )
    notification_type_display = serializers.CharField(
        source='get_notification_type_display', read_only=True
    )

    class Meta:
        model = Notification
        fields = [
            'id', 'notification_type', 'notification_type_display',
            'message', 'document', 'document_title',
            'is_read', 'created_at',
        ]
        read_only_fields = [
            'id', 'notification_type', 'message',
            'document', 'is_read', 'created_at',
        ]


class UnreadCountSerializer(serializers.Serializer):
    """O'qilmagan bildirishnomalar soni"""
    unread_count = serializers.IntegerField(
        help_text="O'qilmagan bildirishnomalar soni"
    )
