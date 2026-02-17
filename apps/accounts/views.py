# flake8: noqa
import logging
from rest_framework import viewsets, permissions, status, generics, decorators
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from drf_spectacular.utils import extend_schema, OpenApiParameter
from .serializers import (
    UserSerializer, ProfileUpdateSerializer, RegisterSerializer,
    ChangePasswordSerializer, GoogleLoginSerializer, OneIDLoginSerializer
)
from .permissions import IsSuperAdmin, IsOwnerOrAdmin
from .services import GoogleAuthService, OneIDService
from django.contrib.auth import get_user_model

User = get_user_model()
logger = logging.getLogger('apps.accounts')


def _get_tokens_for_user(user):
    """Foydalanuvchi uchun JWT token juftligini yaratish"""
    refresh = RefreshToken.for_user(user)
    return {
        'access': str(refresh.access_token),
        'refresh': str(refresh),
    }


@extend_schema(
    tags=['Authentication'],
    summary="Yangi foydalanuvchi (Fuqaro) ro'yxatdan o'tishi",
    description=(
        "Ushbu API orqali yangi fuqarolar tizimda o'z hisoblarini yaratishlari mumkin. "
        "Parol kamida 8 ta belgidan iborat va kuchli bo'lishi shart. "
        "Muvaffaqiyatli ro'yxatdan o'tganda JWT tokenlar qaytariladi."
    ),
    responses={201: {'type': 'object', 'properties': {
        'user': {'type': 'object'},
        'access': {'type': 'string'},
        'refresh': {'type': 'string'},
    }}}
)
class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = (permissions.AllowAny,)
    serializer_class = RegisterSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        logger.info("Yangi foydalanuvchi ro'yxatdan o'tdi: %s (IP: %s)",
                     user.email, self._get_client_ip(request))

        tokens = _get_tokens_for_user(user)
        return Response({
            'user': UserSerializer(user).data,
            **tokens,
        }, status=status.HTTP_201_CREATED)

    @staticmethod
    def _get_client_ip(request):
        x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        return x_forwarded.split(',')[0].strip() if x_forwarded else request.META.get('REMOTE_ADDR')


@extend_schema(
    tags=['Authentication'],
    summary="Tizimdan chiqish (Logout)",
    description="Refresh tokenni blacklistga kiritish orqali foydalanuvchi seansini tugatadi.",
    request={'application/json': {'type': 'object', 'properties': {'refresh': {'type': 'string'}}, 'required': ['refresh']}},
    responses={205: None, 400: 'Xato so\'rov'}
)
class LogoutView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response(
                {"refresh": "Refresh token kiritilishi shart"},
                status=status.HTTP_400_BAD_REQUEST
            )
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
            logger.info("Foydalanuvchi tizimdan chiqdi: %s", request.user.email)
            return Response(
                {"detail": "Tizimdan muvaffaqiyatli chiqildi"},
                status=status.HTTP_205_RESET_CONTENT
            )
        except TokenError:
            return Response(
                {"refresh": "Token yaroqsiz yoki muddati o'tgan"},
                status=status.HTTP_400_BAD_REQUEST
            )


@extend_schema(
    tags=['Authentication'],
    summary="Google orqali kirish",
    description="Frontenddan olingan Google access_token orqali tizimga kirish yoki ro'yxatdan o'tish.",
    request=GoogleLoginSerializer,
    responses={200: {'type': 'object', 'properties': {
        'user': {'type': 'object'},
        'access': {'type': 'string'},
        'refresh': {'type': 'string'},
    }}}
)
class GoogleLoginView(generics.GenericAPIView):
    permission_classes = (permissions.AllowAny,)
    serializer_class = GoogleLoginSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        token = serializer.validated_data.get('access_token')
        user = GoogleAuthService.get_or_create_user(token)

        tokens = _get_tokens_for_user(user)
        return Response({
            'user': UserSerializer(user).data,
            **tokens,
        }, status=status.HTTP_200_OK)


@extend_schema(
    tags=['Authentication'],
    summary="OneID orqali kirish",
    description="OneID tizimidan olingan vaqtinchalik 'code' orqali tizimga kirish yoki ro'yxatdan o'tish.",
    request=OneIDLoginSerializer,
    responses={200: {'type': 'object', 'properties': {
        'user': {'type': 'object'},
        'access': {'type': 'string'},
        'refresh': {'type': 'string'},
    }}}
)
class OneIDLoginView(generics.GenericAPIView):
    permission_classes = (permissions.AllowAny,)
    serializer_class = OneIDLoginSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        code = serializer.validated_data.get('code')
        user = OneIDService.get_or_create_user(code)

        tokens = _get_tokens_for_user(user)
        return Response({
            'user': UserSerializer(user).data,
            **tokens,
        }, status=status.HTTP_200_OK)


@extend_schema(tags=['Profiles'])
class ProfileView(APIView):
    """
    Joriy foydalanuvchi o'z profilini ko'rishi va yangilashi.
    GET  — profilni olish
    PATCH — profilni yangilash (first_name, last_name, phone)
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="O'z profilini ko'rish",
        responses={200: UserSerializer}
    )
    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    @extend_schema(
        summary="Profilni yangilash",
        request=ProfileUpdateSerializer,
        responses={200: UserSerializer}
    )
    def patch(self, request):
        serializer = ProfileUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserSerializer(request.user).data)


@extend_schema(
    tags=['Profiles'],
    summary="Parolni o'zgartirish",
    description="Eski parolni tekshirgan holda yangi parolni o'rnatish.",
    request=ChangePasswordSerializer,
    responses={
        200: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        400: 'Xato ma\'lumotlar'
    }
)
class ChangePasswordView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        if not user.check_password(serializer.validated_data['old_password']):
            return Response(
                {"old_password": ["Eski parol noto'g'ri"]},
                status=status.HTTP_400_BAD_REQUEST
            )

        user.set_password(serializer.validated_data['new_password'])
        user.save(update_fields=['password'])
        return Response(
            {"detail": "Parol muvaffaqiyatli o'zgartirildi"},
            status=status.HTTP_200_OK
        )


@extend_schema(
    tags=['Users Management'],
    summary="Barcha foydalanuvchilar ro'yxati va boshqaruvi",
    description="Faqat SUPERADMIN foydalana oladi. Foydalanuvchilarni qidirish, filtrlash va to'liq boshqarish imkonini beradi."
)
class UserViewSet(viewsets.ModelViewSet):
    """SUPERADMIN uchun barcha foydalanuvchilarni to'liq boshqarish API si"""
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsSuperAdmin]

    filterset_fields = ['role', 'is_active']
    search_fields = ['email', 'first_name', 'last_name', 'phone']
    ordering_fields = ['date_joined', 'email']
    ordering = ['-date_joined']

    def perform_destroy(self, instance):
        """Soft delete — bazadan o'chirmaydi"""
        instance.delete()
