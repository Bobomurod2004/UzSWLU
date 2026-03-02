"""
Notification service — bildirishnoma yaratish uchun yordamchi funksiyalar.
views.py dan chaqiriladi.
"""
import logging
from django.contrib.auth import get_user_model
from .models import Notification

User = get_user_model()
logger = logging.getLogger('django')


def notify_user(recipient, document, notification_type, message):
    """Bitta foydalanuvchiga bildirishnoma yuborish"""
    notification = Notification.objects.create(
        recipient=recipient,
        document=document,
        notification_type=notification_type,
        message=message,
    )
    logger.info(
        "Notification sent to %s: [%s] %s",
        recipient.email, notification_type, message[:80]
    )
    return notification


def notify_users(recipients, document, notification_type, message):
    """Bir nechta foydalanuvchiga bildirishnoma yuborish"""
    notifications = Notification.objects.bulk_create([
        Notification(
            recipient=user,
            document=document,
            notification_type=notification_type,
            message=message,
        )
        for user in recipients
    ])
    logger.info(
        "Notification sent to %d users: [%s] %s",
        len(notifications), notification_type, message[:80]
    )
    return notifications


def notify_staff(document, notification_type, message):
    """Kotib va Manager larga bildirishnoma yuborish"""
    staff = User.objects.filter(
        role__in=['SECRETARY', 'MANAGER'],
        is_active=True,
        deleted_at__isnull=True,
    )
    return notify_users(staff, document, notification_type, message)
