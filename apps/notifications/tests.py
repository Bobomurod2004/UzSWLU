# flake8: noqa
"""
Notifications app uchun testlar.
Bildirishnoma yaratilishi, API endpointlari va workflow integratsiyasi.
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from apps.documents.models import Category, Document, DocumentAssignment
from apps.notifications.models import Notification
from django.core.files.uploadedfile import SimpleUploadedFile

User = get_user_model()


def make_pdf(name="test.pdf", size=100):
    """Haqiqiy PDF header bilan test fayl yaratish"""
    content = b'%PDF-1.4 ' + b'x' * max(0, size - 9)
    return SimpleUploadedFile(name, content, content_type="application/pdf")


class NotificationModelTest(TestCase):
    """Notification modeli testlari"""

    def setUp(self):
        self.citizen = User.objects.create_user(
            email='citizen@test.com', password='TestPass123!', role='CITIZEN'
        )
        self.category = Category.objects.create(name="Test Soha")
        self.document = Document.objects.create(
            title="Test Hujjat", owner=self.citizen,
            category=self.category, status=Document.Status.NEW,
            file=make_pdf()
        )

    def test_notification_creation(self):
        """Notification yaratilishi va maydnlari to'g'ri ishlashi"""
        notification = Notification.objects.create(
            recipient=self.citizen,
            document=self.document,
            notification_type=Notification.Type.DOCUMENT_SUBMITTED,
            message="Test xabar",
        )
        self.assertEqual(notification.recipient, self.citizen)
        self.assertEqual(notification.document, self.document)
        self.assertFalse(notification.is_read)
        self.assertEqual(notification.notification_type, Notification.Type.DOCUMENT_SUBMITTED)

    def test_unread_by_default(self):
        """Yangi notification default bo'yicha o'qilmagan"""
        notification = Notification.objects.create(
            recipient=self.citizen,
            document=self.document,
            notification_type=Notification.Type.NEW_DOCUMENT,
            message="Yangi hujjat",
        )
        self.assertFalse(notification.is_read)


class NotificationAPITest(TestCase):
    """Notification API endpointlari testlari"""

    def setUp(self):
        self.client = APIClient()
        self.citizen = User.objects.create_user(
            email='citizen@test.com', password='TestPass123!', role='CITIZEN'
        )
        self.citizen2 = User.objects.create_user(
            email='citizen2@test.com', password='TestPass123!', role='CITIZEN'
        )
        self.category = Category.objects.create(name="Test Soha")
        self.document = Document.objects.create(
            title="Test Hujjat", owner=self.citizen,
            category=self.category, status=Document.Status.NEW,
            file=make_pdf()
        )
        # 3 ta notification yaratish
        for i in range(3):
            Notification.objects.create(
                recipient=self.citizen,
                document=self.document,
                notification_type=Notification.Type.DOCUMENT_SUBMITTED,
                message=f"Test xabar {i+1}",
            )
        # Boshqa foydalanuvchiga 1 ta notification
        Notification.objects.create(
            recipient=self.citizen2,
            document=self.document,
            notification_type=Notification.Type.NEW_DOCUMENT,
            message="Boshqa foydalanuvchi uchun",
        )

    def test_list_own_notifications(self):
        """Foydalanuvchi faqat o'z bildirishnomalarini ko'radi"""
        self.client.force_authenticate(user=self.citizen)
        resp = self.client.get('/api/notifications/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 3)

    def test_cannot_see_other_user_notifications(self):
        """Boshqa foydalanuvchining bildirishnomalarini ko'ra olmaydi"""
        self.client.force_authenticate(user=self.citizen)
        resp = self.client.get('/api/notifications/')
        # citizen faqat o'z 3 tasini ko'radi, citizen2 ning 1 tasini emas
        self.assertEqual(resp.data['count'], 3)

    def test_unread_count(self):
        """O'qilmagan bildirishnomalar soni to'g'ri qaytishi"""
        self.client.force_authenticate(user=self.citizen)
        resp = self.client.get('/api/notifications/unread_count/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['unread_count'], 3)

    def test_mark_read(self):
        """Bildirishnomani o'qilgan deb belgilash"""
        notification = Notification.objects.filter(recipient=self.citizen).first()
        self.client.force_authenticate(user=self.citizen)
        resp = self.client.post(f'/api/notifications/{notification.id}/mark_read/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

        # Unread count 2 ga tushishi kerak
        resp = self.client.get('/api/notifications/unread_count/')
        self.assertEqual(resp.data['unread_count'], 2)

    def test_mark_all_read(self):
        """Barcha bildirishnomalarni o'qilgan deb belgilash"""
        self.client.force_authenticate(user=self.citizen)
        resp = self.client.post('/api/notifications/mark_all_read/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['unread_count'], 0)

        # Barcha o'qilgan
        unread = Notification.objects.filter(
            recipient=self.citizen, is_read=False
        ).count()
        self.assertEqual(unread, 0)

        # Boshqa foydalanuvchinikiga ta'sir qilmagan
        other_unread = Notification.objects.filter(
            recipient=self.citizen2, is_read=False
        ).count()
        self.assertEqual(other_unread, 1)

    def test_filter_by_is_read(self):
        """is_read bo'yicha filtrlash"""
        # 1 tasini o'qilgan qilish
        n = Notification.objects.filter(recipient=self.citizen).first()
        n.is_read = True
        n.save()

        self.client.force_authenticate(user=self.citizen)
        resp = self.client.get('/api/notifications/?is_read=false')
        self.assertEqual(resp.data['count'], 2)

        resp = self.client.get('/api/notifications/?is_read=true')
        self.assertEqual(resp.data['count'], 1)


class NotificationWorkflowIntegrationTest(TestCase):
    """Hujjat workflow bilan notification integratsiyasi testlari"""

    def setUp(self):
        self.client = APIClient()
        self.citizen = User.objects.create_user(
            email='citizen@test.com', password='TestPass123!', role='CITIZEN'
        )
        self.secretary = User.objects.create_user(
            email='secretary@test.com', password='TestPass123!', role='SECRETARY'
        )
        self.manager = User.objects.create_user(
            email='manager@test.com', password='TestPass123!', role='MANAGER'
        )
        self.reviewer = User.objects.create_user(
            email='reviewer@test.com', password='TestPass123!', role='REVIEWER'
        )
        self.category = Category.objects.create(name="Test Soha")

    def test_document_creation_notifications(self):
        """Hujjat yaratilganda fuqaro + staff ga notification kelishi"""
        self.client.force_authenticate(user=self.citizen)
        resp = self.client.post('/api/documents/', {
            'title': 'Notification Test',
            'file': make_pdf(),
            'category': self.category.id
        }, format='multipart')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        # Fuqaroga DOCUMENT_SUBMITTED notification kelgan
        citizen_notifs = Notification.objects.filter(
            recipient=self.citizen,
            notification_type=Notification.Type.DOCUMENT_SUBMITTED,
        )
        self.assertEqual(citizen_notifs.count(), 1)
        self.assertIn('muvaffaqiyatli yuborildi', citizen_notifs.first().message)

        # Secretary va Manager ga NEW_DOCUMENT notification kelgan
        staff_notifs = Notification.objects.filter(
            notification_type=Notification.Type.NEW_DOCUMENT,
        )
        self.assertEqual(staff_notifs.count(), 2)  # secretary + manager

    def test_assign_reviewer_notification(self):
        """Tahrizchi biriktirilganda unga notification kelishi"""
        # Hujjat yaratish
        self.client.force_authenticate(user=self.citizen)
        resp = self.client.post('/api/documents/', {
            'title': 'Assign Test',
            'file': make_pdf(),
            'category': self.category.id
        }, format='multipart')
        doc_id = resp.data['id']

        # Tahrizchi biriktirish
        self.client.force_authenticate(user=self.secretary)
        self.client.post(f'/api/documents/{doc_id}/assign_reviewer/', {
            'reviewers': [self.reviewer.id]
        })

        # Reviewer ga REVIEWER_ASSIGNED notification kelgan
        reviewer_notifs = Notification.objects.filter(
            recipient=self.reviewer,
            notification_type=Notification.Type.REVIEWER_ASSIGNED,
        )
        self.assertEqual(reviewer_notifs.count(), 1)
        self.assertIn('biriktirildi', reviewer_notifs.first().message)

    def test_full_workflow_notifications(self):
        """To'liq workflow davomida barcha notificationlar kelishi"""
        # 1. Hujjat yaratish
        self.client.force_authenticate(user=self.citizen)
        resp = self.client.post('/api/documents/', {
            'title': 'Full Workflow Test',
            'file': make_pdf(),
            'category': self.category.id
        }, format='multipart')
        doc_id = resp.data['id']

        # 2. Tahrizchi biriktirish
        self.client.force_authenticate(user=self.secretary)
        self.client.post(f'/api/documents/{doc_id}/assign_reviewer/', {
            'reviewers': [self.reviewer.id]
        })

        # 3. Tahriz boshlash
        self.client.force_authenticate(user=self.reviewer)
        self.client.post(f'/api/documents/{doc_id}/start_review/')

        # Staff ga REVIEW_STARTED notification kelgan
        start_notifs = Notification.objects.filter(
            notification_type=Notification.Type.REVIEW_STARTED,
        )
        self.assertEqual(start_notifs.count(), 2)  # secretary + manager

        # 4. Tahriz yuklash
        self.client.post(f'/api/documents/{doc_id}/submit_review/', {
            'review_file': make_pdf("review.pdf"),
            'score': 85,
            'comment': 'Yaxshi'
        }, format='multipart')

        # Staff ga REVIEW_SUBMITTED notification kelgan
        submit_notifs = Notification.objects.filter(
            notification_type=Notification.Type.REVIEW_SUBMITTED,
        )
        self.assertEqual(submit_notifs.count(), 2)

        # 5. Manager tasdiqlaydi
        self.client.force_authenticate(user=self.manager)
        self.client.post(f'/api/documents/{doc_id}/finalize/', {
            'decision': 'APPROVE'
        })

        # Fuqaroga + Staff ga DOCUMENT_APPROVED notification kelgan
        approve_notifs = Notification.objects.filter(
            notification_type=Notification.Type.DOCUMENT_APPROVED,
        )
        self.assertGreaterEqual(approve_notifs.count(), 3)  # citizen + secretary + manager

        # 6. Secretary fuqaroga yuboradi
        self.client.force_authenticate(user=self.secretary)
        self.client.post(f'/api/documents/{doc_id}/send_to_citizen/')

        # Fuqaroga DOCUMENT_DISPATCHED notification kelgan
        dispatch_notifs = Notification.objects.filter(
            recipient=self.citizen,
            notification_type=Notification.Type.DOCUMENT_DISPATCHED,
        )
        self.assertEqual(dispatch_notifs.count(), 1)
        self.assertIn('yuborildi', dispatch_notifs.first().message)
