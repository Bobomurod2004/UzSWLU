# flake8: noqa
import logging
import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.exceptions import AuthenticationFailed

User = get_user_model()
logger = logging.getLogger('apps.accounts')

class GoogleAuthService:
    TIMEOUT = 10  # sekund

    @staticmethod
    def verify_token(token: str) -> dict:
        """Google tokenini tekshirish va user ma'lumotlarini qaytarish"""
        response = requests.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            params={'access_token': token},
            timeout=GoogleAuthService.TIMEOUT,
        )
        if not response.ok:
            raise AuthenticationFailed("Google tokeni yaroqsiz yoki muddati o'tgan")
        
        return response.json()

    @classmethod
    def get_or_create_user(cls, token: str):
        user_data = cls.verify_token(token)
        email = user_data.get('email')
        external_id = user_data.get('sub')
        full_name = user_data.get('name', '')
        
        if not email:
            logger.warning("Google auth: email manzili mavjud emas (sub=%s)", external_id)
            raise AuthenticationFailed("Google hisobida email manzili mavjud emas")
        if not user_data.get('email_verified', False):
            logger.warning("Google auth: tasdiqlanmagan email=%s", email)
            raise AuthenticationFailed("Google email manzili tasdiqlanmagan")

        user, created = User.objects.get_or_create(
            email=email.lower(),
            defaults={
                'first_name': user_data.get('given_name', ''),
                'last_name': user_data.get('family_name', ''),
                'external_id': external_id,
                'role': User.Role.CITIZEN,
                'is_active': True
            }
        )

        if created:
            logger.info("Google auth: yangi user yaratildi email=%s", email)
        else:
            logger.info("Google auth: mavjud user kirdi email=%s", email)

        # Existing user uchun ham profil ma'lumotlarini Google bilan sinxron saqlaymiz.
        if not created:
            changed = False
            given_name = user_data.get('given_name', '')
            family_name = user_data.get('family_name', '')
            if given_name and user.first_name != given_name:
                user.first_name = given_name
                changed = True
            if family_name and user.last_name != family_name:
                user.last_name = family_name
                changed = True
            if external_id and not user.external_id:
                user.external_id = external_id
                changed = True
            if changed:
                user.save(update_fields=['first_name', 'last_name', 'external_id', 'updated_at'])

        return user

class OneIDService:
    TIMEOUT = 10  # sekund

    @staticmethod
    def get_user_data(code: str) -> dict:
        """OneID code orqali foydalanuvchi ma'lumotlarini olish"""
        # 1. Token olish
        token_response = requests.post(
            f"{settings.ONEID_BASE_URL}/api/v1/user/access_token",
            data={
                'grant_type': 'one_authorization_code',
                'client_id': settings.ONEID_CLIENT_ID,
                'client_secret': settings.ONEID_CLIENT_SECRET,
                'code': code,
                'redirect_uri': settings.ONEID_REDIRECT_URI,
            },
            timeout=OneIDService.TIMEOUT,
        )
        if not token_response.ok:
            raise AuthenticationFailed("OneID kodini tekshirishda xatolik yuz berdi")
        
        access_token = token_response.json().get('access_token')

        # 2. User info olish
        user_info_response = requests.get(
            f"{settings.ONEID_BASE_URL}/api/v1/user/info",
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=OneIDService.TIMEOUT,
        )
        if not user_info_response.ok:
            raise AuthenticationFailed("OneID foydalanuvchi ma'lumotlarini olishda xatolik")
            
        return user_info_response.json()

    @classmethod
    def get_or_create_user(cls, code: str):
        data = cls.get_user_data(code)
        # OneID odatda 'pin' yoki 'user_id' qaytaradi
        external_id = data.get('pin') or data.get('user_id')
        if not external_id:
            raise AuthenticationFailed("OneID foydalanuvchi identifikatori topilmadi")
        email = (data.get('email') or f"oneid_{external_id}@oneid.local").lower()
        
        user, created = User.objects.get_or_create(
            external_id=external_id,
            defaults={
                'email': email,
                'first_name': data.get('first_name', ''),
                'last_name': data.get('sur_name', ''),
                'phone': data.get('mob_phone_no', ''),
                'role': User.Role.CITIZEN,
                'is_active': True
            }
        )

        if not created:
            changed = False
            if not user.email:
                user.email = email
                changed = True
            if data.get('first_name', '') and user.first_name != data.get('first_name', ''):
                user.first_name = data.get('first_name', '')
                changed = True
            if data.get('sur_name', '') and user.last_name != data.get('sur_name', ''):
                user.last_name = data.get('sur_name', '')
                changed = True
            if data.get('mob_phone_no', '') and user.phone != data.get('mob_phone_no', ''):
                user.phone = data.get('mob_phone_no', '')
                changed = True
            if changed:
                user.save(update_fields=['email', 'first_name', 'last_name', 'phone', 'updated_at'])
        return user
