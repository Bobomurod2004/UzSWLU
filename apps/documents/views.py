import logging
from django.db import transaction
from django.db.models import Count, Q
from rest_framework import viewsets, permissions, status, decorators
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiTypes
from .models import (
    Category, Document, DocumentAssignment,
    Review, DocumentHistory,
)
from .serializers import (
    CategorySerializer, DocumentSerializer,
    DocumentCreateSerializer,
    DocumentAssignReviewersSerializer, ReviewSerializer,
    DocumentStatsSerializer, FinalizeRequestSerializer,
    FinalizeResponseSerializer,
)
from .permissions import (
    IsCitizen, IsSecretary, IsManager, IsReviewer, IsSuperAdmin,
)
from apps.accounts.serializers import ErrorResponseSerializer

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


@extend_schema(tags=['Categories'])
class CategoryViewSet(viewsets.ModelViewSet):
    """
    Hujjat kategoriyalarini boshqarish.
    - Barcha foydalanuvchilar: Faqat o'qish (list, retrieve)
    - SUPERADMIN: To'liq boshqarish (create, update, delete)
    MPTT (Modified Preorder Tree Traversal) asosida
    daraxtsimon tuzilishga ega.
    """
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    filterset_fields = ['parent', 'level']
    search_fields = ['name']

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsSuperAdmin()]
        return [permissions.IsAuthenticated()]

    @extend_schema(
        summary="Barcha kategoriyalar ro'yxati",
        description=(
            "Tizimdagi barcha hujjat kategoriyalarini "
            "(turlarini) qaytaradi.\n\n"
            "**Daraxtsimon tuzilish (MPTT):**\n"
            "- Har bir kategoriya ota-kategoriyaga (`parent`) "
            "bog'langan bo'lishi mumkin\n"
            "- `level` — daraxtdagi chuqurligi "
            "(0 = ildiz, 1 = pastki, ...)\n"
            "- `lft`, `rght`, `tree_id` — MPTT navigatsiya "
            "maydonlari\n\n"
            "**Filtrlash:**\n"
            "- `parent` — faqat ma'lum ota-kategoriyaning "
            "bolalarini olish (ID)\n"
            "- `parent=null` — faqat ildiz kategoriyalarni\n"
            "- `level` — faqat ma'lum chuqurlikdagilarni\n\n"
            "**Qidirish:** `search=<nomi>` — kategoriya nomi "
            "bo'yicha qidirish\n\n"
            "**Ruxsat:** Barcha autentifikatsiya qilingan "
            "foydalanuvchilar"
        ),
        responses={200: CategorySerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        summary="Bitta kategoriyaning tafsilotlari",
        description=(
            "ID bo'yicha bitta kategoriyaning to'liq "
            "ma'lumotlarini qaytaradi:\n\n"
            "- `id` — kategoriya identifikatori\n"
            "- `name` — kategoriya nomi\n"
            "- `parent` — ota-kategoriya ID si "
            "(ildiz uchun `null`)\n"
            "- `level` — daraxtdagi chuqurligi\n\n"
            "**Ruxsat:** Barcha autentifikatsiya qilingan "
            "foydalanuvchilar"
        ),
        responses={
            200: CategorySerializer,
            404: ErrorResponseSerializer,
        },
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        summary="Yangi kategoriya yaratish",
        description=(
            "Yangi hujjat kategoriyasini yaratadi.\n\n"
            "**Majburiy maydonlar:**\n"
            "- `name` — kategoriya nomi\n\n"
            "**Ixtiyoriy maydonlar:**\n"
            "- `parent` — ota-kategoriya ID si\n\n"
            "**Ruxsat:** Faqat SUPERADMIN"
        ),
        request=CategorySerializer,
        responses={
            201: CategorySerializer,
            400: ErrorResponseSerializer,
        },
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @extend_schema(
        summary="Kategoriyani to'liq yangilash (PUT)",
        description=(
            "ID bo'yicha kategoriyani to'liq yangilaydi.\n\n"
            "**Ruxsat:** Faqat SUPERADMIN"
        ),
        request=CategorySerializer,
        responses={
            200: CategorySerializer,
            400: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @extend_schema(
        summary="Kategoriyani qisman yangilash (PATCH)",
        description=(
            "ID bo'yicha kategoriyani qisman yangilaydi.\n\n"
            "**Ruxsat:** Faqat SUPERADMIN"
        ),
        request=CategorySerializer,
        responses={
            200: CategorySerializer,
            400: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @extend_schema(
        summary="Kategoriyani o'chirish",
        description=(
            "ID bo'yicha kategoriyani o'chiradi.\n\n"
            "**Eslatma:** Agar kategoriyada hujjatlar bo'lsa, "
            "o'chirib bo'lmasligi mumkin (Protect).\n\n"
            "**Ruxsat:** Faqat SUPERADMIN"
        ),
        responses={
            204: None,
            400: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)


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
    parser_classes = [MultiPartParser, FormParser]
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
        # Swagger schema generatsiyasida AnonymousUser xatolikni oldini olish
        if getattr(self, 'swagger_fake_view', False):
            return Document.objects.none()

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
            return base_qs.filter(
                assignments__reviewer=user
            ).distinct()
        return Document.objects.none()

    # -------- LIST --------
    @extend_schema(
        summary="Hujjatlar ro'yxatini olish",
        description=(
            "Foydalanuvchi roliga qarab hujjatlar ro'yxatini "
            "sahifalab (paginated) qaytaradi.\n\n"
            "**Rolga qarab ko'rinadigan hujjatlar:**\n"
            "- **CITIZEN** — faqat o'zi yuborgan hujjatlar\n"
            "- **REVIEWER** — faqat unga biriktirilgan "
            "hujjatlar\n"
            "- **SECRETARY / MANAGER / SUPERADMIN** — "
            "barcha hujjatlar\n\n"
            "**Filtrlash (filter):**\n"
            "- `status` — NEW, PENDING, UNDER_REVIEW, "
            "REVIEWED, APPROVED, REJECTED\n"
            "- `category` — kategoriya ID si\n"
            "- `owner` — hujjat egasining ID si\n\n"
            "**Qidirish (search):**\n"
            "- `title` — hujjat nomi bo'yicha\n"
            "- `owner__email` — egasining emaili bo'yicha\n\n"
            "**Tartiblash (ordering):**\n"
            "- `created_at`, `updated_at`, `title`\n\n"
            "**Javob:** Har bir hujjat bilan birga "
            "biriktirilgan tahrizchilar, tahrizlar va "
            "tarix ham qaytariladi."
        ),
        responses={200: DocumentSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    # -------- RETRIEVE --------
    @extend_schema(
        summary="Bitta hujjatning to'liq ma'lumotlari",
        description=(
            "ID bo'yicha bitta hujjatning barcha "
            "tafsilotlarini qaytaradi:\n\n"
            "- **Asosiy ma'lumotlar:** nomi, fayl, "
            "kategoriya, holati, yaratilgan sana\n"
            "- **Egasi:** hujjatni yuborgan foydalanuvchi\n"
            "- **Biriktirmalar (assignments):** qaysi "
            "tahrizchilarga biriktirilgani, kim biriktirgan "
            "va har birining holati (PENDING / IN_PROGRESS / "
            "COMPLETED)\n"
            "- **Tahrizlar (reviews):** tahrizchilar "
            "yuborgan PDF xulosa, ball va izoh\n"
            "- **Tarix (history):** hujjat holati qachon "
            "va kim tomonidan o'zgartirilgani\n\n"
            "**Ruxsat:** Faqat o'z hujjatini (CITIZEN), "
            "biriktirilgan hujjatni (REVIEWER) yoki barcha "
            "hujjatlarni (SECRETARY/MANAGER/SUPERADMIN) "
            "ko'rish mumkin."
        ),
        responses={
            200: DocumentSerializer,
            404: ErrorResponseSerializer,
        },
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    # -------- CREATE --------
    @extend_schema(
        summary="Yangi hujjat yuborish",
        description=(
            "Fuqaro (CITIZEN) yangi hujjatni tizimga "
            "yuboradi. Hujjat avtomatik ravishda 'Yangi' "
            "(NEW) holatida yaratiladi.\n\n"
            "**Majburiy maydonlar:**\n"
            "- `title` — hujjat nomi\n"
            "- `file` — PDF formatdagi fayl (maksimum "
            "10 MB, faqat haqiqiy PDF qabul qilinadi)\n"
            "- `category` — hujjat kategoriyasi ID si\n\n"
            "**Avtomatik belgilanadi:**\n"
            "- `owner` — joriy foydalanuvchi\n"
            "- `status` — NEW (Yangi)\n\n"
            "**Hujjat hayot sikli:**\n"
            "NEW → PENDING (tahrizchi biriktirilganda) → "
            "UNDER_REVIEW (tahriz boshlanganda) → "
            "REVIEWED (barcha tahrizlar tugaganda) → "
            "APPROVED yoki REJECTED (rais qaror qilganda)\n\n"
            "**Ruxsat:** Faqat CITIZEN"
        ),
        request={
            'multipart/form-data': DocumentCreateSerializer,
        },
        responses={
            201: DocumentSerializer,
            400: ErrorResponseSerializer,
        },
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        doc = serializer.save()
        _record_history(
            doc, None, doc.status,
            self.request.user, "Hujjat yaratildi"
        )
        logger.info(
            "Document #%s created by %s",
            doc.id, self.request.user.email
        )

    # -------- UPDATE --------
    @extend_schema(
        summary="Hujjatni to'liq tahrirlash (PUT)",
        description=(
            "Hujjatning barcha maydonlarini bir vaqtda "
            "yangilaydi.\n\n"
            "**CITIZEN uchun qoidalar:**\n"
            "- Faqat o'z hujjatini tahrirlay oladi\n"
            "- Faqat 'Yangi' (NEW) holatdagi hujjatni "
            "tahrirlash mumkin\n"
            "- Boshqa holatdagi hujjatni o'zgartirib "
            "bo'lmaydi\n\n"
            "**SECRETARY / MANAGER / SUPERADMIN:**\n"
            "- Istalgan hujjatni istalgan holatda "
            "tahrirlay oladi\n\n"
            "**REVIEWER:** tahrirlash huquqi yo'q\n\n"
            "**Ruxsat:** CITIZEN (o'ziniki, faqat NEW), "
            "MANAGER, SECRETARY, SUPERADMIN"
        ),
        request=DocumentSerializer,
        responses={
            200: DocumentSerializer,
            400: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
        },
    )
    def update(self, request, *args, **kwargs):
        document = self.get_object()
        if request.user.role == 'CITIZEN':
            if document.owner != request.user:
                return Response(
                    {"error": "Siz faqat o'z hujjatingizni "
                     "tahrirlashingiz mumkin"},
                    status=status.HTTP_403_FORBIDDEN
                )
            if document.status != Document.Status.NEW:
                return Response(
                    {"error": "Faqat 'Yangi' holatdagi "
                     "hujjatni tahrirlash mumkin"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        elif request.user.role not in [
            'MANAGER', 'SECRETARY', 'SUPERADMIN'
        ]:
            return Response(
                {"error": "Sizda tahrirlash huquqi yo'q"},
                status=status.HTTP_403_FORBIDDEN
            )
        return super().update(request, *args, **kwargs)

    # -------- PARTIAL UPDATE --------
    @extend_schema(
        summary="Hujjatni qisman tahrirlash (PATCH)",
        description=(
            "Hujjatning faqat yuborilgan maydonlarini "
            "yangilaydi. Barcha maydonni yuborish shart "
            "emas — faqat o'zgartirmoqchi bo'lganlarni "
            "yuboring.\n\n"
            "**Misol:** Faqat nomini o'zgartirish uchun "
            "`{\"title\": \"Yangi nom\"}` yuborish "
            "kifoya.\n\n"
            "**Ruxsat qoidalari:** PUT bilan bir xil — "
            "CITIZEN faqat o'ziniki va faqat NEW holatda."
        ),
        request=DocumentSerializer,
        responses={
            200: DocumentSerializer,
            400: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
        },
    )
    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)

    # -------- DESTROY --------
    @extend_schema(
        summary="Hujjatni o'chirish (Soft Delete)",
        description=(
            "Hujjatni tizimdan o'chiradi. Bu soft delete — "
            "hujjat bazadan o'chirilmaydi, faqat "
            "`is_active=false` va `deleted_at` "
            "belgilanadi.\n\n"
            "**CITIZEN uchun qoidalar:**\n"
            "- Faqat o'z hujjatini o'chira oladi\n"
            "- Faqat 'Yangi' (NEW) holatdagi hujjatni "
            "o'chirish mumkin\n"
            "- Agar hujjat tahrizga yuborilgan bo'lsa, "
            "o'chirib bo'lmaydi\n\n"
            "**MANAGER / SUPERADMIN:**\n"
            "- Istalgan hujjatni o'chira oladi\n\n"
            "**Ruxsat:** CITIZEN (o'ziniki, faqat NEW), "
            "MANAGER, SUPERADMIN"
        ),
        responses={
            204: None,
            400: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
        },
    )
    def destroy(self, request, *args, **kwargs):
        document = self.get_object()
        if request.user.role == 'CITIZEN':
            if document.owner != request.user:
                return Response(
                    {"error": "Siz faqat o'z hujjatingizni "
                     "o'chirishingiz mumkin"},
                    status=status.HTTP_403_FORBIDDEN
                )
            if document.status != Document.Status.NEW:
                return Response(
                    {"error": "Faqat 'Yangi' holatdagi "
                     "hujjatni o'chirish mumkin"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        elif request.user.role not in ['MANAGER', 'SUPERADMIN']:
            return Response(
                {"error": "Sizda o'chirish huquqi yo'q"},
                status=status.HTTP_403_FORBIDDEN
            )
        # Soft delete — bazadan o'chirmaydi, faqat belgilaydi
        document.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # -------- STATS --------
    @extend_schema(
        summary="Rolga asoslangan statistika",
        description=(
            "Joriy foydalanuvchi ko'ra oladigan hujjatlar "
            "bo'yicha yig'ma hisobot qaytaradi.\n\n"
            "**Qaytariladigan maydonlar:**\n"
            "- `total` — jami hujjatlar soni\n"
            "- `new` — yangi (NEW) holatdagi\n"
            "- `pending` — tahrizchi biriktirilgan (PENDING)\n"
            "- `under_review` — tahrizda (UNDER_REVIEW)\n"
            "- `reviewed` — tahrizlangan (REVIEWED)\n"
            "- `approved` — tasdiqlangan (APPROVED)\n"
            "- `rejected` — qaytarilgan (REJECTED)\n\n"
            "**Rolga qarab ma'lumot doirasi:**\n"
            "- **CITIZEN** — faqat o'z hujjatlari sonini ko'radi\n"
            "- **REVIEWER** — biriktirilgan hujjatlari sonini\n"
            "- **SECRETARY / MANAGER / SUPERADMIN** — barcha "
            "hujjatlar statistikasini ko'radi\n\n"
            "**Ishlash tartibi:** "
            "SQL `COUNT` aggregation — barchasi bitta so'rov bilan."
        ),
        responses={200: DocumentStatsSerializer},
    )
    @decorators.action(
        detail=False,
        methods=['get'],
        permission_classes=[permissions.IsAuthenticated],
    )
    def stats(self, request):
        """get_queryset() dan foydalanib N+1 query oldini olish"""
        qs = self.get_queryset().only('id', 'status')

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
            "Hujjatga bir yoki bir nechta tahrizchini "
            "biriktiradi. Bu hujjat hayot siklining "
            "muhim bosqichi.\n\n"
            "**So'rov tanasi:**\n"
            "```json\n"
            "{\"reviewers\": [1, 5, 12]}\n"
            "```\n"
            "— `reviewers` — REVIEWER rolidagi foydalanuvchi "
            "ID lari ro'yxati\n\n"
            "**Qoidalar:**\n"
            "- Hujjat NEW, PENDING yoki UNDER_REVIEW holatida "
            "bo'lishi kerak\n"
            "- Agar tahrizchi allaqachon biriktirilgan bo'lsa, "
            "u o'tkazib yuboriladi (duplikat hosil bo'lmaydi)\n"
            "- Agar barcha tanlangan tahrizchilar "
            "allaqachon biriktirilgan bo'lsa, `400` xatosi\n"
            "- Yangi biriktirmalar PENDING holatida yaratiladi\n\n"
            "**Status o'zgarishi:**\n"
            "- Hujjat NEW holatda bo'lsa → avtomatik PENDING ga "
            "o'tkaziladi\n"
            "- PENDING yoki UNDER_REVIEW bo'lsa → status "
            "o'zgarmaydi\n\n"
            "**Ruxsat:** Faqat MANAGER va SECRETARY"
        ),
        request=DocumentAssignReviewersSerializer,
        responses={
            200: DocumentSerializer,
            400: ErrorResponseSerializer,
        },
    )
    @decorators.action(
        detail=True,
        methods=['post'],
        permission_classes=[IsManager | IsSecretary],
    )
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
            "Tahrizchi(lar) biriktirildi: %s" % reviewer_names
        )
        logger.info(
            "Document #%s: %s reviewer(s) assigned by %s",
            document.id, created_count, request.user.email
        )

        doc = Document.objects.prefetch_related(
            'assignments__reviewer', 'assignments__assigned_by',
            'reviews__reviewer', 'history__user'
        ).select_related('owner', 'category').get(pk=document.pk)

        return Response(DocumentSerializer(doc).data)

    # -------- START REVIEW --------
    @extend_schema(
        summary="Tahrizni boshlash",
        description=(
            "Tahrizchi (REVIEWER) hujjatni ko'rib chiqishni "
            "boshlaganini tizimga bildiradi.\n\n"
            "**So'rov tanasi kerak emas** — bo'sh POST "
            "yuborish kifoya.\n\n"
            "**Qoidalar:**\n"
            "- Tahrizchi hujjatga biriktirilgan bo'lishi kerak\n"
            "- Uning biriktirmasi (assignment) PENDING holatda "
            "bo'lishi kerak\n"
            "- Agar allaqachon IN_PROGRESS yoki COMPLETED bo'lsa, "
            "`400` xatosi qaytariladi\n\n"
            "**Status o'zgarishlari:**\n"
            "- Assignment: PENDING → IN_PROGRESS\n"
            "- Hujjat: Agar PENDING bo'lsa → UNDER_REVIEW ga\n\n"
            "**Jarayon:** Tahrizchi boshlaydi → hujjatni "
            "ko'rib chiqadi → `submit_review` orqali xulosasini "
            "yuboradi\n\n"
            "**Ruxsat:** Faqat REVIEWER (o'zi biriktirilgan "
            "hujjat uchun)"
        ),
        request=None,
        responses={
            200: DocumentSerializer,
            400: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
        },
    )
    @decorators.action(
        detail=True,
        methods=['post'],
        permission_classes=[IsReviewer],
    )
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
            "Tahriz boshlandi (%s)" % request.user.email
        )
        logger.info("Document #%s review started by %s", document.id, request.user.email)

        doc = Document.objects.prefetch_related(
            'assignments__reviewer', 'reviews__reviewer', 'history__user'
        ).select_related('owner', 'category').get(pk=document.pk)
        return Response(DocumentSerializer(doc).data)

    # -------- SUBMIT REVIEW --------
    @extend_schema(
        summary="Tahriz xulosasini yuklash (PDF)",
        description=(
            "Tahrizchi o'z ko'rib chiqish xulosasini "
            "PDF fayl ko'rinishida yuklaydi.\n\n"
            "**So'rov maydonlari (multipart/form-data):**\n"
            "- `review_file` — tahriz xulosasi PDF fayli "
            "(majburiy, maks 10 MB)\n"
            "- `score` — ball (ixtiyoriy, 0-100)\n"
            "- `comment` — izoh (ixtiyoriy)\n\n"
            "**Qoidalar:**\n"
            "- Tahrizchi biriktirilgan bo'lishi kerak\n"
            "- `start_review` avval chaqirilgan bo'lishi kerak "
            "(assignment IN_PROGRESS holatida)\n"
            "- Bir tahrizchi bitta hujjatga faqat bitta tahriz "
            "yubora oladi (duplikat bo'lmaydi)\n\n"
            "**Avtomatik status o'zgarishlari:**\n"
            "- Assignment: IN_PROGRESS → COMPLETED\n"
            "- Hujjat: Agar **barcha** biriktirilgan "
            "tahrizchilar ishini tugatsa → REVIEWED holatiga "
            "o'tadi\n\n"
            "**Xavfsizlik:** `select_for_update` va "
            "`transaction.atomic` orqali race condition "
            "oldini olingan — bir vaqtda bir nechta tahrizchi "
            "yuborsa ham to'g'ri ishlaydi.\n\n"
            "**Ruxsat:** Faqat REVIEWER (o'zi biriktirilgan "
            "hujjat uchun)"
        ),
        request={
            'multipart/form-data': ReviewSerializer,
        },
        responses={
            201: ReviewSerializer,
            400: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
        },
    )
    @decorators.action(
        detail=True,
        methods=['post'],
        permission_classes=[IsReviewer],
        parser_classes=[MultiPartParser, FormParser],
    )
    def submit_review(self, request, pk=None):
        document = self.get_object()

        # Assignment tekshiruvi (select_for_update — race condition oldini olish)
        try:
            assignment = DocumentAssignment.objects.select_for_update().get(
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
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Atomic transaction — race condition oldini olish
        with transaction.atomic():
            serializer.save(document=document, reviewer=request.user)

            # Assignment ni COMPLETED ga o'tkazish
            assignment.status = DocumentAssignment.AssignmentStatus.COMPLETED
            assignment.save(update_fields=['status', 'updated_at'])

            # Barcha assignment lar tugadimi tekshirish
            # select_for_update bilan document ni qayta olish
            doc_locked = Document.objects.select_for_update().get(pk=document.pk)
            old_status = doc_locked.status
            if doc_locked.all_assignments_completed:
                doc_locked.status = Document.Status.REVIEWED
                doc_locked.save(update_fields=['status', 'updated_at'])
                _record_history(
                    doc_locked, old_status, doc_locked.status, request.user,
                    "Barcha tahrizchilar ishini tugatdi — hujjat tahrizlandi"
                )
            else:
                _record_history(
                    doc_locked, old_status, doc_locked.status, request.user,
                    "Tahriz yuklandi (%s)" % request.user.email
                )

        logger.info("Document #%s reviewed by %s", document.id, request.user.email)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    # -------- FINALIZE --------
    @extend_schema(
        summary="Yakuniy qaror — tasdiqlash yoki qaytarish",
        description=(
            "Rais (MANAGER) hujjat bo'yicha yakuniy qaror "
            "qabul qiladi.\n\n"
            "**So'rov tanasi:**\n"
            "```json\n"
            "{\"decision\": \"APPROVE\", \"comment\": \"\"}\n"
            "```\n"
            "yoki\n"
            "```json\n"
            "{\"decision\": \"REJECT\", "
            "\"comment\": \"Xulosa yetarli emas, qaytadan ko'rib chiqing\"}\n"
            "```\n\n"
            "**APPROVE (tasdiqlash):**\n"
            "- Hujjat holati APPROVED ga o'tadi\n"
            "- Fuqaro (CITIZEN) hujjatni barcha tahrizlar "
            "bilan birga ko'ra oladi\n\n"
            "**REJECT (qaytarish):**\n"
            "- Hujjat holati UNDER_REVIEW ga qaytadi\n"
            "- Barcha tahrizchilarning biriktirmalari "
            "IN_PROGRESS holatiga qaytariladi\n"
            "- Eski tahriz fayllari o'chiriladi\n"
            "- Tahrizchilar yangi xulosa yuborishlari kerak\n"
            "- `comment` maydonida rad etish sababi "
            "yoziladi — tahrizchilar tarix orqali ko'ra oladi\n\n"
            "**Qoidalar:**\n"
            "- Hujjat REVIEWED holatida bo'lishi kerak\n\n"
            "**Ruxsat:** Faqat MANAGER"
        ),
        request=FinalizeRequestSerializer,
        responses={
            200: FinalizeResponseSerializer,
            400: ErrorResponseSerializer,
        },
    )
    @decorators.action(
        detail=True,
        methods=['post'],
        permission_classes=[IsManager],
    )
    def finalize(self, request, pk=None):
        document = self.get_object()

        serializer = FinalizeRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        decision = serializer.validated_data['decision']
        comment = serializer.validated_data.get('comment', '')

        if document.status not in FINALIZE_ALLOWED_FROM:
            return Response(
                {"error": f"'{document.get_status_display()}' holatidagi hujjatda qaror qabul qilib bo'lmaydi. "
                          f"Hujjat 'Tahrizlandi' holatida bo'lishi kerak."},
                status=status.HTTP_400_BAD_REQUEST
            )

        old_status = document.status

        if decision == 'APPROVE':
            document.status = Document.Status.APPROVED
            document.save(update_fields=['status', 'updated_at'])

            history_comment = "Hujjat tasdiqlandi"
            if comment:
                history_comment += f" — {comment}"
            _record_history(document, old_status, document.status, request.user, history_comment)

            logger.info("Document #%s approved by %s", document.id, request.user.email)
            return Response({
                "status": "Hujjat tasdiqlandi. Fuqaroga tahriz xulosalari bilan birga yuborildi."
            })

        # ---- REJECT: tahrizchilarga qaytarish ----
        with transaction.atomic():
            # 1) Eski tahrizlarni o'chirish (hard delete — qaytadan yozishi kerak)
            deleted_count, _ = Review.objects.filter(document=document).hard_delete()

            # 2) Barcha assignmentlarni IN_PROGRESS ga qaytarish
            DocumentAssignment.objects.filter(
                document=document
            ).update(
                status=DocumentAssignment.AssignmentStatus.IN_PROGRESS
            )

            # 3) Hujjat statusini UNDER_REVIEW ga qaytarish
            document.status = Document.Status.UNDER_REVIEW
            document.save(update_fields=['status', 'updated_at'])

            history_comment = "Hujjat qaytarildi — tahrizchilar qaytadan ko'rib chiqishi kerak"
            if comment:
                history_comment += f". Sabab: {comment}"
            _record_history(document, old_status, document.status, request.user, history_comment)

        logger.info("Document #%s rejected by %s, %s reviews deleted",
                    document.id, request.user.email, deleted_count)

        return Response({
            "status": (
                f"Hujjat qaytarildi. {deleted_count} ta eski tahriz o'chirildi. "
                f"Tahrizchilar qaytadan xulosa yuborishlari kerak."
            )
        })
