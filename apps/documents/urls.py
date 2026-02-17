from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CategoryViewSet, DocumentViewSet

router = DefaultRouter()
router.register(r'categories', CategoryViewSet)
router.register(r'', DocumentViewSet, basename='document')

urlpatterns = [
    path('', include(router.urls)),
]
