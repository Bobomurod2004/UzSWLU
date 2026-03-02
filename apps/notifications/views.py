from rest_framework import viewsets, permissions, status, decorators
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema
from .models import Notification
from .serializers import NotificationSerializer, UnreadCountSerializer


@extend_schema(tags=['Notifications'])
class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Bildirishnomalar bilan ishlash.
    Foydalanuvchi faqat o'z bildirishnomalarini ko'ra oladi.

    - GET /api/notifications/ — barcha bildirishnomalar (sahifalangan)
    - GET /api/notifications/unread_count/ — o'qilmagan soni
    - POST /api/notifications/{id}/mark_read/ — o'qilgan deb belgilash
    - POST /api/notifications/mark_all_read/ — hammasini o'qilgan deb belgilash
    """
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['is_read', 'notification_type']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Notification.objects.none()
        return Notification.objects.filter(
            recipient=self.request.user
        ).select_related('document')

    @extend_schema(
        summary="Bildirishnomalar ro'yxati",
        description=(
            "Joriy foydalanuvchining barcha bildirishnomalarini "
            "qaytaradi (oxirgilari birinchi).\n\n"
            "**Filtrlash:**\n"
            "- `is_read=true/false` — o'qilgan/o'qilmaganlarni\n"
            "- `notification_type` — turi bo'yicha\n\n"
            "**Ruxsat:** Autentifikatsiya qilingan foydalanuvchi"
        ),
        responses={200: NotificationSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        summary="Bildirishnoma tafsilotlari",
        description="ID bo'yicha bitta bildirishnomani qaytaradi.",
        responses={200: NotificationSerializer},
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        summary="O'qilmagan bildirishnomalar soni",
        description=(
            "Joriy foydalanuvchining o'qilmagan "
            "bildirishnomalar sonini qaytaradi.\n\n"
            "**Foydalanish:** Frontend da badge/counter "
            "ko'rsatish uchun."
        ),
        responses={200: UnreadCountSerializer},
    )
    @decorators.action(
        detail=False,
        methods=['get'],
    )
    def unread_count(self, request):
        count = self.get_queryset().filter(is_read=False).count()
        return Response({'unread_count': count})

    @extend_schema(
        summary="Bildirishnomani o'qilgan deb belgilash",
        description=(
            "Bitta bildirishnomani o'qilgan deb belgilaydi.\n\n"
            "**Ruxsat:** Faqat o'z bildirishnomasini belgilash mumkin."
        ),
        request=None,
        responses={200: NotificationSerializer},
    )
    @decorators.action(
        detail=True,
        methods=['post'],
    )
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        notification.is_read = True
        notification.save(update_fields=['is_read', 'updated_at'])
        return Response(NotificationSerializer(notification).data)

    @extend_schema(
        summary="Barcha bildirishnomalarni o'qilgan deb belgilash",
        description=(
            "Joriy foydalanuvchining barcha o'qilmagan "
            "bildirishnomalarini o'qilgan deb belgilaydi."
        ),
        request=None,
        responses={200: UnreadCountSerializer},
    )
    @decorators.action(
        detail=False,
        methods=['post'],
    )
    def mark_all_read(self, request):
        updated = self.get_queryset().filter(
            is_read=False
        ).update(is_read=True)
        return Response({
            'unread_count': 0,
            'updated': updated,
        })
