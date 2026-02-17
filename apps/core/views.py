# flake8: noqa
"""
Himoyalangan media fayllarni xizmat qilish.
Faqat autentifikatsiyadan o'tgan foydalanuvchilar fayllarni yuklab olishi mumkin.

Production da nginx X-Accel-Redirect ishlatiladi.
Development da Django o'zi faylni qaytaradi.
"""
import mimetypes
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView


class ProtectedMediaView(APIView):
    """
    Media fayllarni autentifikatsiya bilan himoyalash.

    URL: /media/<path>
    Faqat login qilgan foydalanuvchi kirishi mumkin.

    Production (nginx) da:
        X-Accel-Redirect header qaytariladi — nginx o'zi faylni beradi.
    Development da:
        Django to'g'ridan-to'g'ri faylni qaytaradi.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, file_path):
        # Fayl yo'lini xavfsiz tekshirish — path traversal himoyasi
        full_path = Path(settings.MEDIA_ROOT) / file_path
        full_path = full_path.resolve()

        # Path traversal hujumini oldini olish (../../etc/passwd)
        media_root = Path(settings.MEDIA_ROOT).resolve()
        if not str(full_path).startswith(str(media_root)):
            raise Http404("Fayl topilmadi")

        if not full_path.is_file():
            raise Http404("Fayl topilmadi")

        # Content type aniqlash
        content_type, _ = mimetypes.guess_type(str(full_path))
        content_type = content_type or 'application/octet-stream'

        # Production da nginx X-Accel-Redirect
        if not settings.DEBUG:
            from django.http import HttpResponse
            response = HttpResponse()
            response['Content-Type'] = content_type
            response['X-Accel-Redirect'] = f'/protected-media/{file_path}'
            return response

        # Development da Django o'zi xizmat qiladi
        return FileResponse(
            open(full_path, 'rb'),
            content_type=content_type,
        )
