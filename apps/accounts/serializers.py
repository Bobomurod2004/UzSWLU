# flake8: noqa
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """Foydalanuvchi to'liq ma'lumotlari"""
    full_name = serializers.CharField(source='get_full_name', read_only=True)

    class Meta:
        model = User
        fields = [
            'id', 'email', 'full_name', 'first_name', 'last_name',
            'role', 'phone', 'is_active', 'date_joined'
        ]
        read_only_fields = ['id', 'role', 'date_joined', 'is_active']


class ProfileUpdateSerializer(serializers.ModelSerializer):
    """Profilni yangilash — faqat ruxsat etilgan maydonlar"""
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'phone']


class RegisterSerializer(serializers.ModelSerializer):
    """
    Yangi fuqaro ro'yxatdan o'tishi.
    Muvaffaqiyatli bo'lsa, JWT tokenlarni qaytaradi.
    """
    password = serializers.CharField(
        write_only=True,
        min_length=8,
        validators=[validate_password],
        help_text="Kamida 8 ta belgi, kuchli parol"
    )
    password_confirm = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['email', 'password', 'password_confirm', 'first_name', 'last_name', 'phone']

    def validate_email(self, value):
        email = value.lower().strip()
        if User.all_objects.filter(email=email).exists():
            raise serializers.ValidationError("Bu email manzil allaqachon ro'yxatdan o'tgan")
        return email

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({"password_confirm": "Parollar mos kelmadi"})
        return attrs

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        user = User.objects.create_user(**validated_data)
        return user


class ChangePasswordSerializer(serializers.Serializer):
    """Parolni o'zgartirish (eski parolsiz)"""
    new_password = serializers.CharField(
        required=True,
        min_length=8,
        validators=[validate_password]
    )
    new_password_confirm = serializers.CharField(required=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError({"new_password_confirm": "Yangi parollar mos kelmadi"})
        return attrs


class AdminResetPasswordSerializer(serializers.Serializer):
    """Admin tomonidan parolni tiklash"""
    new_password = serializers.CharField(
        required=True,
        min_length=8,
        validators=[validate_password]
    )
    new_password_confirm = serializers.CharField(required=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError({"new_password_confirm": "Parollar mos kelmadi"})
        return attrs


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Login — JWT tokenlar + foydalanuvchi ma'lumotlarini qaytaradi.
    Soft-delete qilingan foydalanuvchilarni rad etadi.
    """
    def validate(self, attrs):
        # Email ni normalize qilish
        attrs['email'] = attrs.get('email', '').lower().strip()
        data = super().validate(attrs)

        # Soft-delete tekshiruvi
        if self.user.deleted_at is not None:
            raise serializers.ValidationError("Bu hisob o'chirilgan. Admin bilan bog'laning.")

        # Token javobiga user ma'lumotlarini qo'shish
        data['user'] = UserSerializer(self.user, context=self.context).data
        return data


class GoogleLoginSerializer(serializers.Serializer):
    """Google autentifikatsiyasi uchun access_token serializatori"""
    access_token = serializers.CharField(
        required=True,
        help_text="Google tomonidan taqdim etilgan access_token"
    )


class OneIDLoginSerializer(serializers.Serializer):
    """OneID autentifikatsiyasi uchun vaqtinchalik code serializatori"""
    code = serializers.CharField(
        required=True,
        help_text="OneID (OIDC) dan olingan vaqtinchalik 'code' qiymati"
    )


# ──────────────────────────────────────────────
# Swagger uchun Response Serializerlar
# ──────────────────────────────────────────────

class AuthTokenResponseSerializer(serializers.Serializer):
    """JWT token javob formati — login, register, social auth uchun"""
    user = UserSerializer(read_only=True)
    access = serializers.CharField(
        read_only=True,
        help_text="JWT access token (Bearer)"
    )
    refresh = serializers.CharField(
        read_only=True,
        help_text="JWT refresh token"
    )


class LogoutRequestSerializer(serializers.Serializer):
    """Logout uchun request body"""
    refresh = serializers.CharField(
        required=True,
        help_text="Bekor qilinadigan refresh token"
    )


class DetailResponseSerializer(serializers.Serializer):
    """Umumiy xabar javob formati"""
    detail = serializers.CharField(
        read_only=True,
        help_text="Javob xabari"
    )


class ErrorResponseSerializer(serializers.Serializer):
    """Xatolik javob formati"""
    error = serializers.CharField(
        read_only=True,
        help_text="Xatolik xabari"
    )


class ChangeRoleSerializer(serializers.Serializer):
    """Foydalanuvchi rolini o'zgartirish"""
    role = serializers.ChoiceField(
        choices=User.Role.choices,
        help_text=(
            "Yangi rol: CITIZEN (Fuqaro), SECRETARY (Kotib), "
            "MANAGER (Rais), REVIEWER (Tahrizchi), SUPERADMIN (Admin)"
        ),
    )


class UserCreateSerializer(serializers.ModelSerializer):
    """
    Admin tomonidan yangi foydalanuvchi yaratish uchun serializator.
    Barcha rollar va xeshlanadigan parolni qo'llab-quvvatlaydi.
    """
    password = serializers.CharField(
        write_only=True,
        min_length=8,
        validators=[validate_password],
        help_text="Foydalanuvchi paroli (kamida 8 ta belgi)"
    )

    class Meta:
        model = User
        fields = [
            'email', 'password', 'first_name', 'last_name',
            'role', 'phone', 'external_id', 'is_active', 'is_staff'
        ]

    def validate_email(self, value):
        email = value.lower().strip()
        if User.all_objects.filter(email=email).exists():
            raise serializers.ValidationError("Bu email allaqachon ro'yxatdan o'tgan")
        return email

    def validate_external_id(self, value):
        if value:
            if User.all_objects.filter(external_id=value).exists():
                raise serializers.ValidationError("Bu external_id allaqachon mavjud")
        return value

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user
