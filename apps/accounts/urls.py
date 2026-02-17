# flake8: noqa
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ProfileView, ChangePasswordView, RegisterView, LogoutView,
    UserViewSet, GoogleLoginView, OneIDLoginView
)

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='users-list')

urlpatterns = [
    # Auth
    path('register/', RegisterView.as_view(), name='register'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('google-login/', GoogleLoginView.as_view(), name='google-login'),
    path('oneid-login/', OneIDLoginView.as_view(), name='oneid-login'),

    # Profile
    path('profile/', ProfileView.as_view(), name='profile'),
    path('profile/change-password/', ChangePasswordView.as_view(), name='change-password'),

    # Admin user management
    path('', include(router.urls)),
]
