from django.db import models
from django.conf import settings
from apps.core.models import BaseModel


class Notification(BaseModel):
    """
    In-app bildirishnoma modeli.
    Hujjat aylanishi bo'yicha foydalanuvchilarga xabar yuborish uchun.
    """
    class Type(models.TextChoices):
        DOCUMENT_SUBMITTED = 'DOCUMENT_SUBMITTED', 'Hujjat yuborildi'
        NEW_DOCUMENT = 'NEW_DOCUMENT', 'Yangi hujjat'
        REVIEWER_ASSIGNED = 'REVIEWER_ASSIGNED', 'Tahrizchi biriktirildi'
        REVIEW_STARTED = 'REVIEW_STARTED', 'Tahriz boshlandi'
        REVIEW_SUBMITTED = 'REVIEW_SUBMITTED', 'Tahriz yuklandi'
        DOCUMENT_APPROVED = 'DOCUMENT_APPROVED', 'Tasdiqlandi'
        DOCUMENT_REJECTED = 'DOCUMENT_REJECTED', 'Rad etildi'
        REVIEW_ACCEPTED = 'REVIEW_ACCEPTED', 'Tahriz qabul qilindi'
        REVIEW_REJECTED = 'REVIEW_REJECTED', 'Tahriz rad etildi'
        DOCUMENT_DISPATCHED = 'DOCUMENT_DISPATCHED', 'Yuborildi'

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
        verbose_name="Qabul qiluvchi"
    )
    document = models.ForeignKey(
        'documents.Document',
        on_delete=models.CASCADE,
        related_name='notifications',
        verbose_name="Hujjat"
    )
    notification_type = models.CharField(
        max_length=30,
        choices=Type.choices,
        verbose_name="Turi"
    )
    message = models.TextField(verbose_name="Xabar matni")
    is_read = models.BooleanField(default=False, verbose_name="O'qilgan")

    class Meta:
        verbose_name = "Bildirishnoma"
        verbose_name_plural = "Bildirishnomalar"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'is_read']),
            models.Index(fields=['recipient', '-created_at']),
        ]

    def __str__(self):
        status_icon = "✓" if self.is_read else "●"
        return f"{status_icon} {self.recipient.email}: {self.message[:50]}"
