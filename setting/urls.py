# flake8: noqa
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from drf_spectacular.utils import extend_schema
from rest_framework_simplejwt.views import TokenRefreshView
from apps.accounts.serializers import CustomTokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView
from apps.core.views import ProtectedMediaView


# Custom login view — user ma'lumotlarini ham qaytaradi + Swagger tag
@extend_schema(
    tags=['Authentication'],
    summary="Tizimga kirish (Login)",
    description="Email va parol orqali JWT access va refresh tokenlarni olish. "
                "Response da foydalanuvchi ma'lumotlari ham qaytariladi."
)
class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer


# Token refresh uchun Swagger tag
@extend_schema(
    tags=['Authentication'],
    summary="Tokenni yangilash (Refresh)",
    description="Muddati o'tgan access tokenni yangi refresh token orqali yangilash."
)
class CustomTokenRefreshView(TokenRefreshView):
    pass


urlpatterns = [
    # Root URL — admin panelga yo'naltirish
    path('', RedirectView.as_view(url='/admin/', permanent=False)),

    path('admin/', admin.site.urls),

    # Auth API — Login va Refresh
    path('api/login/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token-refresh/', CustomTokenRefreshView.as_view(), name='token_refresh'),

    # Apps API
    path('api/documents/', include('apps.documents.urls')),
    path('api/accounts/', include('apps.accounts.urls')),

    # Media fayllar — har doim himoyalangan (login talab qilinadi)
    path('media/<path:file_path>', ProtectedMediaView.as_view(), name='protected-media'),

    # API Documentation — Swagger va ReDoc (frontendchilar uchun doim ochiq)
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]

# DEBUG rejimda Django o'zi static fayllarni beradi
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
