from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from mptt.models import MPTTModel, TreeForeignKey
from apps.core.models import BaseModel
from apps.core.validators import validate_document_file, validate_review_file


class Category(MPTTModel, BaseModel):
    name = models.CharField(max_length=255, verbose_name="Soha nomi")
    parent = TreeForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children',
        verbose_name="Yuqori soha"
    )

    class MPTTMeta:
        order_insertion_by = ['name']

    class Meta:
        verbose_name = "Soha"
        verbose_name_plural = "Sohalar"

    def __str__(self):
        return self.name


class Document(BaseModel):
    class Status(models.TextChoices):
        NEW = 'NEW', 'Yangi'
        PENDING = 'PENDING', 'Yo\'naltirildi'
        UNDER_REVIEW = 'UNDER_REVIEW', 'Tahrizda'
        REVIEWED = 'REVIEWED', 'Tahrizlandi'
        WAITING_FOR_DISPATCH = 'WAITING_FOR_DISPATCH', 'Yuborish kutilmoqda'
        APPROVED = 'APPROVED', 'Tasdiqlandi'
        REJECTED = 'REJECTED', 'Qaytarildi'

    title = models.CharField(max_length=255, verbose_name="Hujjat nomi")
    file = models.FileField(
        upload_to='documents/%Y/%m/%d/',
        validators=[validate_document_file],
        verbose_name="PDF Hujjat"
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='documents',
        verbose_name="Soha"
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='my_documents',
        verbose_name="Yuboruvchi"
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NEW,
        verbose_name="Holati"
    )

    class Meta:
        verbose_name = "Hujjat"
        verbose_name_plural = "Hujjatlar"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} - {self.get_status_display()}"

    @property
    def assigned_reviewers(self):
        """Barcha biriktirilgan tahrizchilar"""
        return self.assignments.select_related('reviewer').all()

    @property
    def all_assignments_completed(self):
        """Barcha biriktirilgan tahrizchilar ishini tugatdimi?"""
        assignments = self.assignments.all()
        if not assignments.exists():
            return False
        return not assignments.exclude(
            status=DocumentAssignment.AssignmentStatus.COMPLETED
        ).exists()


class DocumentAssignment(BaseModel):
    """
    Hujjat-Tahrizchi biriktirmasi.
    Bitta hujjat bir nechta tahrizchiga biriktirilishi mumkin.
    """
    class AssignmentStatus(models.TextChoices):
        PENDING = 'PENDING', 'Kutilmoqda'
        IN_PROGRESS = 'IN_PROGRESS', 'Jarayonda'
        COMPLETED = 'COMPLETED', 'Bajarildi'

    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name='assignments',
        verbose_name="Hujjat"
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='document_assignments',
        verbose_name="Tahrizchi"
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='made_assignments',
        verbose_name="Kim biriktirdi"
    )
    status = models.CharField(
        max_length=20,
        choices=AssignmentStatus.choices,
        default=AssignmentStatus.PENDING,
        verbose_name="Holati"
    )

    class Meta:
        verbose_name = "Hujjat biriktirmasi"
        verbose_name_plural = "Hujjat biriktirmalari"
        unique_together = ['document', 'reviewer']
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.document.title} → {self.reviewer.email} ({self.get_status_display()})"


class Review(BaseModel):
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name='reviews',
        verbose_name="Hujjat"
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='completed_reviews',
        verbose_name="Tahrizchi"
    )
    review_file = models.FileField(
        upload_to='reviews/%Y/%m/%d/',
        validators=[validate_review_file],
        verbose_name="Tahriz PDF"
    )
    score = models.IntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        verbose_name="Ball (0-100)"
    )
    comment = models.TextField(null=True, blank=True, verbose_name="Izoh")

    class Meta:
        verbose_name = "Tahriz"
        verbose_name_plural = "Tahrizlar"
        unique_together = ['document', 'reviewer']

    def __str__(self):
        return f"Review for {self.document.title} by {self.reviewer.email}"


class DocumentHistory(BaseModel):
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name='history',
        verbose_name="Hujjat"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name="Harakat qiluvchi"
    )
    old_status = models.CharField(max_length=20, null=True, blank=True)
    new_status = models.CharField(max_length=20, null=True, blank=True)
    comment = models.TextField(null=True, blank=True, verbose_name="Izoh/Harakat")

    class Meta:
        verbose_name = "Hujjat tarixi"
        verbose_name_plural = "Hujjatlar tarixi"
        ordering = ['-created_at']

    def __str__(self):
        return f"History for {self.document.title} at {self.created_at}"
