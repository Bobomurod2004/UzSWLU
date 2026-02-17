import logging
from django.db.models import Count, Q
from rest_framework import viewsets, permissions, status, decorators
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes
from .models import Category, Document, DocumentAssignment, Review, DocumentHistory
from .serializers import (
    CategorySerializer, DocumentSerializer, DocumentCreateSerializer,
    DocumentAssignReviewersSerializer, ReviewSerializer, DocumentAssignmentSerializer
)
from .permissions import IsCitizen, IsSecretary, IsManager, IsReviewer, IsSuperAdmin

logger = logging.getLogger('django')

# ---- Status o'tish qoidalari ----
# assign_reviewer: NEW/PENDING/UNDER_REVIEW → PENDING (yoki joriy holatda qoladi)
# start_review:    PENDING → UNDER_REVIEW (yoki allaqachon UNDER_REVIEW)
# submit_review:   UNDER_REVIEW → status context ga qarab
# finalize:        REVIEWED → APPROVED/REJECTED

FINALIZE_ALLOWED_FROM = [Document.Status.REVIEWED]


def _record_history(document, old_status, new_status, user, comment=None):
    """DocumentHistory yozuvini yaratish"""
    DocumentHistory.objects.create(
        document=document,
        user=user,
        old_status=old_status,
        new_status=new_status,
        comment=comment or "Status o'zgardi"
    )


@extend_schema(
    tags=['Categories'],
    summary="Hujjat kategoriyalari ro'yxati",
    description="Tizimdagi mavjud hujjat turlari (kategoriyalari) ni ko'rish. Daraxtsimon (MPTT) tuzilishga ega."
)
class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['parent', 'level']
    search_fields = ['name']


@extend_schema(tags=['Documents'])
class DocumentViewSet(viewsets.ModelViewSet):
    """
    Hujjatlarni boshqarishning asosiy ViewSet'i.
    - CITIZEN: Faqat o'z hujjatlari (yaratish, o'chirish faqat NEW holatda)
    - SECRETARY/MANAGER/SUPERADMIN: Barcha hujjatlar
    - REVIEWER: Unga biriktirilgan hujjatlar
    Bitta hujjat bir nechta tahrizchiga biriktirilishi mumkin.
    """
    serializer_class = DocumentSerializer
    filterset_fields = ['status', 'category', 'owner']
    search_fields = ['title', 'owner__email']
    ordering_fields = ['created_at', 'updated_at', 'title']

    def get_permissions(self):
        if self.action == 'create':
            return [IsCitizen()]
        if self.action in ('update', 'partial_update', 'destroy'):
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated()]

    def get_serializer_class(self):
        if self.action == 'create':
            return DocumentCreateSerializer
        return DocumentSerializer

    def get_queryset(self):
        user = self.request.user
        base_qs = Document.objects.select_related(
            'owner', 'category'
        ).prefetch_related(
            'assignments__reviewer',
            'assignments__assigned_by',
            'reviews__reviewer',
            'history__user',
        )

        if user.role == 'CITIZEN':
            return base_qs.filter(owner=user)
        elif user.role in ['SECRETARY', 'MANAGER', 'SUPERADMIN']:
            return base_qs.all()
        elif user.role == 'REVIEWER':
            return base_qs.filter(assignments__reviewer=user).distinct()
        return Document.objects.none()

    def perform_create(self, serializer):
        doc = serializer.save()
        _record_history(doc, None, doc.status, self.request.user, "Hujjat yaratildi")
        logger.info(f"Document #{doc.id} created by {self.request.user.email}")

    def update(self, request, *args, **kwargs):
        document = self.get_object()
        if request.user.role == 'CITIZEN':
            if document.owner != request.user:
                return Response(
                    {"error": "Siz faqat o'z hujjatingizni tahrirlashingiz mumkin"},
                    status=status.HTTP_403_FORBIDDEN
                )
            if document.status != Document.Status.NEW:
                return Response(
                    {"error": "Faqat 'Yangi' holatdagi hujjatni tahrirlash mumkin"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        elif request.user.role not in ['MANAGER', 'SECRETARY', 'SUPERADMIN']:
            return Response(
                {"error": "Sizda tahrirlash huquqi yo'q"},
                status=status.HTTP_403_FORBIDDEN
            )
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        document = self.get_object()
        if request.user.role == 'CITIZEN':
            if document.owner != request.user:
                return Response(
                    {"error": "Siz faqat o'z hujjatingizni o'chirishingiz mumkin"},
                    status=status.HTTP_403_FORBIDDEN
                )
            if document.status != Document.Status.NEW:
                return Response(
                    {"error": "Faqat 'Yangi' holatdagi hujjatni o'chirish mumkin"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        elif request.user.role not in ['MANAGER', 'SUPERADMIN']:
            return Response(
                {"error": "Sizda o'chirish huquqi yo'q"},
                status=status.HTTP_403_FORBIDDEN
            )
        return super().destroy(request, *args, **kwargs)

    # -------- STATS --------
    @extend_schema(
        summary="Rolga asoslangan statistika",
        description="Foydalanuvchining tizimdagi roliga mos hujjatlar soni va holatlari.",
        responses={200: OpenApiTypes.OBJECT}
    )
    @decorators.action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def stats(self, request):
        user = request.user

        if user.role == 'CITIZEN':
            qs = Document.objects.filter(owner=user)
        elif user.role in ['SECRETARY', 'MANAGER', 'SUPERADMIN']:
            qs = Document.objects.all()
        elif user.role == 'REVIEWER':
            qs = Document.objects.filter(assignments__reviewer=user).distinct()
        else:
            return Response({})

        data = qs.aggregate(
            total=Count('id'),
            new=Count('id', filter=Q(status=Document.Status.NEW)),
            pending=Count('id', filter=Q(status=Document.Status.PENDING)),
            under_review=Count('id', filter=Q(status=Document.Status.UNDER_REVIEW)),
            reviewed=Count('id', filter=Q(status=Document.Status.REVIEWED)),
            approved=Count('id', filter=Q(status=Document.Status.APPROVED)),
            rejected=Count('id', filter=Q(status=Document.Status.REJECTED)),
        )
        return Response(data)

    # -------- ASSIGN REVIEWERS (bir nechta tahrizchi) --------
    @extend_schema(
        summary="Tahrizchilarni biriktirish",
        description=(
            "Hujjatga bir yoki bir nechta tahrizchi biriktirish. "
            "Faqat Rais yoki Kotib bajara oladi. "
            "NEW, PENDING yoki UNDER_REVIEW holatida biriktirish mumkin. "
            "Yangi tahrizchilar qo'shilishi mumkin, allaqachon biriktirilganlar o'tkazib yuboriladi."
        ),
        request=DocumentAssignReviewersSerializer,
        responses={200: DocumentSerializer, 400: 'Xato'}
    )
    @decorators.action(detail=True, methods=['post'], permission_classes=[IsManager | IsSecretary])
    def assign_reviewer(self, request, pk=None):
        document = self.get_object()

        # Faqat NEW, PENDING, UNDER_REVIEW holatda biriktirish mumkin
        allowed_statuses = [
            Document.Status.NEW,
            Document.Status.PENDING,
            Document.Status.UNDER_REVIEW,
        ]
        if document.status not in allowed_statuses:
            return Response(
                {"error": f"'{document.get_status_display()}' holatida tahrizchi biriktirish mumkin emas."},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = DocumentAssignReviewersSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        reviewers = serializer.validated_data['reviewers']
        created_count = 0
        skipped = []

        for reviewer in reviewers:
            assignment, created = DocumentAssignment.objects.get_or_create(
                document=document,
                reviewer=reviewer,
                defaults={'assigned_by': request.user}
            )
            if created:
                created_count += 1
            else:
                skipped.append(reviewer.email)

        if created_count == 0:
            return Response(
                {"error": "Barcha tanlangan tahrizchilar allaqachon biriktirilgan.",
                 "skipped": skipped},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Agar hujjat hali NEW bo'lsa, PENDING ga o'tkazish
        old_status = document.status
        if document.status == Document.Status.NEW:
            document.status = Document.Status.PENDING
            document.save(update_fields=['status', 'updated_at'])

        reviewer_names = ", ".join(r.email for r in reviewers)
        _record_history(
            document, old_status, document.status, request.user,
            f"Tahrizchi(lar) biriktirildi: {reviewer_names}"
        )
        logger.info(
            f"Document #{document.id}: {created_count} reviewer(s) assigned by {request.user.email}"
        )

        doc = Document.objects.prefetch_related(
            'assignments__reviewer', 'assignments__assigned_by',
            'reviews__reviewer', 'history__user'
        ).select_related('owner', 'category').get(pk=document.pk)

        return Response(DocumentSerializer(doc).data)

    # -------- START REVIEW --------
    @extend_schema(
        summary="Tahrizni boshlash",
        description="Tahrizchi ishni boshlaganini tizimga bildirish. Uning assignment holati IN_PROGRESS bo'ladi.",
        responses={200: DocumentSerializer, 403: 'Ruxsat etilmagan'}
    )
    @decorators.action(detail=True, methods=['post'], permission_classes=[IsReviewer])
    def start_review(self, request, pk=None):
        document = self.get_object()

        # Ushbu tahrizchining assignment ini topish
        try:
            assignment = DocumentAssignment.objects.get(
                document=document, reviewer=request.user
            )
        except DocumentAssignment.DoesNotExist:
            return Response(
                {"error": "Siz bu hujjatga biriktirilmagansiz"},
                status=status.HTTP_403_FORBIDDEN
            )

        if assignment.status != DocumentAssignment.AssignmentStatus.PENDING:
            return Response(
                {"error": f"Sizning biriktirmangiz '{assignment.get_status_display()}' holatida. "
                          f"Faqat 'Kutilmoqda' holatida boshlash mumkin."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Assignment ni IN_PROGRESS ga o'tkazish
        assignment.status = DocumentAssignment.AssignmentStatus.IN_PROGRESS
        assignment.save(update_fields=['status', 'updated_at'])

        # Hujjat statusini UNDER_REVIEW ga o'tkazish (agar hali bo'lmasa)
        old_status = document.status
        if document.status == Document.Status.PENDING:
            document.status = Document.Status.UNDER_REVIEW
            document.save(update_fields=['status', 'updated_at'])

        _record_history(
            document, old_status, document.status, request.user,
            f"Tahriz boshlandi ({request.user.email})"
        )
        logger.info(f"Document #{document.id} review started by {request.user.email}")

        doc = Document.objects.prefetch_related(
            'assignments__reviewer', 'reviews__reviewer', 'history__user'
        ).select_related('owner', 'category').get(pk=document.pk)
        return Response(DocumentSerializer(doc).data)

    # -------- SUBMIT REVIEW --------
    @extend_schema(
        summary="Tahriz PDF yuklash",
        description=(
            "Tahrizchi o'z xulosasini (PDF) yuklaydi. "
            "Barcha biriktirilgan tahrizchilar ishini tugatsa, hujjat REVIEWED holatiga o'tadi."
        ),
        request=ReviewSerializer,
        responses={201: ReviewSerializer, 403: 'Ruxsat etilmagan', 400: 'Xato'}
    )
    @decorators.action(detail=True, methods=['post'], permission_classes=[IsReviewer])
    def submit_review(self, request, pk=None):
        document = self.get_object()

        # Assignment tekshiruvi
        try:
            assignment = DocumentAssignment.objects.get(
                document=document, reviewer=request.user
            )
        except DocumentAssignment.DoesNotExist:
            return Response(
                {"error": "Siz bu hujjatga biriktirilmagansiz"},
                status=status.HTTP_403_FORBIDDEN
            )

        if assignment.status == DocumentAssignment.AssignmentStatus.COMPLETED:
            return Response(
                {"error": "Siz bu hujjat uchun allaqachon tahriz yuborgansiz."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if assignment.status == DocumentAssignment.AssignmentStatus.PENDING:
            return Response(
                {"error": "Avval tahrizni boshlang (start_review)."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Duplikat review tekshiruvi
        if Review.objects.filter(document=document, reviewer=request.user).exists():
            return Response(
                {"error": "Siz bu hujjat uchun allaqachon tahriz yuborgansiz."},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = ReviewSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(document=document, reviewer=request.user)

            # Assignment ni COMPLETED ga o'tkazish
            assignment.status = DocumentAssignment.AssignmentStatus.COMPLETED
            assignment.save(update_fields=['status', 'updated_at'])

            # Barcha assignment lar tugadimi tekshirish
            old_status = document.status
            if document.all_assignments_completed:
                document.status = Document.Status.REVIEWED
                document.save(update_fields=['status', 'updated_at'])
                _record_history(
                    document, old_status, document.status, request.user,
                    "Barcha tahrizchilar ishini tugatdi — hujjat tahrizlandi"
                )
            else:
                _record_history(
                    document, old_status, document.status, request.user,
                    f"Tahriz yuklandi ({request.user.email})"
                )

            logger.info(f"Document #{document.id} reviewed by {request.user.email}")
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # -------- FINALIZE --------
    @extend_schema(
        summary="Yakuniy qaror (Tasdiqlash/Rad etish)",
        description="Rais hujjatni tasdiqlaydi yoki rad etadi. Hujjat REVIEWED holatda bo'lishi kerak.",
        request={'application/json': {'type': 'object', 'properties': {'decision': {'type': 'string', 'enum': ['APPROVE', 'REJECT']}}}},
        responses={200: {'type': 'object'}, 400: 'Xato'}
    )
    @decorators.action(detail=True, methods=['post'], permission_classes=[IsManager])
    def finalize(self, request, pk=None):
        document = self.get_object()
        decision = request.data.get('decision')

        if decision == 'APPROVE':
            new_status = Document.Status.APPROVED
        elif decision == 'REJECT':
            new_status = Document.Status.REJECTED
        else:
            return Response(
                {"error": "Noto'g'ri qaror. 'APPROVE' yoki 'REJECT' yuboring."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if document.status not in FINALIZE_ALLOWED_FROM:
            return Response(
                {"error": f"'{document.get_status_display()}' holatidagi hujjatda qaror qabul qilib bo'lmaydi. "
                          f"Hujjat 'Tahrizlandi' holatida bo'lishi kerak."},
                status=status.HTTP_400_BAD_REQUEST
            )

        old_status = document.status
        document.status = new_status
        document.save(update_fields=['status', 'updated_at'])

        comment = "Hujjat tasdiqlandi" if decision == 'APPROVE' else "Hujjat qaytarildi"
        _record_history(document, old_status, document.status, request.user, comment)
        logger.info(f"Document #{document.id} {decision.lower()}d by {request.user.email}")

        return Response({
            "status": f"Hujjat holati o'zgardi: {document.get_status_display()}"
        })
