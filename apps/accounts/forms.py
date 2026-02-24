from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from .models import User

class CustomUserCreationForm(UserCreationForm):
    """
    Admin panelda yangi foydalanuvchi yaratish uchun forma.
    Email ni asosiy identifikator sifatida ishlatadi.
    """
    class Meta:
        model = User
        fields = ('email', 'first_name', 'last_name', 'role', 'phone', 'external_id')

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Bu email allaqachon mavjud.")
        return email

class CustomUserChangeForm(UserChangeForm):
    """
    Admin panelda foydalanuvchi ma'lumotlarini tahrirlash uchun forma.
    """
    class Meta:
        model = User
        fields = ('email', 'first_name', 'last_name', 'role', 'phone', 'external_id', 'is_active', 'is_staff', 'is_superuser')
