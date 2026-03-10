# flake8: noqa
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

User = get_user_model()


class AccountsTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.superadmin = User.objects.create_superuser(
            email='admin@example.com', password='password123'
        )
        self.citizen = User.objects.create_user(
            email='citizen@example.com', password='password123', role='CITIZEN'
        )

    def test_register_citizen(self):
        """Ro'yxatdan o'tish — token qaytarilishi"""
        response = self.client.post('/api/accounts/register/', {
            'email': 'newuser@example.com',
            'password': 'StrongPass123!',
            'password_confirm': 'StrongPass123!',
            'first_name': 'New',
            'last_name': 'User',
            'phone': '+998901234567'
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertIn('user', response.data)
        self.assertTrue(User.objects.filter(email='newuser@example.com').exists())

    def test_register_duplicate_email(self):
        """Takroriy email bilan ro'yxatdan o'tish mumkin emas"""
        response = self.client.post('/api/accounts/register/', {
            'email': 'citizen@example.com',
            'password': 'StrongPass123!',
            'password_confirm': 'StrongPass123!',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_weak_password(self):
        """Zaif parol bilan ro'yxatdan o'tish mumkin emas"""
        response = self.client.post('/api/accounts/register/', {
            'email': 'weak@example.com',
            'password': '123',
            'password_confirm': '123',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_password_mismatch(self):
        """Mos kelmaydigan parollar rad etiladi"""
        response = self.client.post('/api/accounts/register/', {
            'email': 'mismatch@example.com',
            'password': 'StrongPass123!',
            'password_confirm': 'DifferentPass456!',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_jwt(self):
        """JWT login — access va refresh tokenlar qaytarilishi"""
        response = self.client.post('/api/login/', {
            'email': 'citizen@example.com',
            'password': 'password123'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertIn('user', response.data)  # Custom: user ma'lumotlari ham qaytadi

    def test_login_wrong_password(self):
        """Noto'g'ri parol bilan kirib bo'lmaydi"""
        response = self.client.post('/api/login/', {
            'email': 'citizen@example.com',
            'password': 'wrongpassword'
        })
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout(self):
        """Logout — refresh token blacklistga tushadi"""
        # Login oldin
        login = self.client.post('/api/login/', {
            'email': 'citizen@example.com',
            'password': 'password123'
        })
        refresh = login.data['refresh']
        access = login.data['access']

        # Logout
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        response = self.client.post('/api/accounts/logout/', {'refresh': refresh})
        self.assertEqual(response.status_code, status.HTTP_205_RESET_CONTENT)

        # Eski refresh token bilan yangilab bo'lmaydi
        response = self.client.post('/api/token-refresh/', {'refresh': refresh})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_without_token(self):
        """Logout refresh token siz — xato"""
        self.client.force_authenticate(user=self.citizen)
        response = self.client.post('/api/accounts/logout/', {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_profile_get(self):
        """Profil olish"""
        self.client.force_authenticate(user=self.citizen)
        response = self.client.get('/api/accounts/profile/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['email'], 'citizen@example.com')

    def test_profile_update(self):
        """Profil yangilash"""
        self.client.force_authenticate(user=self.citizen)
        response = self.client.patch('/api/accounts/profile/', {
            'first_name': 'Updated',
            'last_name': 'Name'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['first_name'], 'Updated')

    def test_profile_unauthenticated(self):
        """Autentifikatsiyasiz profilga kirib bo'lmaydi"""
        response = self.client.get('/api/accounts/profile/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_change_password(self):
        """Parolni o'zgartirish"""
        self.client.force_authenticate(user=self.citizen)
        response = self.client.post('/api/accounts/profile/change-password/', {
            'old_password': 'password123',
            'new_password': 'NewStrong123!',
            'new_password_confirm': 'NewStrong123!'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.citizen.refresh_from_db()
        self.assertTrue(self.citizen.check_password('NewStrong123!'))

    def test_superadmin_user_list(self):
        """SUPERADMIN barcha foydalanuvchilarni ko'radi"""
        self.client.force_authenticate(user=self.superadmin)
        response = self.client.get('/api/accounts/users/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_citizen_user_list_forbidden(self):
        """Oddiy foydalanuvchi boshqa userlarni ko'ra olmaydi"""
        self.client.force_authenticate(user=self.citizen)
        response = self.client.get('/api/accounts/users/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_soft_delete_user(self):
        """SUPERADMIN user ni soft-delete qiladi"""
        self.client.force_authenticate(user=self.superadmin)
        response = self.client.delete(f'/api/accounts/users/{self.citizen.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # User bazada bor, lekin o'chirilgan deb belgilangan
        self.citizen.refresh_from_db()
        self.assertIsNotNone(self.citizen.deleted_at)
        self.assertFalse(self.citizen.is_active)

        # Default manager orqali ko'rinmaydi
        self.assertFalse(User.objects.filter(id=self.citizen.id).exists())
        # all_objects orqali ko'rinadi
        self.assertTrue(User.all_objects.filter(id=self.citizen.id).exists())

    def test_token_refresh(self):
        """Token refresh ishlashini tekshirish"""
        login = self.client.post('/api/login/', {
            'email': 'citizen@example.com',
            'password': 'password123'
        })
        refresh = login.data['refresh']

        response = self.client.post('/api/token-refresh/', {'refresh': refresh})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)


class ReviewerListTest(TestCase):
    """Tahrizchilar ro'yxati endpointi testlari"""

    def setUp(self):
        self.client = APIClient()
        self.secretary = User.objects.create_user(
            email='secretary@example.com', password='password123', role='SECRETARY'
        )
        self.manager = User.objects.create_user(
            email='manager@example.com', password='password123', role='MANAGER'
        )
        self.citizen = User.objects.create_user(
            email='citizen@example.com', password='password123', role='CITIZEN'
        )
        self.reviewer1 = User.objects.create_user(
            email='reviewer1@example.com', password='password123', role='CITIZEN'
        )
        self.reviewer2 = User.objects.create_user(
            email='reviewer2@example.com', password='password123', role='CITIZEN'
        )
        # Nofaol reviewer — ro'yxatda ko'rinmasligi kerak
        self.inactive_reviewer = User.objects.create_user(
            email='inactive@example.com', password='password123',
            role='CITIZEN', is_active=False
        )

    def test_secretary_can_list_reviewers(self):
        """Kotib tahrizchilar ro'yxatini ko'radi"""
        self.client.force_authenticate(user=self.secretary)
        response = self.client.get('/api/accounts/reviewers/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = [u['email'] for u in response.data['results']]
        self.assertIn('reviewer1@example.com', emails)
        self.assertIn('reviewer2@example.com', emails)
        self.assertNotIn('inactive@example.com', emails)

    def test_manager_can_list_reviewers(self):
        """Rais tahrizchilar ro'yxatini ko'radi"""
        self.client.force_authenticate(user=self.manager)
        response = self.client.get('/api/accounts/reviewers/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = [u['email'] for u in response.data['results']]
        self.assertIn('reviewer1@example.com', emails)

    def test_citizen_cannot_list_reviewers(self):
        """Fuqaro tahrizchilar ro'yxatiga kira olmaydi"""
        self.client.force_authenticate(user=self.citizen)
        response = self.client.get('/api/accounts/reviewers/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_cannot_list_reviewers(self):
        """Kirmasdan tahrizchilar ro'yxatiga kira olmaydi"""
        response = self.client.get('/api/accounts/reviewers/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
