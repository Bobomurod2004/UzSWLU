# flake8: noqa
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone
from apps.core.models import BaseModel, SoftDeleteQuerySet


class UserManager(BaseUserManager):
    """
    Custom user manager that supports soft delete.
    O'chirilgan foydalanuvchilarni avtomatik filtrlab beradi.
    """
    use_in_migrations = True

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).alive()

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email manzil kiritilishi shart")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', 'SUPERADMIN')
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        return self.create_user(email, password, **extra_fields)


class UserAllManager(BaseUserManager):
    """O'chirilganlarni ham ko'rsatadigan manager"""
    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db)


phone_validator = RegexValidator(
    regex=r'^\+998[0-9]{9}$',
    message="Telefon raqam formati: +998XXXXXXXXX (12 ta raqam)"
)


class User(AbstractUser, BaseModel):
    username = None
    email = models.EmailField(unique=True, verbose_name="Email manzil")

    class Role(models.TextChoices):
        CITIZEN = 'CITIZEN', 'Fuqaro'
        SECRETARY = 'SECRETARY', 'Kotib'
        MANAGER = 'MANAGER', 'Rais'
        REVIEWER = 'REVIEWER', 'Tahrizchi'
        SUPERADMIN = 'SUPERADMIN', 'Admin'

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.CITIZEN
    )
    external_id = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        unique=True,
        help_text="OneID yoki tashqi tizim ID raqami"
    )
    phone = models.CharField(
        max_length=13,
        null=True,
        blank=True,
        validators=[phone_validator],
        help_text="Format: +998XXXXXXXXX"
    )

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = UserManager()
    all_objects = UserAllManager()

    def __str__(self):
        return f"{self.email} ({self.get_role_display()})"

    def delete(self, using=None, keep_parents=False):
        """Soft delete — bazadan o'chirmaydi, faqat belgilaydi"""
        self.deleted_at = timezone.now()
        self.is_active = False
        self.save(update_fields=['deleted_at', 'is_active', 'updated_at'])

    def hard_delete(self):
        """Bazadan butunlay o'chirish"""
        super().delete()

    @property
    def is_admin(self):
        return self.role == self.Role.SUPERADMIN

    @property
    def is_manager(self):
        return self.role == self.Role.MANAGER

    @property
    def is_secretary(self):
        return self.role == self.Role.SECRETARY

    @property
    def is_reviewer(self):
        return self.role == self.Role.REVIEWER

    @property
    def is_citizen(self):
        return self.role == self.Role.CITIZEN

    class Meta:
        verbose_name = 'Foydalanuvchi'
        verbose_name_plural = 'Foydalanuvchilar'
        indexes = [
            models.Index(fields=['role']),
            models.Index(fields=['external_id']),
            models.Index(fields=['phone']),
            models.Index(fields=['is_active', 'deleted_at']),
        ]
