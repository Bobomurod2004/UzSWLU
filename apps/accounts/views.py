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
    ChangePasswordSerializer, GoogleLoginSerializer, OneIDLoginSerializer,
    AuthTokenResponseSerializer, LogoutRequestSerializer,
    DetailResponseSerializer, ErrorResponseSerializer,
    ChangeRoleSerializer, UserCreateSerializer,
    AdminResetPasswordSerializer,
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
        "Ushbu API orqali yangi fuqarolar tizimda o'z hisoblarini "
        "yaratishlari mumkin. Ro'yxatdan o'tgan foydalanuvchiga "
        "avtomatik ravishda **CITIZEN** roli beriladi.\n\n"
        "**Majburiy maydonlar:**\n"
        "- `email` \u2014 elektron pochta manzili (unikal)\n"
        "- `password` \u2014 kamida 8 ta belgi, Django "
        "standart validatorlari bilan tekshiriladi\n"
        "- `first_name`, `last_name` \u2014 ism va familiya\n\n"
        "**Ixtiyoriy maydonlar:**\n"
        "- `phone` \u2014 +998XXXXXXXXX formatida telefon raqam\n\n"
        "**Muvaffaqiyatli javob:**\n"
        "Foydalanuvchi ma'lumotlari va JWT tokenlar "
        "(`access` va `refresh`) qaytariladi. Frontendchi "
        "tokenlarni saqlaydi va keyingi so'rovlarda "
        "`Authorization: Bearer <access>` headerida yuboradi.\n\n"
        "**Ruxsat:** Autentifikatsiya talab etilmaydi (AllowAny)"
    ),
    request=RegisterSerializer,
    responses={
        201: AuthTokenResponseSerializer,
        400: ErrorResponseSerializer,
    },
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
    description=(
        "Foydalanuvchining sessiyasini yakunlaydi. "
        "Buning uchun `refresh` token blacklist ga "
        "qo'shiladi va qayta ishlatib bo'lmaydi.\n\n"
        "**So'rov tanasi:**\n"
        "```json\n"
        "{\"refresh\": \"<refresh_token>\"}\n"
        "```\n\n"
        "**Eslatma:**\n"
        "- Access token muddati o'tguncha ishlayveradi "
        "(stateless JWT xususiyati)\n"
        "- Frontendchi access tokenni ham o'z tomonida "
        "o'chirishi zarur\n"
        "- Token allaqachon blacklistda bo'lsa yoki "
        "muddati o'tgan bo'lsa, 400 xatosi qaytariladi\n\n"
        "**Ruxsat:** Autentifikatsiya qilingan foydalanuvchilar"
    ),
    request=LogoutRequestSerializer,
    responses={
        205: DetailResponseSerializer,
        400: ErrorResponseSerializer,
    },
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
    description=(
        "Google OAuth2 yordamida tizimga kirish yoki "
        "yangi hisob yaratish.\n\n"
        "**Ishlash tartibi:**\n"
        "1. Frontend foydalanuvchini Google "
        "avtorizatsiya sahifasiga yo'naltiradi\n"
        "2. Google `access_token` beradi\n"
        "3. Frontend ushbu `access_token` ni shu API ga "
        "yuboradi\n"
        "4. Backend Google API dan foydalanuvchi "
        "ma'lumotlarini oladi\n"
        "5. Agar foydalanuvchi mavjud bo'lsa \u2014 kirish; "
        "yo'q bo'lsa \u2014 CITIZEN sifatida yaratiladi\n\n"
        "**So'rov tanasi:**\n"
        "```json\n"
        "{\"access_token\": \"ya29.a0...\"}\n"
        "```\n\n"
        "**Javob:** Foydalanuvchi ma'lumotlari va JWT "
        "tokenlar (access + refresh)\n\n"
        "**Ruxsat:** Autentifikatsiya talab etilmaydi"
    ),
    request=GoogleLoginSerializer,
    responses={
        200: AuthTokenResponseSerializer,
        401: ErrorResponseSerializer,
    },
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
    description=(
        "O'zbekiston Respublikasining OneID tizimi orqali "
        "autentifikatsiya.\n\n"
        "**Ishlash tartibi:**\n"
        "1. Frontend foydalanuvchini OneID avtorizatsiya "
        "sahifasiga yo'naltiradi\n"
        "2. Foydalanuvchi OneID da login qiladi\n"
        "3. OneID `code` (vaqtinchalik kod) qaytaradi\n"
        "4. Frontend ushbu `code` ni shu API ga yuboradi\n"
        "5. Backend OneID API dan access_token va "
        "foydalanuvchi ma'lumotlarini oladi\n"
        "6. Agar foydalanuvchi mavjud bo'lsa \u2014 kirish; "
        "yo'q bo'lsa \u2014 CITIZEN sifatida yaratiladi\n\n"
        "**So'rov tanasi:**\n"
        "```json\n"
        "{\"code\": \"abc123...\"}\n"
        "```\n\n"
        "**Javob:** Foydalanuvchi ma'lumotlari va JWT "
        "tokenlar (access + refresh)\n\n"
        "**Ruxsat:** Autentifikatsiya talab etilmaydi"
    ),
    request=OneIDLoginSerializer,
    responses={
        200: AuthTokenResponseSerializer,
        401: ErrorResponseSerializer,
    },
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
        description=(
            "Joriy autentifikatsiya qilingan foydalanuvchining "
            "to'liq profil ma'lumotlarini qaytaradi.\n\n"
            "**Qaytariladigan maydonlar:**\n"
            "- `id` \u2014 foydalanuvchi identifikatori\n"
            "- `email` \u2014 elektron pochta\n"
            "- `first_name`, `last_name` \u2014 ism, familiya\n"
            "- `phone` \u2014 telefon raqam\n"
            "- `role` \u2014 roli (CITIZEN, SECRETARY, ...)\n"
            "- `is_active` \u2014 faollik holati\n"
            "- `date_joined` \u2014 ro'yxatdan o'tgan sanasi\n\n"
            "**Ruxsat:** Autentifikatsiya qilingan "
            "foydalanuvchilar"
        ),
        responses={200: UserSerializer}
    )
    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    @extend_schema(
        summary="O'z profilini yangilash",
        description=(
            "Joriy foydalanuvchining profil ma'lumotlarini "
            "qisman yangilaydi (PATCH).\n\n"
            "**O'zgartirish mumkin bo'lgan maydonlar:**\n"
            "- `first_name` \u2014 yangi ism\n"
            "- `last_name` \u2014 yangi familiya\n"
            "- `phone` \u2014 telefon raqam "
            "(+998XXXXXXXXX formatda)\n\n"
            "**O'zgartirib bo'lmaydigan:**\n"
            "- `email`, `role`, `is_active` \u2014 "
            "admin tomonidan o'zgartiriladi\n\n"
            "**Misol:**\n"
            "```json\n"
            "{\"first_name\": \"Ali\", "
            "\"phone\": \"+998901234567\"}\n"
            "```\n\n"
            "**Ruxsat:** Autentifikatsiya qilingan "
            "foydalanuvchilar (faqat o'z profili)"
        ),
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
    summary="Parolni o'zgartirish (eski parolsiz)",
    description=(
        "Joriy foydalanuvchining parolini o'zgartiradi.\n\n"
        "**Majburiy maydonlar:**\n"
        "- `new_password` \u2014 yangi parol (kamida 8 ta belgi, "
        "Django validatorlari tekshiradi)\n"
        "- `new_password_confirm` \u2014 parolni tasdiqlash\n\n"
        "**Ruxsat:** Autentifikatsiya qilingan foydalanuvchilar"
    ),
    request=ChangePasswordSerializer,
    responses={
        200: DetailResponseSerializer,
        400: ErrorResponseSerializer,
    },
)
class ChangePasswordView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        user.set_password(serializer.validated_data['new_password'])
        user.save(update_fields=['password'])
        return Response(
            {"detail": "Parol muvaffaqiyatli o'zgartirildi"},
            status=status.HTTP_200_OK
        )


@extend_schema(
    tags=['Users Management'],
    summary="Barcha foydalanuvchilar ro'yxati va boshqaruvi",
    description=(
        "Faqat SUPERADMIN foydalana oladi. "
        "Foydalanuvchilarni qidirish, filtrlash "
        "va to'liq boshqarish imkonini beradi."
    ),
)
class UserViewSet(viewsets.ModelViewSet):
    """SUPERADMIN uchun barcha foydalanuvchilarni to'liq boshqarish API si"""
    serializer_class = UserSerializer
    permission_classes = [IsSuperAdmin]

    filterset_fields = ['role', 'is_active']
    search_fields = ['email', 'first_name', 'last_name', 'phone']
    ordering_fields = ['date_joined', 'email']
    ordering = ['-date_joined']

    def get_serializer_class(self):
        if self.action == 'create':
            return UserCreateSerializer
        return UserSerializer

    def get_queryset(self):
        """SUPERADMIN faol foydalanuvchilarni ko'radi"""
        if getattr(self, 'swagger_fake_view', False):
            return User.objects.none()
        return User.objects.all()

    @extend_schema(
        summary="Foydalanuvchilar ro'yxatini olish",
        description=(
            "Tizimdagi barcha foydalanuvchilar ro'yxatini "
            "sahifalab (paginated) qaytaradi.\n\n"
            "**Filtrlash imkoniyatlari:**\n"
            "- `role` — CITIZEN, SECRETARY, MANAGER, "
            "REVIEWER, SUPERADMIN bo'yicha\n"
            "- `is_active` — faol (true) yoki nofaol "
            "(false) foydalanuvchilar\n\n"
            "**Qidirish (search):**\n"
            "- `email`, `first_name`, `last_name`, `phone` "
            "maydonlari bo'yicha qidirish mumkin\n\n"
            "**Tartiblash (ordering):**\n"
            "- `date_joined` — ro'yxatdan o'tgan sanasi\n"
            "- `email` — email bo'yicha alifbo tartibi\n\n"
            "**Ruxsat:** Faqat SUPERADMIN"
        ),
        responses={200: UserSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        summary="Bitta foydalanuvchi ma'lumotlarini olish",
        description=(
            "ID bo'yicha bitta foydalanuvchining to'liq "
            "ma'lumotlarini qaytaradi: email, ism-familiya, "
            "rol, telefon, faollik holati va ro'yxatdan "
            "o'tgan sanasi.\n\n"
            "**Ruxsat:** Faqat SUPERADMIN"
        ),
        responses={
            200: UserSerializer,
            404: ErrorResponseSerializer,
        },
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        summary="Yangi foydalanuvchi yaratish",
        description=(
            "Admin tomonidan yangi foydalanuvchi hisobini "
            "yaratish. Istalgan rol bilan yaratish mumkin: "
            "CITIZEN, SECRETARY, MANAGER, REVIEWER, "
            "SUPERADMIN.\n\n"
            "**Muhim:** Ro'yxatdan o'tish (Register) API "
            "dan farqi shundaki, bu yerda admin istalgan "
            "rolda foydalanuvchi yarata oladi va parolni "
            "o'zi belgilaydi. Register orqali faqat "
            "CITIZEN roli bilan yaratiladi.\n\n"
            "**Ruxsat:** Faqat SUPERADMIN"
        ),
        request=UserCreateSerializer,
        responses={
            201: UserSerializer,
            400: ErrorResponseSerializer,
        },
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @extend_schema(
        summary="Foydalanuvchi ma'lumotlarini to'liq yangilash",
        description=(
            "ID bo'yicha foydalanuvchining barcha "
            "maydonlarini bir vaqtda yangilaydi (PUT). "
            "Barcha majburiy maydonlar yuborilishi kerak.\n\n"
            "**O'zgartirish mumkin bo'lgan maydonlar:**\n"
            "- `email` — yangi email manzil\n"
            "- `first_name`, `last_name` — ism va familiya\n"
            "- `phone` — telefon raqam "
            "(+998XXXXXXXXX formatda)\n\n"
            "**O'zgartirib bo'lmaydigan maydonlar:** "
            "`id`, `role`, `date_joined`, `is_active` — "
            "bu maydonlar faqat o'qish uchun.\n\n"
            "**Ruxsat:** Faqat SUPERADMIN"
        ),
        responses={
            200: UserSerializer,
            400: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @extend_schema(
        summary="Foydalanuvchi ma'lumotlarini qisman yangilash",
        description=(
            "ID bo'yicha foydalanuvchining faqat "
            "yuborilgan maydonlarini yangilaydi (PATCH). "
            "Faqat o'zgartirmoqchi bo'lgan maydonlarni "
            "yuboring, qolganlarini yuborish shart emas.\n\n"
            "**Misol:** Faqat telefon raqamni yangilash "
            "uchun `{\"phone\": \"+998901234567\"}` "
            "yuborish kifoya.\n\n"
            "**Ruxsat:** Faqat SUPERADMIN"
        ),
        responses={
            200: UserSerializer,
            400: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @extend_schema(
        summary="Foydalanuvchini o'chirish (Soft Delete)",
        description=(
            "ID bo'yicha foydalanuvchini tizimdan o'chiradi. "
            "Bu soft delete — foydalanuvchi bazadan "
            "o'chirilmaydi, faqat `is_active=false` va "
            "`deleted_at` belgilanadi.\n\n"
            "O'chirilgan foydalanuvchi tizimga kira "
            "olmaydi, lekin ma'lumotlari saqlanib qoladi. "
            "Keyinchalik admin qayta tiklashi mumkin.\n\n"
            "**Ruxsat:** Faqat SUPERADMIN"
        ),
        responses={
            204: None,
            404: ErrorResponseSerializer,
        },
    )
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)

    def perform_destroy(self, instance):
        """Soft delete — bazadan o'chirmaydi"""
        instance.delete()

    # -------- CHANGE ROLE --------
    @extend_schema(
        summary="Foydalanuvchi rolini o'zgartirish",
        description=(
            "SUPERADMIN foydalanuvchiga yangi rol beradi.\n\n"
            "**Mavjud rollar:**\n"
            "- `CITIZEN` — Fuqaro (hujjat yuboradi)\n"
            "- `SECRETARY` — Kotib (tahrizchi biriktiradi)\n"
            "- `MANAGER` — Rais (tahrizchi biriktiradi, "
            "yakuniy qaror qabul qiladi)\n"
            "- `REVIEWER` — Tahrizchi (hujjatlarni ko'rib "
            "chiqadi va xulosa beradi)\n"
            "- `SUPERADMIN` — Admin (barcha huquqlar)\n\n"
            "**So'rov tanasi:**\n"
            "```json\n"
            "{\"role\": \"REVIEWER\"}\n"
            "```\n\n"
            "**Qoidalar:**\n"
            "- O'zingizning rolingizni o'zgartira olmaysiz\n"
            "- Faqat ro'yxatdagi rollardan birini tanlash "
            "mumkin\n\n"
            "**Ruxsat:** Faqat SUPERADMIN"
        ),
        request=ChangeRoleSerializer,
        responses={
            200: UserSerializer,
            400: ErrorResponseSerializer,
        },
    )
    @decorators.action(
        detail=True,
        methods=['post'],
        url_path='change-role',
    )
    def change_role(self, request, pk=None):
        user = self.get_object()

        if user == request.user:
            return Response(
                {"error": "O'z rolingizni o'zgartira olmaysiz"},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = ChangeRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        new_role = serializer.validated_data['role']
        old_role = user.get_role_display()

        user.role = new_role
        # MANAGER/SUPERADMIN uchun is_staff ham kerak
        user.is_staff = new_role in ('MANAGER', 'SUPERADMIN')
        user.save(update_fields=['role', 'is_staff', 'updated_at'])

        logger.info(
            "User #%s role changed: %s -> %s by %s",
            user.id, old_role, user.get_role_display(),
            request.user.email
        )
        return Response(UserSerializer(user).data)

    # -------- ACTIVATE --------
    @extend_schema(
        summary="Foydalanuvchini faollashtirish",
        description=(
            "O'chirilgan (deaktiv) foydalanuvchini qayta "
            "faollashtiradi.\n\n"
            "`is_active=true` va `deleted_at=null` "
            "qilib belgilanadi. Foydalanuvchi qayta tizimga "
            "kira oladi.\n\n"
            "**Ruxsat:** Faqat SUPERADMIN"
        ),
        request=None,
        responses={
            200: UserSerializer,
            400: ErrorResponseSerializer,
        },
    )
    @decorators.action(
        detail=True,
        methods=['post'],
    )
    def activate(self, request, pk=None):
        user = self.get_object()
        if user.is_active and user.deleted_at is None:
            return Response(
                {"error": "Foydalanuvchi allaqachon faol"},
                status=status.HTTP_400_BAD_REQUEST
            )

        user.is_active = True
        user.deleted_at = None
        user.save(update_fields=['is_active', 'deleted_at', 'updated_at'])

        logger.info(
            "User #%s activated by %s", user.id, request.user.email
        )
        return Response(UserSerializer(user).data)

    # -------- DEACTIVATE --------
    @extend_schema(
        summary="Foydalanuvchini bloklash (deaktiv qilish)",
        description=(
            "Foydalanuvchini vaqtincha bloklaydi (o'chirmaydi).\n\n"
            "`is_active=false` qilib belgilanadi. "
            "Foydalanuvchi tizimga kira olmaydi, lekin "
            "ma'lumotlari saqlanib qoladi.\n\n"
            "Qayta faollashtirish uchun `activate` "
            "endpointini ishlating.\n\n"
            "**Ruxsat:** Faqat SUPERADMIN"
        ),
        request=None,
        responses={
            200: UserSerializer,
            400: ErrorResponseSerializer,
        },
    )
    @decorators.action(
        detail=True,
        methods=['post'],
    )
    def deactivate(self, request, pk=None):
        user = self.get_object()

        if user == request.user:
            return Response(
                {"error": "O'zingizni deaktiv qila olmaysiz"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not user.is_active:
            return Response(
                {"error": "Foydalanuvchi allaqachon deaktiv"},
                status=status.HTTP_400_BAD_REQUEST
            )

        user.is_active = False
        user.save(update_fields=['is_active', 'updated_at'])

        logger.info(
            "User #%s deactivated by %s", user.id, request.user.email
        )
        return Response(UserSerializer(user).data)

    # -------- RESET PASSWORD --------
    @extend_schema(
        summary="Foydalanuvchi parolini tiklash (Admin)",
        description=(
            "SUPERADMIN foydalanuvchi parolini yangisiga tiklaydi.\n\n"
            "**So'rov tanasi:**\n"
            "```json\n"
            "{\n"
            "  \"new_password\": \"new_secure_password\",\n"
            "  \"new_password_confirm\": \"new_secure_password\"\n"
            "}\n"
            "```\n\n"
            "**Ruxsat:** Faqat SUPERADMIN"
        ),
        request=AdminResetPasswordSerializer,
        responses={
            200: DetailResponseSerializer,
            400: ErrorResponseSerializer,
        },
    )
    @decorators.action(
        detail=True,
        methods=['post'],
        url_path='reset-password',
    )
    def reset_password(self, request, pk=None):
        user = self.get_object()
        serializer = AdminResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user.set_password(serializer.validated_data['new_password'])
        user.save(update_fields=['password', 'updated_at'])

        logger.info(
            "User #%s password reset by %s", user.id, request.user.email
        )
        return Response({"detail": "Foydalanuvchi paroli muvaffaqiyatli tiklandi"})
