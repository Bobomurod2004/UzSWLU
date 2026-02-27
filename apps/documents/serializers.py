from rest_framework import serializers
from .models import Category, Document, DocumentAssignment, Review, DocumentHistory
from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema_field, OpenApiTypes

User = get_user_model()


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'parent', 'level']


class UserShortSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source='get_full_name', read_only=True)

    class Meta:
        model = User
        fields = ['id', 'email', 'full_name', 'role']


class DocumentHistorySerializer(serializers.ModelSerializer):
    user_details = UserShortSerializer(source='user', read_only=True)

    class Meta:
        model = DocumentHistory
        fields = ['id', 'user_details', 'old_status', 'new_status', 'comment', 'created_at']

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        request = self.context.get('request')
        if request and request.user.is_authenticated and request.user.role == 'CITIZEN':
            # Tahrizchi bo'lsa anonymize qilish
            if instance.user and instance.user.role == 'REVIEWER':
                ret['user_details'] = {
                    "id": None,
                    "email": "Tahrizchi",
                    "full_name": "Maxfiy",
                    "role": "REVIEWER"
                }
            
            # Izoh ichidagi email va ma'lumotlarni tozalash
            if ret.get('comment'):
                import re
                # Email larni "tahrizchi" so'zi bilan almashtirish
                ret['comment'] = re.sub(
                    r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
                    'tahrizchi',
                    ret['comment']
                )
        return ret


class ReviewSerializer(serializers.ModelSerializer):
    reviewer = UserShortSerializer(read_only=True)
    view_url = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()
    score = serializers.IntegerField(
        required=False, allow_null=True,
        min_value=0, max_value=100,
        help_text="Ball (0 dan 100 gacha)"
    )

    class Meta:
        model = Review
        fields = [
            'id', 'document', 'reviewer', 'review_file', 
            'view_url', 'download_url', 'score', 'comment', 'created_at'
        ]
        read_only_fields = ['reviewer', 'document']

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        request = self.context.get('request')
        if request and request.user.is_authenticated and request.user.role == 'CITIZEN':
            ret['reviewer'] = {
                "id": None,
                "email": "Tahrizchi",
                "full_name": "Maxfiy",
                "role": "REVIEWER"
            }
        return ret

    @extend_schema_field(OpenApiTypes.URI)
    def get_view_url(self, obj):
        if obj.review_file:
            request = self.context.get('request')
            url = obj.review_file.url
            if request:
                # Token qo'shish
                if request.user.is_authenticated:
                    from rest_framework_simplejwt.tokens import AccessToken
                    token = str(AccessToken.for_user(request.user))
                    separator = '&' if '?' in url else '?'
                    url = f"{url}{separator}token={token}"
                
                # Full URI hosil qilish
                full_url = request.build_absolute_uri(url)
                
                # Agar port 8001 (backend) bo'lsa va hostda 81 (nginx) ko'rsatilgan bo'lsa
                # build_absolute_uri odatda to'g'ri Host headerini oladi ($http_host orqali)
                return full_url
            return url
        return None

    @extend_schema_field(OpenApiTypes.URI)
    def get_download_url(self, obj):
        if obj.review_file:
            request = self.context.get('request')
            url = f"{obj.review_file.url}?download=1"
            if request:
                # Token qo'shish
                if request.user.is_authenticated:
                    from rest_framework_simplejwt.tokens import AccessToken
                    token = str(AccessToken.for_user(request.user))
                    url = f"{url}&token={token}"
                
                # Full URI
                return request.build_absolute_uri(url)
            return url
        return None


class DocumentAssignmentSerializer(serializers.ModelSerializer):
    """Hujjat-Tahrizchi biriktirmasi"""
    reviewer_details = UserShortSerializer(source='reviewer', read_only=True)
    assigned_by_details = UserShortSerializer(source='assigned_by', read_only=True)

    class Meta:
        model = DocumentAssignment
        fields = [
            'id', 'reviewer', 'reviewer_details',
            'assigned_by', 'assigned_by_details',
            'status', 'created_at'
        ]
        read_only_fields = ['assigned_by', 'status']

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        request = self.context.get('request')
        if request and request.user.is_authenticated and request.user.role == 'CITIZEN':
            ret['reviewer'] = None
            ret['reviewer_details'] = {
                "id": None,
                "email": "Tahrizchi",
                "full_name": "Maxfiy",
                "role": "REVIEWER"
            }
        return ret


class DocumentSerializer(serializers.ModelSerializer):
    owner = UserShortSerializer(read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    view_url = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()
    reviews = ReviewSerializer(many=True, read_only=True)
    assignments = DocumentAssignmentSerializer(many=True, read_only=True)
    history = DocumentHistorySerializer(many=True, read_only=True)

    class Meta:
        model = Document
        fields = [
            'id', 'title', 'file', 'view_url', 'download_url', 
            'category', 'category_name', 'owner', 'status', 
            'assignments', 'reviews', 'history', 'created_at'
        ]
        read_only_fields = ['owner', 'status']

    @extend_schema_field(OpenApiTypes.URI)
    def get_view_url(self, obj):
        if obj.file:
            request = self.context.get('request')
            url = obj.file.url
            if request:
                # Token qo'shish
                if request.user.is_authenticated:
                    from rest_framework_simplejwt.tokens import AccessToken
                    token = str(AccessToken.for_user(request.user))
                    separator = '&' if '?' in url else '?'
                    url = f"{url}{separator}token={token}"
                
                # Full URI
                return request.build_absolute_uri(url)
            return url
        return None

    @extend_schema_field(OpenApiTypes.URI)
    def get_download_url(self, obj):
        if obj.file:
            request = self.context.get('request')
            url = f"{obj.file.url}?download=1"
            if request:
                # Token qo'shish
                if request.user.is_authenticated:
                    from rest_framework_simplejwt.tokens import AccessToken
                    token = str(AccessToken.for_user(request.user))
                    url = f"{url}&token={token}"
                
                # Full URI
                return request.build_absolute_uri(url)
            return url
        return None

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        request = self.context.get('request')
        
        # Fuqaro uchun cheklov: tasdiqlanmagan yoki rad etilmagan bo'lsa, tahrizlarni berkitish
        if request and request.user.is_authenticated and request.user.role == 'CITIZEN':
            if instance.status not in [Document.Status.APPROVED, Document.Status.REJECTED]:
                ret['reviews'] = []
                # Izoh: Assignments ham fuqaro uchun unchalik muhim emas, lekin qolsa ham zarar qilmaydi (tepish anonim bo'lishi sharti bilan)
        return ret


class DocumentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = ['id', 'title', 'file', 'category']

    def create(self, validated_data):
        validated_data['owner'] = self.context['request'].user
        validated_data['status'] = Document.Status.NEW
        return super().create(validated_data)


class DocumentAssignReviewersSerializer(serializers.Serializer):
    """Bir nechta tahrizchini biriktirish uchun serializer"""
    reviewers = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        many=True,
        help_text="Tahrizchilar ID lari ro'yxati"
    )

    def validate_reviewers(self, value):
        if not value:
            raise serializers.ValidationError(
                "Kamida bitta tahrizchi tanlanishi kerak."
            )

        errors = []
        for user in value:
            if user.role != 'REVIEWER':
                errors.append(
                    f"{user.email} — REVIEWER rolida emas."
                )
            elif not user.is_active:
                errors.append(f"{user.email} — faol emas.")
        if errors:
            raise serializers.ValidationError(errors)
        return value


# ──────────────────────────────────────────────
# Swagger uchun Response Serializerlar
# ──────────────────────────────────────────────

class DocumentStatsSerializer(serializers.Serializer):
    """Hujjatlar statistikasi javob formati"""
    total = serializers.IntegerField(
        help_text="Jami hujjatlar soni"
    )
    new = serializers.IntegerField(
        help_text="Yangi hujjatlar"
    )
    pending = serializers.IntegerField(
        help_text="Yo'naltirilgan hujjatlar"
    )
    under_review = serializers.IntegerField(
        help_text="Tahrizda bo'lgan hujjatlar"
    )
    reviewed = serializers.IntegerField(
        help_text="Tahrizlangan hujjatlar"
    )
    approved = serializers.IntegerField(
        help_text="Tasdiqlangan hujjatlar"
    )
    rejected = serializers.IntegerField(
        help_text="Qaytarilgan hujjatlar"
    )


class FinalizeRequestSerializer(serializers.Serializer):
    """Yakuniy qaror (Tasdiqlash/Rad etish) request body"""
    decision = serializers.ChoiceField(
        choices=['APPROVE', 'RE_REVIEW', 'REJECT'],
        help_text=(
            "'APPROVE' — tasdiqlash (fuqaroga yuborish), "
            "'RE_REVIEW' — tahrizchilarga qaytarish (tuzatish uchun), "
            "'REJECT' — rad etish (fuqaroga qaytarish)"
        )
    )
    comment = serializers.CharField(
        required=False,
        allow_blank=True,
        default='',
    )


class FinalizeResponseSerializer(serializers.Serializer):
    """Yakuniy qaror javob formati"""
    status = serializers.CharField(
        read_only=True,
        help_text="Hujjat holati xabari"
    )
