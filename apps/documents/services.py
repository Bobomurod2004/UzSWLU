import logging
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError, PermissionDenied

from .models import Document, DocumentAssignment, Review, DocumentHistory
from apps.notifications.services import notify_user, notify_staff
from apps.notifications.models import Notification

logger = logging.getLogger('django')

class DocumentService:
    @staticmethod
    def _record_history(document, old_status, new_status, user, comment=None):
        """Hujjat tarixini yozish"""
        DocumentHistory.objects.create(
            document=document,
            user=user,
            old_status=old_status,
            new_status=new_status,
            comment=comment or "Status o'zgardi"
        )

    @transaction.atomic
    def assign_reviewers(self, document, reviewers, assigned_by):
        """Tahrizchilarni biriktirish mantiqi"""
        allowed_statuses = [
            Document.Status.NEW,
            Document.Status.PENDING,
            Document.Status.UNDER_REVIEW,
        ]
        if document.status not in allowed_statuses:
            raise ValidationError(f"'{document.get_status_display()}' holatida tahrizchi biriktirish mumkin emas.")

        created_count = 0
        skipped = []

        for reviewer in reviewers:
            assignment, created = DocumentAssignment.objects.get_or_create(
                document=document,
                reviewer=reviewer,
                defaults={'assigned_by': assigned_by}
            )
            if created:
                created_count += 1
            else:
                skipped.append(reviewer.email)

        if created_count == 0:
            raise ValidationError({
                "error": "Barcha tanlangan tahrizchilar allaqachon biriktirilgan.",
                "skipped": skipped
            })

        # Status o'zgarishi
        old_status = document.status
        if document.status == Document.Status.NEW:
            document.status = Document.Status.PENDING
            document.save(update_fields=['status', 'updated_at'])

        reviewer_names = ", ".join(r.email for r in reviewers)
        self._record_history(
            document, old_status, document.status, assigned_by,
            "Tahrizchi(lar) biriktirildi: %s" % reviewer_names
        )

        for reviewer in reviewers:
            notify_user(
                reviewer, document,
                Notification.Type.REVIEWER_ASSIGNED,
                f"📋 Sizga yangi hujjat biriktirildi: \"{document.title}\""
            )
        
        return document

    @transaction.atomic
    def start_review(self, document, reviewer):
        """Tahrizni boshlash mantiqi"""
        try:
            assignment = DocumentAssignment.objects.select_for_update().get(
                document=document, reviewer=reviewer
            )
        except DocumentAssignment.DoesNotExist:
            raise PermissionDenied("Siz bu hujjatga biriktirilmagansiz")

        if assignment.status != DocumentAssignment.AssignmentStatus.PENDING:
            raise ValidationError(f"Sizning biriktirmangiz '{assignment.get_status_display()}' holatida. "
                                f"Faqat 'Kutilmoqda' holatida boshlash mumkin.")

        assignment.status = DocumentAssignment.AssignmentStatus.IN_PROGRESS
        assignment.save(update_fields=['status', 'updated_at'])

        old_status = document.status
        if document.status == Document.Status.PENDING:
            document.status = Document.Status.UNDER_REVIEW
            document.save(update_fields=['status', 'updated_at'])

        self._record_history(
            document, old_status, document.status, reviewer,
            "Tahriz boshlandi (%s)" % reviewer.email
        )
        
        notify_staff(
            document,
            Notification.Type.REVIEW_STARTED,
            f"🔍 Tahriz boshlandi: \"{document.title}\" ({reviewer.email})"
        )
        return document

    @transaction.atomic
    def submit_review(self, document, reviewer, review_data, review_file):
        """Tahrizni topshirish mantiqi"""
        try:
            assignment = DocumentAssignment.objects.select_for_update().get(
                document=document, reviewer=reviewer
            )
        except DocumentAssignment.DoesNotExist:
            raise PermissionDenied("Siz bu hujjatga biriktirilmagansiz")

        if assignment.status == DocumentAssignment.AssignmentStatus.COMPLETED and \
           assignment.manager_decision != DocumentAssignment.ManagerDecision.REJECTED:
            raise ValidationError("Siz bu hujjat uchun allaqachon tahriz yuborgansiz.")

        if assignment.status == DocumentAssignment.AssignmentStatus.PENDING:
            raise ValidationError("Avval tahrizni boshlang (start_review).")

        review_instance = Review.objects.filter(document=document, reviewer=reviewer).first()
        
        if review_instance:
            review_instance.review_file = review_file or review_instance.review_file
            review_instance.score = review_data.get('score', review_instance.score)
            review_instance.comment = review_data.get('comment', review_instance.comment)
            review_instance.save()
            action_text = "Tahriz yangilandi"
            is_update = True
        else:
            Review.objects.create(
                document=document,
                reviewer=reviewer,
                review_file=review_file,
                score=review_data.get('score'),
                comment=review_data.get('comment')
            )
            action_text = "Tahriz yuklandi"
            is_update = False

        assignment.status = DocumentAssignment.AssignmentStatus.COMPLETED
        assignment.manager_decision = DocumentAssignment.ManagerDecision.PENDING
        assignment.save(update_fields=['status', 'manager_decision', 'updated_at'])

        document.refresh_from_db()
        old_status = document.status
        all_assignments = DocumentAssignment.objects.filter(document=document)
        has_unfinished = all_assignments.exclude(status=DocumentAssignment.AssignmentStatus.COMPLETED).exists()
        
        if not has_unfinished:
            if document.status != Document.Status.REVIEWED:
                document.status = Document.Status.REVIEWED
                document.save(update_fields=['status', 'updated_at'])
                self._record_history(
                    document, old_status, document.status, reviewer,
                    "Barcha tahrizchilar ishini tugatdi — hujjat tahrizlandi"
                )
            else:
                self._record_history(document, old_status, document.status, reviewer, f"{action_text} ({reviewer.email})")
        else:
            self._record_history(document, old_status, document.status, reviewer, f"{action_text} ({reviewer.email})")

        notify_staff(
            document,
            Notification.Type.REVIEW_SUBMITTED,
            f"📝 Tahriz yuklandi: \"{document.title}\" ({reviewer.email})"
        )
        return document, is_update

    @transaction.atomic
    def accept_review(self, document, review_id, manager, comment=""):
        """Tahrizni qabul qilish"""
        assignment = get_object_or_404(DocumentAssignment, id=review_id, document=document)

        if assignment.status != DocumentAssignment.AssignmentStatus.COMPLETED:
            raise ValidationError("Faqat yakunlangan tahrizni qabul qilish mumkin")

        assignment.manager_decision = DocumentAssignment.ManagerDecision.ACCEPTED
        assignment.save(update_fields=['manager_decision', 'updated_at'])

        history_comment = f"Tahriz qabul qilindi (Tahrizchi: {assignment.reviewer.email})"
        if comment:
            history_comment += f" — {comment}"
        
        self._record_history(document, document.status, document.status, manager, history_comment)
        
        notify_user(
            assignment.reviewer, document,
            Notification.Type.REVIEW_ACCEPTED,
            f"✅ Tahrizingiz qabul qilindi: \"{document.title}\""
        )
        return document

    @transaction.atomic
    def reject_review(self, document, review_id, manager, comment=""):
        """Tahrizni rad etish"""
        assignment = get_object_or_404(DocumentAssignment, id=review_id, document=document)

        assignment.manager_decision = DocumentAssignment.ManagerDecision.REJECTED
        assignment.status = DocumentAssignment.AssignmentStatus.IN_PROGRESS
        assignment.rejection_reason = comment
        assignment.save(update_fields=['manager_decision', 'status', 'rejection_reason', 'updated_at'])

        if document.status == Document.Status.REVIEWED:
            old_status = document.status
            document.status = Document.Status.UNDER_REVIEW
            document.save(update_fields=['status', 'updated_at'])
            self._record_history(document, old_status, document.status, manager, f"Hujjat qayta tahrizga o'tkazildi (Tahriz rad etildi: {assignment.reviewer.email})")

        history_comment = f"Tahriz rad etildi (Tahrizchi: {assignment.reviewer.email}). Sabab: {comment}"
        self._record_history(document, document.status, document.status, manager, history_comment)
        
        notify_user(
            assignment.reviewer, document,
            Notification.Type.REVIEW_REJECTED,
            f"🔄 Tahrizingiz rad etildi, qayta ko'ring: \"{document.title}\""
        )
        return document

    @transaction.atomic
    def finalize_document(self, document, manager, decision, comment=""):
        """Hujjat bo'yicha yakuniy qaror"""
        document.refresh_from_db()
        if document.status != Document.Status.REVIEWED:
            raise ValidationError(f"'{document.get_status_display()}' holatidagi hujjatda qaror qabul qilib bo'lmaydi.")

        old_status = document.status

        if decision == 'APPROVE':
            document.assignments.filter(
                status=DocumentAssignment.AssignmentStatus.COMPLETED
            ).update(manager_decision=DocumentAssignment.ManagerDecision.ACCEPTED)

            document.status = Document.Status.WAITING_FOR_DISPATCH
            document.save(update_fields=['status', 'updated_at'])

            history_comment = "Hujjat tasdiqlandi (yuborish kutilmoqda)"
            if comment:
                history_comment += f" — {comment}"
            self._record_history(document, old_status, document.status, manager, history_comment)

            notify_staff(document, Notification.Type.DOCUMENT_APPROVED, f"✅ Hujjat tasdiqlandi: \"{document.title}\"")
            notify_user(document.owner, document, Notification.Type.DOCUMENT_APPROVED, f"✅ Hujjatingiz tasdiqlandi: \"{document.title}\"")
            return "Hujjat tasdiqlandi. Endi kotib uni yuborishi kerak."

        elif decision == 'REJECT':
            document.status = Document.Status.REJECTED
            document.save(update_fields=['status', 'updated_at'])

            history_comment = "Hujjat rad etildi"
            if comment:
                history_comment += f". Sabab: {comment}"
            self._record_history(document, old_status, document.status, manager, history_comment)

            notify_user(document.owner, document, Notification.Type.DOCUMENT_REJECTED, f"❌ Hujjatingiz rad etildi: \"{document.title}\"")
            return "Hujjat rad etildi va fuqaroga xabar yuborildi."

        raise ValidationError("Noma'lum qaror.")

    @transaction.atomic
    def dispatch_document(self, document, secretary):
        """Hujjatni fuqaroga yuborish (Dispatch)"""
        document.refresh_from_db()
        if document.status != Document.Status.WAITING_FOR_DISPATCH:
            raise ValidationError(f"'{document.get_status_display()}' holatidagi hujjatni yuborib bo'lmaydi.")

        old_status = document.status
        document.status = Document.Status.APPROVED
        document.save(update_fields=['status', 'updated_at'])

        self._record_history(document, old_status, document.status, secretary, "Hujjat yuborildi")

        notify_user(document.owner, document, Notification.Type.DOCUMENT_DISPATCHED, f"📬 Hujjatingiz yuborildi: \"{document.title}\"")
        return "Hujjat muvaffaqiyatli yuborildi."

    @transaction.atomic
    def delete_review(self, document, reviewer):
        """Tahrizchi o'z tahrizini o'chirishi"""
        try:
            assignment = DocumentAssignment.objects.select_for_update().get(
                document=document, reviewer=reviewer
            )
            review = Review.objects.get(document=document, reviewer=reviewer)
        except (DocumentAssignment.DoesNotExist, Review.DoesNotExist):
            raise ValidationError("Tahriz topilmadi yoki siz bunga biriktirilmagansiz")

        document.refresh_from_db()
        if assignment.manager_decision != DocumentAssignment.ManagerDecision.PENDING:
            raise ValidationError("Tahriz ko'rib chiqilgan, uni endi o'chirib bo'lmaydi.")

        review.delete()
        assignment.status = DocumentAssignment.AssignmentStatus.IN_PROGRESS
        assignment.save(update_fields=['status', 'updated_at'])

        if document.status == Document.Status.REVIEWED:
            old_status = document.status
            document.status = Document.Status.UNDER_REVIEW
            document.save(update_fields=['status', 'updated_at'])
            self._record_history(document, old_status, document.status, reviewer, "Tahriz o'chirildi, hujjat qayta tahrizga qaytarildi")
        else:
            self._record_history(document, document.status, document.status, reviewer, "Tahriz o'chirildi")
        
        return "Tahriz muvaffaqiyatli o'chirildi"
