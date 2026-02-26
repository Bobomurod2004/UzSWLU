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
from rest_framework import permissions
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiTypes


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
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        tags=['Media'],
        summary="Himoyalangan media faylni yuklab olish",
        description=(
            "Autentifikatsiya qilingan foydalanuvchilar uchun "
            "media fayllarni (hujjat PDF lari, tahriz xulosa "
            "fayllari) xavfsiz yuklab olish.\n\n"
            "**URL formati:** `/media/<fayl_yo'li>`\n\n"
            "**Misol:** `/media/documents/2026/02/13/hujjat.pdf`\n\n"
            "**Xavfsizlik:**\n"
            "- Faqat tizimga kirgan foydalanuvchilar kirishi "
            "mumkin\n"
            "- Path traversal hujumlari (`../`) oldini olish "
            "tekshiruvi mavjud\n"
            "- Fayl mavjud bo'lmasa `404` qaytariladi\n\n"
            "**Production (nginx):**\n"
            "- `X-Accel-Redirect` headeri qaytariladi — Django "
            "o'zi faylni bermaydi, nginx xizmat qiladi\n"
            "- Bu katta fayllar uchun samaraliroq\n\n"
            "**Development:**\n"
            "- Django `FileResponse` orqali to'g'ridan-to'g'ri "
            "faylni qaytaradi\n\n"
            "**Ruxsat:** Autentifikatsiya qilingan foydalanuvchilar"
        ),
        responses={
            (200, 'application/pdf'): OpenApiTypes.BINARY,
            (200, 'application/octet-stream'): OpenApiTypes.BINARY,
            404: None,
        },
    )
    def get(self, request, file_path):
        # Agar header orqali login qilmagan bo'lsa, URL dan tokenni tekshirish
        if not request.user.is_authenticated:
            token = request.GET.get('token')
            if token:
                from rest_framework_simplejwt.tokens import AccessToken
                from rest_framework_simplejwt.exceptions import TokenError
                from django.contrib.auth import get_user_model
                
                User = get_user_model()
                try:
                    access_token = AccessToken(token)
                    user_id = access_token.get('user_id')
                    if user_id:
                        user = User.objects.get(id=user_id)
                        if user.is_active:
                            request.user = user
                except (TokenError, User.DoesNotExist):
                    pass

        # Autentifikatsiya tekshiruvi (header yoki URL token orqali)
        if not request.user.is_authenticated:
            from rest_framework.response import Response
            from rest_framework import status
            return Response(
                {"detail": "Ushbu faylni ko'rish uchun autentifikatsiya talab qilinadi."},
                status=status.HTTP_401_UNAUTHORIZED
            )

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

        # Download rejimi
        is_download = request.GET.get('download') == '1'
        filename = full_path.name

        # Production da nginx X-Accel-Redirect
        if not settings.DEBUG:
            from django.http import HttpResponse
            response = HttpResponse()
            response['Content-Type'] = content_type
            response['X-Accel-Redirect'] = f'/protected-media/{file_path}'
            if is_download:
                response['Content-Disposition'] = f'attachment; filename="{filename}"'
            else:
                response['Content-Disposition'] = f'inline; filename="{filename}"'
            return response

        # Development da Django o'zi xizmat qiladi
        return FileResponse(
            open(full_path, 'rb'),
            content_type=content_type,
            as_attachment=is_download,
            filename=filename if is_download else None
        )
