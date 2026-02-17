from rest_framework import serializers
from .models import Category, Document, DocumentAssignment, Review, DocumentHistory
from django.contrib.auth import get_user_model

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


class ReviewSerializer(serializers.ModelSerializer):
    reviewer = UserShortSerializer(read_only=True)
    score = serializers.IntegerField(
        required=False, allow_null=True,
        min_value=0, max_value=100,
        help_text="Ball (0 dan 100 gacha)"
    )

    class Meta:
        model = Review
        fields = ['id', 'document', 'reviewer', 'review_file', 'score', 'comment', 'created_at']
        read_only_fields = ['reviewer', 'document']


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


class DocumentSerializer(serializers.ModelSerializer):
    owner = UserShortSerializer(read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    reviews = ReviewSerializer(many=True, read_only=True)
    assignments = DocumentAssignmentSerializer(many=True, read_only=True)
    history = DocumentHistorySerializer(many=True, read_only=True)

    class Meta:
        model = Document
        fields = [
            'id', 'title', 'file', 'category', 'category_name',
            'owner', 'status', 'assignments', 'reviews',
            'history', 'created_at'
        ]
        read_only_fields = ['owner', 'status']


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
            raise serializers.ValidationError("Kamida bitta tahrizchi tanlanishi kerak.")

        errors = []
        for user in value:
            if user.role != 'REVIEWER':
                errors.append(f"{user.email} — REVIEWER rolida emas.")
            elif not user.is_active:
                errors.append(f"{user.email} — faol emas.")
        if errors:
            raise serializers.ValidationError(errors)
        return value
