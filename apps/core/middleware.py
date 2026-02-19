"""
API Request Logging Middleware
Barcha /api/ so'rovlarini bazaga yozadi.
Admin panelda ko'rish mumkin: frontchi qaysi endpointga nima yuborayotganini real-time kuzatish.
"""
import json
import time
import traceback

from django.conf import settings
from django.utils.deprecation import MiddlewareMixin


class APIRequestLogMiddleware(MiddlewareMixin):
    """
    /api/ boshlanadigan barcha so'rovlarni APIRequestLog modeliga yozadi.
    - Request body (POST/PUT/PATCH) — fayllardan tashqari
    - Response status va body (JSON javoblar)
    - Duration (ms)
    - User, IP, User-Agent
    """

    # Logga yozmaslik kerak bo'lgan yo'llar
    SKIP_PATHS = [
        '/admin/',
        '/static/',
        '/favicon.ico',
    ]

    # Response body da maxfiy maydonlarni yashirish
    SENSITIVE_FIELDS = {'password', 'old_password', 'new_password', 'token', 'access', 'refresh'}

    # Max body hajmi (juda katta javoblarni qisqartirish)
    MAX_BODY_LENGTH = 4000

    def _should_log(self, request):
        """Faqat /api/ so'rovlarini logga yozamiz"""
        path = request.path
        if not path.startswith('/api/'):
            return False
        for skip in self.SKIP_PATHS:
            if path.startswith(skip):
                return False
        return True

    def _get_client_ip(self, request):
        xff = request.META.get('HTTP_X_FORWARDED_FOR')
        if xff:
            return xff.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '')

    def _get_request_body(self, request):
        """Request body ni xavfsiz olish"""
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return ''
        content_type = request.content_type or ''
        # Multipart fayllarni logga yozmaymiz (faqat maydon nomlari)
        if 'multipart' in content_type:
            fields = {}
            for key in request.POST:
                value = request.POST[key]
                if key.lower() in self.SENSITIVE_FIELDS:
                    fields[key] = '***'
                else:
                    fields[key] = value[:200] if len(value) > 200 else value
            if request.FILES:
                fields['_files'] = [
                    f"{name} ({f.size} bytes, {f.content_type})"
                    for name, f in request.FILES.items()
                ]
            return json.dumps(fields, ensure_ascii=False, default=str)[:self.MAX_BODY_LENGTH]
        # JSON body — cache qilingan body ni ishlatamiz
        try:
            raw = getattr(request, '_api_log_body', None)
            if raw is None:
                return '(body not available)'
            body = raw.decode('utf-8', errors='replace')
            if body:
                data = json.loads(body)
                if isinstance(data, dict):
                    for key in self.SENSITIVE_FIELDS:
                        if key in data:
                            data[key] = '***'
                return json.dumps(data, ensure_ascii=False, default=str)[:self.MAX_BODY_LENGTH]
            return body[:self.MAX_BODY_LENGTH]
        except (json.JSONDecodeError, UnicodeDecodeError):
            return '(binary/unparseable)'

    def _get_response_body(self, response):
        """Response body ni xavfsiz olish"""
        content_type = response.get('Content-Type', '')
        if 'application/json' not in content_type:
            return f'({content_type or "no content-type"})'
        try:
            body = response.content.decode('utf-8', errors='replace')
            data = json.loads(body)
            if isinstance(data, dict):
                for key in self.SENSITIVE_FIELDS:
                    if key in data:
                        data[key] = '***'
            return json.dumps(data, ensure_ascii=False, default=str)[:self.MAX_BODY_LENGTH]
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            return '(unparseable)'

    def process_request(self, request):
        """So'rov boshlanish vaqtini belgilash va body ni cache qilish"""
        if self._should_log(request):
            request._api_log_start = time.time()
            # DRF request.data ni o'qigandan keyin request.body ga
            # murojaat qilib bo'lmaydi (RawPostDataException).
            # Shuning uchun body ni hoziroq cache qilamiz.
            try:
                request._api_log_body = request.body
            except Exception:
                request._api_log_body = None

    def process_response(self, request, response):
        """So'rov tugaganda logga yozish"""
        if not self._should_log(request):
            return response

        try:
            from apps.core.models import APIRequestLog

            duration = None
            if hasattr(request, '_api_log_start'):
                duration = int((time.time() - request._api_log_start) * 1000)

            user = None
            if hasattr(request, 'user') and request.user.is_authenticated:
                user = request.user

            APIRequestLog.objects.create(
                user=user,
                method=request.method,
                path=request.path,
                query_params=request.META.get('QUERY_STRING', ''),
                request_body=self._get_request_body(request),
                response_status=response.status_code,
                response_body=self._get_response_body(response),
                ip_address=self._get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
                duration_ms=duration,
            )
        except Exception:
            # Logging xatosi boshqa so'rovlarni buzmasligi kerak
            if settings.DEBUG:
                traceback.print_exc()

        return response
