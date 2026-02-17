# flake8: noqa
"""
Documents app uchun testlar.
Hujjat workflow, permission, file validation, multi-reviewer va status transition tekshiruvlari.
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from apps.documents.models import Category, Document, DocumentAssignment, Review, DocumentHistory
from django.core.files.uploadedfile import SimpleUploadedFile

User = get_user_model()


def make_pdf(name="test.pdf", size=100):
    """Haqiqiy PDF header bilan test fayl yaratish"""
    content = b'%PDF-1.4 ' + b'x' * max(0, size - 9)
    return SimpleUploadedFile(name, content, content_type="application/pdf")


def make_txt(name="test.txt"):
    """PDF bo'lmagan test fayl"""
    return SimpleUploadedFile(name, b"plain text", content_type="text/plain")


class DocumentWorkflowTest(TestCase):
    """To'liq workflow testi: bir va ko'p tahrizchilar bilan"""

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
        self.reviewer2 = User.objects.create_user(
            email='reviewer2@test.com', password='TestPass123!', role='REVIEWER'
        )
        self.reviewer3 = User.objects.create_user(
            email='reviewer3@test.com', password='TestPass123!', role='REVIEWER'
        )
        self.superadmin = User.objects.create_user(
            email='admin@test.com', password='TestPass123!', role='SUPERADMIN'
        )
        self.category = Category.objects.create(name="Test Soha")

    def _create_document(self, user=None):
        """Helper: citizen sifatida hujjat yaratish"""
        self.client.force_authenticate(user=user or self.citizen)
        response = self.client.post('/api/documents/', {
            'title': 'Test Hujjat',
            'file': make_pdf(),
            'category': self.category.id
        }, format='multipart')
        return response

    def _assign_and_review(self, doc_id, reviewer):
        """Helper: bitta tahrizchiga biriktirish, boshlash va tahriz yuklash"""
        self.client.force_authenticate(user=self.secretary)
        self.client.post(f'/api/documents/{doc_id}/assign_reviewer/', {
            'reviewers': [reviewer.id]
        })
        self.client.force_authenticate(user=reviewer)
        self.client.post(f'/api/documents/{doc_id}/start_review/')
        return self.client.post(f'/api/documents/{doc_id}/submit_review/', {
            'review_file': make_pdf("review.pdf"),
            'score': 85,
            'comment': 'Yaxshi hujjat'
        }, format='multipart')

    # ==================== BIR TAHRIZCHI BILAN TO'LIQ WORKFLOW ====================

    def test_full_workflow_single_reviewer_approve(self):
        """Bitta tahrizchi bilan: yaratish → biriktirish → boshlash → tahriz → tasdiqlash"""
        # 1. Citizen hujjat yaratadi
        resp = self._create_document()
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        doc_id = resp.data['id']
        doc = Document.objects.get(id=doc_id)
        self.assertEqual(doc.status, Document.Status.NEW)

        # 2. Secretary tahrizchi biriktiradi → PENDING
        self.client.force_authenticate(user=self.secretary)
        resp = self.client.post(f'/api/documents/{doc_id}/assign_reviewer/', {
            'reviewers': [self.reviewer.id]
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        doc.refresh_from_db()
        self.assertEqual(doc.status, Document.Status.PENDING)
        self.assertEqual(DocumentAssignment.objects.filter(document=doc).count(), 1)

        # 3. Reviewer tahrizni boshlaydi → UNDER_REVIEW
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.post(f'/api/documents/{doc_id}/start_review/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        doc.refresh_from_db()
        self.assertEqual(doc.status, Document.Status.UNDER_REVIEW)

        # 4. Reviewer tahriz yuklaydi → REVIEWED (hammasi tugatdi)
        resp = self.client.post(f'/api/documents/{doc_id}/submit_review/', {
            'review_file': make_pdf("review.pdf"),
            'score': 85,
            'comment': 'Yaxshi hujjat'
        }, format='multipart')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        doc.refresh_from_db()
        self.assertEqual(doc.status, Document.Status.REVIEWED)

        # 5. Manager tasdiqlaydi → APPROVED
        self.client.force_authenticate(user=self.manager)
        resp = self.client.post(f'/api/documents/{doc_id}/finalize/', {
            'decision': 'APPROVE'
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        doc.refresh_from_db()
        self.assertEqual(doc.status, Document.Status.APPROVED)

        # History tekshiruvi
        history = DocumentHistory.objects.filter(document=doc).order_by('created_at')
        self.assertGreaterEqual(history.count(), 5)
        for h in history:
            self.assertIsNotNone(h.user)

    def test_full_workflow_reject(self):
        """Workflow: yaratish → ... → rad etish"""
        resp = self._create_document()
        doc_id = resp.data['id']

        self._assign_and_review(doc_id, self.reviewer)

        # Reject
        self.client.force_authenticate(user=self.manager)
        resp = self.client.post(f'/api/documents/{doc_id}/finalize/', {
            'decision': 'REJECT'
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        doc = Document.objects.get(id=doc_id)
        self.assertEqual(doc.status, Document.Status.REJECTED)

    # ==================== KO'P TAHRIZCHILAR BILAN WORKFLOW ====================

    def test_multi_reviewer_workflow(self):
        """Bir nechta tahrizchi bilan: barchasi tugatganda REVIEWED bo'ladi"""
        resp = self._create_document()
        doc_id = resp.data['id']

        # Birdaniga 2 ta tahrizchi biriktirish
        self.client.force_authenticate(user=self.secretary)
        resp = self.client.post(f'/api/documents/{doc_id}/assign_reviewer/', {
            'reviewers': [self.reviewer.id, self.reviewer2.id]
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(DocumentAssignment.objects.filter(document_id=doc_id).count(), 2)

        doc = Document.objects.get(id=doc_id)
        self.assertEqual(doc.status, Document.Status.PENDING)

        # 1-chi tahrizchi boshlaydi → UNDER_REVIEW
        self.client.force_authenticate(user=self.reviewer)
        self.client.post(f'/api/documents/{doc_id}/start_review/')
        doc.refresh_from_db()
        self.assertEqual(doc.status, Document.Status.UNDER_REVIEW)

        # 1-chi tahrizchi yuklaydi — hali barchasi tugamagan → UNDER_REVIEW da qoladi
        self.client.post(f'/api/documents/{doc_id}/submit_review/', {
            'review_file': make_pdf("review1.pdf"),
            'score': 90,
            'comment': 'Ajoyib'
        }, format='multipart')
        doc.refresh_from_db()
        self.assertEqual(doc.status, Document.Status.UNDER_REVIEW)

        # 2-chi tahrizchi boshlaydi va yuklaydi → barchasi tugatdi → REVIEWED
        self.client.force_authenticate(user=self.reviewer2)
        self.client.post(f'/api/documents/{doc_id}/start_review/')
        resp = self.client.post(f'/api/documents/{doc_id}/submit_review/', {
            'review_file': make_pdf("review2.pdf"),
            'score': 75,
            'comment': 'Yaxshi'
        }, format='multipart')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        doc.refresh_from_db()
        self.assertEqual(doc.status, Document.Status.REVIEWED)

        # 2 ta review mavjud bo'lishi kerak
        self.assertEqual(Review.objects.filter(document=doc).count(), 2)

    def test_sequential_reviewer_assignment(self):
        """Tahrizchilarni birma-bir biriktirish: yangilari qo'shilishi mumkin"""
        resp = self._create_document()
        doc_id = resp.data['id']

        # 1-chi tahrizchi
        self.client.force_authenticate(user=self.secretary)
        resp = self.client.post(f'/api/documents/{doc_id}/assign_reviewer/', {
            'reviewers': [self.reviewer.id]
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(DocumentAssignment.objects.filter(document_id=doc_id).count(), 1)

        # 1-chi boshlaydi
        self.client.force_authenticate(user=self.reviewer)
        self.client.post(f'/api/documents/{doc_id}/start_review/')

        # UNDER_REVIEW holatda 2-chi tahrizchi qo'shish
        self.client.force_authenticate(user=self.secretary)
        resp = self.client.post(f'/api/documents/{doc_id}/assign_reviewer/', {
            'reviewers': [self.reviewer2.id]
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(DocumentAssignment.objects.filter(document_id=doc_id).count(), 2)

        # 1-chi tugatdi — hali 2-chi bor → UNDER_REVIEW da qoladi
        self.client.force_authenticate(user=self.reviewer)
        self.client.post(f'/api/documents/{doc_id}/submit_review/', {
            'review_file': make_pdf("r1.pdf"), 'score': 80
        }, format='multipart')
        doc = Document.objects.get(id=doc_id)
        self.assertEqual(doc.status, Document.Status.UNDER_REVIEW)

        # 2-chi ham tugatdi → REVIEWED
        self.client.force_authenticate(user=self.reviewer2)
        self.client.post(f'/api/documents/{doc_id}/start_review/')
        self.client.post(f'/api/documents/{doc_id}/submit_review/', {
            'review_file': make_pdf("r2.pdf"), 'score': 70
        }, format='multipart')
        doc.refresh_from_db()
        self.assertEqual(doc.status, Document.Status.REVIEWED)

    def test_assign_three_reviewers_at_once(self):
        """3 ta tahrizchini birdaniga biriktirish"""
        resp = self._create_document()
        doc_id = resp.data['id']

        self.client.force_authenticate(user=self.manager)
        resp = self.client.post(f'/api/documents/{doc_id}/assign_reviewer/', {
            'reviewers': [self.reviewer.id, self.reviewer2.id, self.reviewer3.id]
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(DocumentAssignment.objects.filter(document_id=doc_id).count(), 3)

    def test_duplicate_assignment_skipped(self):
        """Allaqachon biriktirilgan tahrizchi qayta biriktirilmaydi"""
        resp = self._create_document()
        doc_id = resp.data['id']

        self.client.force_authenticate(user=self.secretary)
        self.client.post(f'/api/documents/{doc_id}/assign_reviewer/', {
            'reviewers': [self.reviewer.id]
        })

        # Xuddi shu tahrizchini qayta biriktirish — xato
        resp = self.client.post(f'/api/documents/{doc_id}/assign_reviewer/', {
            'reviewers': [self.reviewer.id]
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_add_new_reviewer_with_existing(self):
        """Mavjud tahrizchi + yangi tahrizchi — faqat yangisi qo'shiladi"""
        resp = self._create_document()
        doc_id = resp.data['id']

        self.client.force_authenticate(user=self.secretary)
        self.client.post(f'/api/documents/{doc_id}/assign_reviewer/', {
            'reviewers': [self.reviewer.id]
        })

        # Mavjud + yangi
        resp = self.client.post(f'/api/documents/{doc_id}/assign_reviewer/', {
            'reviewers': [self.reviewer.id, self.reviewer2.id]
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(DocumentAssignment.objects.filter(document_id=doc_id).count(), 2)

    # ==================== STATUS TRANSITION VALIDATION ====================

    def test_cannot_skip_status_steps(self):
        """NEW dan to'g'ridan to'g'ri APPROVED ga o'tib bo'lmaydi"""
        resp = self._create_document()
        doc_id = resp.data['id']

        self.client.force_authenticate(user=self.manager)
        resp = self.client.post(f'/api/documents/{doc_id}/finalize/', {
            'decision': 'APPROVE'
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_finalize_pending_document(self):
        """PENDING holatdagi hujjatni to'g'ridan to'g'ri tasdiqlash mumkin emas"""
        resp = self._create_document()
        doc_id = resp.data['id']

        self.client.force_authenticate(user=self.secretary)
        self.client.post(f'/api/documents/{doc_id}/assign_reviewer/', {
            'reviewers': [self.reviewer.id]
        })

        self.client.force_authenticate(user=self.manager)
        resp = self.client.post(f'/api/documents/{doc_id}/finalize/', {
            'decision': 'APPROVE'
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_submit_review_without_start(self):
        """Tahrizni boshlamasdan yuklash mumkin emas"""
        resp = self._create_document()
        doc_id = resp.data['id']

        self.client.force_authenticate(user=self.secretary)
        self.client.post(f'/api/documents/{doc_id}/assign_reviewer/', {
            'reviewers': [self.reviewer.id]
        })

        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.post(f'/api/documents/{doc_id}/submit_review/', {
            'review_file': make_pdf("review.pdf"),
            'score': 80
        }, format='multipart')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_assign_to_reviewed_document(self):
        """REVIEWED holatdagi hujjatga tahrizchi biriktirish mumkin emas"""
        resp = self._create_document()
        doc_id = resp.data['id']
        self._assign_and_review(doc_id, self.reviewer)

        self.client.force_authenticate(user=self.secretary)
        resp = self.client.post(f'/api/documents/{doc_id}/assign_reviewer/', {
            'reviewers': [self.reviewer2.id]
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    # ==================== DUPLICATE REVIEW ====================

    def test_duplicate_review_prevented(self):
        """Bir tahrizchi ikki marta tahriz yuklash mumkin emas"""
        resp = self._create_document()
        doc_id = resp.data['id']

        # 2 tahrizchi biriktirish (shunda hujjat REVIEWED bo'lmasin)
        self.client.force_authenticate(user=self.secretary)
        self.client.post(f'/api/documents/{doc_id}/assign_reviewer/', {
            'reviewers': [self.reviewer.id, self.reviewer2.id]
        })

        self.client.force_authenticate(user=self.reviewer)
        self.client.post(f'/api/documents/{doc_id}/start_review/')
        self.client.post(f'/api/documents/{doc_id}/submit_review/', {
            'review_file': make_pdf("review.pdf"),
            'score': 90
        }, format='multipart')

        # Ikkinchi tahriz — assignment allaqachon COMPLETED
        resp = self.client.post(f'/api/documents/{doc_id}/submit_review/', {
            'review_file': make_pdf("review2.pdf"),
            'score': 80
        }, format='multipart')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    # ==================== PERMISSION TESTS ====================

    def test_only_citizen_can_create(self):
        """Faqat CITIZEN hujjat yarata oladi"""
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.post('/api/documents/', {
            'title': 'Test',
            'file': make_pdf(),
            'category': self.category.id
        }, format='multipart')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_citizen_can_only_see_own_documents(self):
        """Citizen faqat o'z hujjatlarini ko'radi"""
        citizen2 = User.objects.create_user(
            email='citizen2@test.com', password='TestPass123!', role='CITIZEN'
        )
        self._create_document(user=self.citizen)
        self._create_document(user=citizen2)

        self.client.force_authenticate(user=self.citizen)
        resp = self.client.get('/api/documents/')
        self.assertEqual(resp.data['count'], 1)

    def test_superadmin_sees_all_documents(self):
        """SUPERADMIN barcha hujjatlarni ko'ra oladi"""
        self._create_document()
        self.client.force_authenticate(user=self.superadmin)
        resp = self.client.get('/api/documents/')
        self.assertEqual(resp.data['count'], 1)

    def test_reviewer_sees_only_assigned_documents(self):
        """REVIEWER faqat unga biriktirilgan hujjatlarni ko'radi"""
        resp = self._create_document()
        doc_id = resp.data['id']

        self.client.force_authenticate(user=self.secretary)
        self.client.post(f'/api/documents/{doc_id}/assign_reviewer/', {
            'reviewers': [self.reviewer.id]
        })

        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.get('/api/documents/')
        self.assertEqual(resp.data['count'], 1)

        # reviewer2 ko'rmaydi
        self.client.force_authenticate(user=self.reviewer2)
        resp = self.client.get('/api/documents/')
        self.assertEqual(resp.data['count'], 0)

    def test_citizen_cannot_delete_non_new_document(self):
        """Citizen faqat NEW holatdagi hujjatni o'chira oladi"""
        resp = self._create_document()
        doc_id = resp.data['id']

        self.client.force_authenticate(user=self.secretary)
        self.client.post(f'/api/documents/{doc_id}/assign_reviewer/', {
            'reviewers': [self.reviewer.id]
        })

        self.client.force_authenticate(user=self.citizen)
        resp = self.client.delete(f'/api/documents/{doc_id}/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_citizen_can_delete_new_document(self):
        """Citizen NEW holatdagi o'z hujjatini o'chira oladi"""
        resp = self._create_document()
        doc_id = resp.data['id']

        self.client.force_authenticate(user=self.citizen)
        resp = self.client.delete(f'/api/documents/{doc_id}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

    def test_citizen_cannot_edit_other_citizen_document(self):
        """Citizen boshqa citizen ning hujjatini tahrirlay olmaydi"""
        resp = self._create_document()
        doc_id = resp.data['id']

        citizen2 = User.objects.create_user(
            email='citizen2@test.com', password='TestPass123!', role='CITIZEN'
        )
        self.client.force_authenticate(user=citizen2)
        resp = self.client.patch(f'/api/documents/{doc_id}/', {
            'title': 'Hacked!'
        })
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_unassigned_reviewer_cannot_start_review(self):
        """Biriktirilmagan tahrizchi tahrizni boshlay olmaydi"""
        resp = self._create_document()
        doc_id = resp.data['id']

        self.client.force_authenticate(user=self.secretary)
        self.client.post(f'/api/documents/{doc_id}/assign_reviewer/', {
            'reviewers': [self.reviewer.id]
        })

        # reviewer2 biriktirilmagan — 404 (queryset da ko'rinmaydi)
        self.client.force_authenticate(user=self.reviewer2)
        resp = self.client.post(f'/api/documents/{doc_id}/start_review/')
        self.assertIn(resp.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    # ==================== ASSIGN REVIEWER VALIDATION ====================

    def test_assign_non_reviewer_role_rejected(self):
        """REVIEWER bo'lmagan foydalanuvchini biriktirish mumkin emas"""
        resp = self._create_document()
        doc_id = resp.data['id']

        self.client.force_authenticate(user=self.secretary)
        resp = self.client.post(f'/api/documents/{doc_id}/assign_reviewer/', {
            'reviewers': [self.citizen.id]
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_assign_empty_list_rejected(self):
        """Bo'sh tahrizchilar ro'yxati qabul qilinmaydi"""
        resp = self._create_document()
        doc_id = resp.data['id']

        self.client.force_authenticate(user=self.secretary)
        resp = self.client.post(f'/api/documents/{doc_id}/assign_reviewer/', {
            'reviewers': []
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    # ==================== SCORE VALIDATION ====================

    def test_score_must_be_0_to_100(self):
        """Score 0-100 orasida bo'lishi kerak"""
        resp = self._create_document()
        doc_id = resp.data['id']

        self.client.force_authenticate(user=self.secretary)
        self.client.post(f'/api/documents/{doc_id}/assign_reviewer/', {
            'reviewers': [self.reviewer.id]
        })

        self.client.force_authenticate(user=self.reviewer)
        self.client.post(f'/api/documents/{doc_id}/start_review/')

        resp = self.client.post(f'/api/documents/{doc_id}/submit_review/', {
            'review_file': make_pdf("review.pdf"),
            'score': 150,
        }, format='multipart')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_negative_score_rejected(self):
        """Salbiy ball qabul qilinmaydi"""
        resp = self._create_document()
        doc_id = resp.data['id']

        self.client.force_authenticate(user=self.secretary)
        self.client.post(f'/api/documents/{doc_id}/assign_reviewer/', {
            'reviewers': [self.reviewer.id]
        })

        self.client.force_authenticate(user=self.reviewer)
        self.client.post(f'/api/documents/{doc_id}/start_review/')

        resp = self.client.post(f'/api/documents/{doc_id}/submit_review/', {
            'review_file': make_pdf("review.pdf"),
            'score': -5,
        }, format='multipart')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    # ==================== FILE VALIDATION ====================

    def test_non_pdf_document_rejected(self):
        """PDF bo'lmagan fayl qabul qilinmaydi"""
        self.client.force_authenticate(user=self.citizen)
        resp = self.client.post('/api/documents/', {
            'title': 'Test',
            'file': make_txt(),
            'category': self.category.id
        }, format='multipart')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_fake_pdf_rejected(self):
        """Kengaytmasi .pdf lekin tarkibi PDF bo'lmagan fayl rad etiladi"""
        fake_pdf = SimpleUploadedFile("fake.pdf", b"not a real pdf", content_type="application/pdf")
        self.client.force_authenticate(user=self.citizen)
        resp = self.client.post('/api/documents/', {
            'title': 'Fake PDF',
            'file': fake_pdf,
            'category': self.category.id
        }, format='multipart')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    # ==================== STATS ====================

    def test_stats_api(self):
        """Statistika API to'g'ri ishlashi"""
        self._create_document()

        self.client.force_authenticate(user=self.citizen)
        resp = self.client.get('/api/documents/stats/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['total'], 1)
        self.assertEqual(resp.data['new'], 1)

    def test_superadmin_stats(self):
        """SUPERADMIN statistika ko'ra olishi kerak"""
        self._create_document()

        self.client.force_authenticate(user=self.superadmin)
        resp = self.client.get('/api/documents/stats/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['total'], 1)

    def test_reviewer_stats(self):
        """REVIEWER statistikasi faqat biriktirilgan hujjatlarini ko'rsatadi"""
        resp = self._create_document()
        doc_id = resp.data['id']

        self.client.force_authenticate(user=self.secretary)
        self.client.post(f'/api/documents/{doc_id}/assign_reviewer/', {
            'reviewers': [self.reviewer.id]
        })

        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.get('/api/documents/stats/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['total'], 1)
        self.assertEqual(resp.data['pending'], 1)

    # ==================== FINALIZE VALIDATION ====================

    def test_finalize_bad_decision(self):
        """Noto'g'ri decision xato qaytaradi"""
        resp = self._create_document()
        doc_id = resp.data['id']
        self._assign_and_review(doc_id, self.reviewer)

        self.client.force_authenticate(user=self.manager)
        resp = self.client.post(f'/api/documents/{doc_id}/finalize/', {
            'decision': 'INVALID'
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    # ==================== ASSIGNMENT STATUS ====================

    def test_assignment_status_transitions(self):
        """Assignment status: PENDING → IN_PROGRESS → COMPLETED"""
        resp = self._create_document()
        doc_id = resp.data['id']

        self.client.force_authenticate(user=self.secretary)
        self.client.post(f'/api/documents/{doc_id}/assign_reviewer/', {
            'reviewers': [self.reviewer.id]
        })

        assignment = DocumentAssignment.objects.get(
            document_id=doc_id, reviewer=self.reviewer
        )
        self.assertEqual(assignment.status, DocumentAssignment.AssignmentStatus.PENDING)

        # Start review → IN_PROGRESS
        self.client.force_authenticate(user=self.reviewer)
        self.client.post(f'/api/documents/{doc_id}/start_review/')
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, DocumentAssignment.AssignmentStatus.IN_PROGRESS)

        # Submit review → COMPLETED
        self.client.post(f'/api/documents/{doc_id}/submit_review/', {
            'review_file': make_pdf("review.pdf"),
            'score': 80
        }, format='multipart')
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, DocumentAssignment.AssignmentStatus.COMPLETED)

    def test_cannot_start_review_twice(self):
        """Allaqachon boshlangan tahrizni qayta boshlash mumkin emas"""
        resp = self._create_document()
        doc_id = resp.data['id']

        self.client.force_authenticate(user=self.secretary)
        self.client.post(f'/api/documents/{doc_id}/assign_reviewer/', {
            'reviewers': [self.reviewer.id]
        })

        self.client.force_authenticate(user=self.reviewer)
        self.client.post(f'/api/documents/{doc_id}/start_review/')

        # Qayta boshlash
        resp = self.client.post(f'/api/documents/{doc_id}/start_review/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
