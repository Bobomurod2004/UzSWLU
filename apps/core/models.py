from django.conf import settings
from django.db import models
from django.utils import timezone


class SoftDeleteQuerySet(models.QuerySet):
    def delete(self):
        return super().update(deleted_at=timezone.now(), is_active=False)

    def hard_delete(self):
        return super().delete()

    def alive(self):
        return self.filter(deleted_at__isnull=True)

    def dead(self):
        return self.exclude(deleted_at__isnull=True)

class SoftDeleteManager(models.Manager):
    def __init__(self, *args, **kwargs):
        self.alive_only = kwargs.pop('alive_only', True)
        super(SoftDeleteManager, self).__init__(*args, **kwargs)

    def get_queryset(self):
        if self.alive_only:
            return SoftDeleteQuerySet(self.model).alive()
        return SoftDeleteQuerySet(self.model)

    def hard_delete(self):
        return self.get_queryset().hard_delete()

class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    objects = SoftDeleteManager()
    all_objects = SoftDeleteManager(alive_only=False)

    class Meta:
        abstract = True

    def delete(self):
        self.deleted_at = timezone.now()
        self.is_active = False
        self.save()

    def hard_delete(self):
        super(BaseModel, self).delete()


class APIRequestLog(models.Model):
    """Barcha API so'rovlarini logga yozish modeli"""

    class Method(models.TextChoices):
        GET = 'GET'
        POST = 'POST'
        PUT = 'PUT'
        PATCH = 'PATCH'
        DELETE = 'DELETE'
        OPTIONS = 'OPTIONS'
        HEAD = 'HEAD'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='api_logs',
        verbose_name="Foydalanuvchi"
    )
    method = models.CharField(max_length=10, choices=Method.choices, verbose_name="HTTP Metod")
    path = models.CharField(max_length=500, verbose_name="URL yo'l", db_index=True)
    query_params = models.TextField(blank=True, default='', verbose_name="Query parametrlar")
    request_body = models.TextField(blank=True, default='', verbose_name="So'rov tanasi")
    response_status = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name="Javob kodi"
    )
    response_body = models.TextField(blank=True, default='', verbose_name="Javob tanasi")
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP manzil")
    user_agent = models.CharField(max_length=500, blank=True, default='', verbose_name="User-Agent")
    duration_ms = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="Davomiyligi (ms)"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Vaqt", db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "API So'rov Logi"
        verbose_name_plural = "API So'rov Loglari"
        indexes = [
            models.Index(fields=['method', 'path']),
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['response_status']),
        ]

    def __str__(self):
        user_str = self.user.email if self.user else 'Anonim'
        return f"[{self.method}] {self.path} — {user_str} ({self.response_status})"
