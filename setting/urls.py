# flake8: noqa
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from rest_framework_simplejwt.views import TokenRefreshView
from apps.accounts.serializers import CustomTokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView
from apps.core.views import ProtectedMediaView


# Custom login view — user ma'lumotlarini ham qaytaradi
class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer


urlpatterns = [
    # Root URL — admin panelga yo'naltirish
    path('', RedirectView.as_view(url='/admin/', permanent=False)),

    path('admin/', admin.site.urls),

    # Auth API — Login va Refresh
    path('api/token/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # Apps API
    path('api/documents/', include('apps.documents.urls')),
    path('api/accounts/', include('apps.accounts.urls')),

    # Media fayllar — har doim himoyalangan (login talab qilinadi)
    path('media/<path:file_path>', ProtectedMediaView.as_view(), name='protected-media'),
]

# API Documentation — faqat DEBUG=True da ochiq
if settings.DEBUG:
    urlpatterns += [
        path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
        path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
        path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    ]
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
