# flake8: noqa
"""
Fayl yuklash uchun validatorlar.
PDF tekshiruvi, hajm cheklovi va xavfsizlik filtrlari.
"""
import os
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator


def validate_file_size(value, max_size_mb=10):
    """Fayl hajmini tekshirish (default: 10 MB)"""
    max_size = max_size_mb * 1024 * 1024
    if value.size > max_size:
        raise ValidationError(
            f"Fayl hajmi {max_size_mb} MB dan oshmasligi kerak. "
            f"Sizning faylingiz: {value.size / (1024 * 1024):.1f} MB"
        )


def validate_pdf_file(value):
    """
    Faylning haqiqatan ham PDF ekanligini tekshirish.
    1) Kengaytma tekshiruvi (.pdf)
    2) Magic bytes tekshiruvi (fayl boshi %PDF bo'lishi kerak)
    """
    # 1. Kengaytma tekshiruvi
    ext = os.path.splitext(value.name)[1].lower()
    if ext != '.pdf':
        raise ValidationError(
            f"Faqat PDF fayllar qabul qilinadi. Sizning faylingiz: {ext}"
        )

    # 2. Magic bytes — haqiqiy PDF tekshiruvi
    try:
        # Faylning boshini o'qish
        initial_pos = value.tell()
        value.seek(0)
        header = value.read(5)
        value.seek(initial_pos)  # Pozitsiyani qaytarish

        if not header.startswith(b'%PDF-'):
            raise ValidationError(
                "Fayl kengaytmasi PDF, lekin tarkibi PDF formatiga mos emas. "
                "Iltimos, haqiqiy PDF fayl yuklang."
            )
    except Exception as e:
        if isinstance(e, ValidationError):
            raise
        raise ValidationError("Faylni tekshirishda xatolik yuz berdi.")


def validate_document_file(value):
    """Hujjat fayli uchun to'liq validatsiya: PDF + 10MB"""
    validate_pdf_file(value)
    validate_file_size(value, max_size_mb=10)


def validate_review_file(value):
    """Tahriz fayli uchun to'liq validatsiya: PDF + 10MB"""
    validate_pdf_file(value)
    validate_file_size(value, max_size_mb=10)
