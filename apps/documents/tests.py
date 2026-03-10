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
            email='reviewer@test.com', password='TestPass123!', role='CITIZEN'
        )
        self.reviewer2 = User.objects.create_user(
            email='reviewer2@test.com', password='TestPass123!', role='CITIZEN'
        )
        self.reviewer3 = User.objects.create_user(
            email='reviewer3@test.com', password='TestPass123!', role='CITIZEN'
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

        # 5. Manager tasdiqlaydi → WAITING_FOR_DISPATCH
        self.client.force_authenticate(user=self.manager)
        resp = self.client.post(f'/api/documents/{doc_id}/finalize/', {
            'decision': 'APPROVE'
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        doc.refresh_from_db()
        self.assertEqual(doc.status, Document.Status.WAITING_FOR_DISPATCH)

        # 6. Secretary yuboradi → APPROVED
        self.client.force_authenticate(user=self.secretary)
        resp = self.client.post(f'/api/documents/{doc_id}/send_to_citizen/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        doc.refresh_from_db()
        self.assertEqual(doc.status, Document.Status.APPROVED)

        # History tekshiruvi
        history = DocumentHistory.objects.filter(document=doc).order_by('created_at')
        self.assertGreaterEqual(history.count(), 5)
        for h in history:
            self.assertIsNotNone(h.user)

    def test_full_workflow_reject(self):
        """Workflow: yaratish → ... → rad etish (fuqaroga)"""
        resp = self._create_document()
        doc_id = resp.data['id']

        self._assign_and_review(doc_id, self.reviewer)

        # Reject (fuqaroga)
        self.client.force_authenticate(user=self.manager)
        resp = self.client.post(f'/api/documents/{doc_id}/finalize/', {
            'decision': 'REJECT'
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        doc = Document.objects.get(id=doc_id)
        self.assertEqual(doc.status, Document.Status.REJECTED)

    def test_re_review_decision_rejected(self):
        """RE_REVIEW endi qo'llab-quvvatlanmaydi — xato qaytarishi kerak"""
        resp = self._create_document()
        doc_id = resp.data['id']

        self._assign_and_review(doc_id, self.reviewer)

        # RE_REVIEW endi invalid decision
        self.client.force_authenticate(user=self.manager)
        resp = self.client.post(f'/api/documents/{doc_id}/finalize/', {
            'decision': 'RE_REVIEW'
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_workflow_manager_decision_secretary_dispatch(self):
        """Workflow: Manager tasdiqlaydi -> Secretary yuboradi"""
        resp = self._create_document()
        doc_id = resp.data['id']
        self._assign_and_review(doc_id, self.reviewer)

        # 1. Manager tasdiqlaydi
        self.client.force_authenticate(user=self.manager)
        resp = self.client.post(f'/api/documents/{doc_id}/finalize/', {'decision': 'APPROVE'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        
        doc = Document.objects.get(id=doc_id)
        self.assertEqual(doc.status, Document.Status.WAITING_FOR_DISPATCH)

        # 2. Citizen ko'radi (tahrizlarni ko'rmasligi kerak)
        self.client.force_authenticate(user=self.citizen)
        resp = self.client.get(f'/api/documents/{doc_id}/')
        self.assertEqual(len(resp.data['reviews']), 0)

        # 3. Secretary yuboradi (send_to_citizen)
        self.client.force_authenticate(user=self.secretary)
        resp = self.client.post(f'/api/documents/{doc_id}/send_to_citizen/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        
        doc.refresh_from_db()
        self.assertEqual(doc.status, Document.Status.APPROVED)

        # 4. Citizen ko'radi (tahrizlarni ko'ra olishi kerak)
        self.client.force_authenticate(user=self.citizen)
        resp = self.client.get(f'/api/documents/{doc_id}/')
        self.assertGreater(len(resp.data['reviews']), 0)

    def test_secretary_can_finalize(self):
        """Secretary ham finalize qila olishini tekshirish (tenglashtirilgan huquqlar)"""
        resp = self._create_document()
        doc_id = resp.data['id']
        self._assign_and_review(doc_id, self.reviewer)

        self.client.force_authenticate(user=self.secretary)
        resp = self.client.post(f'/api/documents/{doc_id}/finalize/', {
            'decision': 'APPROVE'
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_reviewer_anonymity_for_citizen(self):
        """Fuqaro tahrizchi emailini ko'rmasligini tekshirish"""
        resp = self._create_document()
        doc_id = resp.data['id']
        self._assign_and_review(doc_id, self.reviewer)

        # Citizen sifatida ko'rish
        self.client.force_authenticate(user=self.citizen)
        resp = self.client.get(f'/api/documents/{doc_id}/')
        
        # Reviewer emailini qidirish
        import json
        resp_str = json.dumps(resp.data)
        self.assertNotIn(self.reviewer.email, resp_str)
        self.assertIn("Tahrizchi", resp_str)
        self.assertIn("Maxfiy", resp_str)

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

    def test_review_update_allowed_until_seen(self):
        """Tahrizchi o'z tahrizini manager ko'rmaguncha yangilay olishi"""
        resp = self._create_document()
        doc_id = resp.data['id']

        # 2 tahrizchi biriktirish
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

        # Ikkinchi marta yuborish (update) — 200 OK qaytishi kerak
        resp = self.client.post(f'/api/documents/{doc_id}/submit_review/', {
            'review_file': make_pdf("review2.pdf"),
            'score': 80
        }, format='multipart')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # Manager ko'rdi deb belgilaydi
        self.client.force_authenticate(user=self.manager)
        self.client.post(f'/api/documents/{doc_id}/mark_review_as_seen/', {
            'reviewer_id': self.reviewer.id
        })

        # Endi yangilab bo'lmasligi kerak
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.post(f'/api/documents/{doc_id}/submit_review/', {
            'review_file': make_pdf("review3.pdf")
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
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

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

    def test_assign_citizen_role_accepted(self):
        """Oddiy foydalanuvchini (Citizen) tahrizchi sifatidabiriktirish mumkin"""
        resp = self._create_document()
        doc_id = resp.data['id']

        self.client.force_authenticate(user=self.secretary)
        resp = self.client.post(f'/api/documents/{doc_id}/assign_reviewer/', {
            'reviewers': [self.citizen.id]
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

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

    def test_individual_review_management_workflow(self):
        """Workflow: Rais har bir tahrizni alohida qabul/rad qilishi"""
        resp = self._create_document()
        doc_id = resp.data['id']

        # 2 ta tahrizchi biriktirish
        self.client.force_authenticate(user=self.secretary)
        self.client.post(f'/api/documents/{doc_id}/assign_reviewer/', {
            'reviewers': [self.reviewer.id, self.reviewer2.id]
        })

        # 1-chi tahrizchi yuklaydi
        self.client.force_authenticate(user=self.reviewer)
        self.client.post(f'/api/documents/{doc_id}/start_review/')
        self.client.post(f'/api/documents/{doc_id}/submit_review/', {
            'review_file': make_pdf("r1.pdf"), 'score': 80
        }, format='multipart')

        # 2-chi tahrizchi yuklaydi
        self.client.force_authenticate(user=self.reviewer2)
        self.client.post(f'/api/documents/{doc_id}/start_review/')
        self.client.post(f'/api/documents/{doc_id}/submit_review/', {
            'review_file': make_pdf("r2.pdf"), 'score': 70
        }, format='multipart')

        doc = Document.objects.get(id=doc_id)
        self.assertEqual(doc.status, Document.Status.REVIEWED)

        # Rais 1-chi tahrizni rad etadi
        assignment1 = DocumentAssignment.objects.get(document=doc, reviewer=self.reviewer)
        self.client.force_authenticate(user=self.manager)
        resp = self.client.post(f'/api/documents/{doc_id}/reject_review/', {
            'reviewer_id': self.reviewer.id,
            'comment': 'Sifatsiz tahriz'
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        
        doc.refresh_from_db()
        self.assertEqual(doc.status, Document.Status.UNDER_REVIEW)
        assignment1.refresh_from_db()
        self.assertEqual(assignment1.manager_decision, DocumentAssignment.ManagerDecision.REJECTED)
        self.assertEqual(assignment1.status, DocumentAssignment.AssignmentStatus.IN_PROGRESS)

        # Rais hozir finalize(APPROVE) qilolmasligi kerak (chunki status UNDER_REVIEW)
        resp = self.client.post(f'/api/documents/{doc_id}/finalize/', {'decision': 'APPROVE'})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        # DRF ValidationError dict bo'lishi mumkin yoki list
        error_data = str(resp.data)
        self.assertIn("Tahrizda", error_data)

        # 1-chi tahrizchi qayta yuklaydi (update)
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.post(f'/api/documents/{doc_id}/submit_review/', {
            'review_file': make_pdf("r1_fixed.pdf"), 'score': 85
        }, format='multipart')
        self.assertEqual(resp.status_code, status.HTTP_200_OK) # Update uchun 200
        
        assignment1.refresh_from_db()
        self.assertEqual(assignment1.manager_decision, DocumentAssignment.ManagerDecision.PENDING)
        self.assertEqual(assignment1.status, DocumentAssignment.AssignmentStatus.COMPLETED)
        
        doc.refresh_from_db()
        self.assertEqual(doc.status, Document.Status.REVIEWED)

        # Rais bitta tahrizni qabul qiladi, ikkinchisi PENDING ligicha qoladi
        assignment2 = DocumentAssignment.objects.get(document=doc, reviewer=self.reviewer2)
        self.client.force_authenticate(user=self.manager)
        self.client.post(f'/api/documents/{doc_id}/accept_review/', {'reviewer_id': self.reviewer.id})
        
        doc.refresh_from_db()
        self.assertEqual(doc.status, Document.Status.REVIEWED) # Hali ham REVIEWED

        # Rais endi tasdiqlaydi (finalize APPROVE)
        # Bu qolgan PENDING (assignment2) ni avtomatik ACCEPTED qiladi
        resp = self.client.post(f'/api/documents/{doc_id}/finalize/', {'decision': 'APPROVE'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        
        doc.refresh_from_db()
        self.assertEqual(doc.status, Document.Status.WAITING_FOR_DISPATCH)
        
        assignment2.refresh_from_db()
        self.assertEqual(assignment2.manager_decision, DocumentAssignment.ManagerDecision.ACCEPTED)

        # Kotib yuboradi
        self.client.force_authenticate(user=self.secretary)
        resp = self.client.post(f'/api/documents/{doc_id}/send_to_citizen/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        doc.refresh_from_db()
        self.assertEqual(doc.status, Document.Status.APPROVED)

    def test_mark_review_as_seen_blocks_reviewer(self):
        """Tahrizni 'ko'rildi' deb belgilash tahrizchini bloklashini tekshirish"""
        # 1. Hujjat yaratish va tahriz topshirish
        resp = self._create_document()
        doc_id = resp.data['id']
        self._assign_and_review(doc_id, self.reviewer)
        
        # 2. Rais tahrizni ko'rildi deb belgilaydi
        self.client.force_authenticate(user=self.manager)
        resp = self.client.post(f'/api/documents/{doc_id}/mark_review_as_seen/', {
            'reviewer_id': self.reviewer.id
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        
        # 3. Tahrizchi endi o'chira olmasligi kerak
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.post(f'/api/documents/{doc_id}/delete_review/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("ko'rib chiqilgan", str(resp.data))
        
        # 4. Tahrizchi endi qayta yuklay (update) olmasligi kerak
        resp = self.client.post(f'/api/documents/{doc_id}/submit_review/', {
            'review_file': make_pdf("new.pdf")
        }, format='multipart')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("ko'rib chiqilgan", str(resp.data))

