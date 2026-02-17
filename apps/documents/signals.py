# flake8: noqa
"""
Document signals.

DocumentHistory yozuvlari endi views.py dagi _record_history() orqali
yaratiladi — chunki faqat view'da request.user mavjud bo'ladi.

Signal faqat admin panel yoki boshqa joylardan o'zgarishlarni
kuzatish uchun saqlanadi (user=NULL bo'ladi).
"""
from django.db.models.signals import pre_save
from django.dispatch import receiver
from .models import Document


@receiver(pre_save, sender=Document)
def capture_old_status(sender, instance, **kwargs):
    """
    Saqlashdan oldin eski statusni eslab qolish.
    Bu views.py dagi _record_history() uchun kerak emas,
    lekin admin panel orqali o'zgarishlarni kuzatish uchun foydali.
    """
    if instance.pk:
        try:
            old_instance = Document.objects.get(pk=instance.pk)
            instance._old_status = old_instance.status
        except Document.DoesNotExist:
            instance._old_status = None
    else:
        instance._old_status = None
