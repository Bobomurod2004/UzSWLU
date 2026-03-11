import logging
from django.db import transaction
from django.db.models import Count, Q
from rest_framework import viewsets, permissions, status, decorators
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
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
    ReviewActionSerializer, ReviewSeenSerializer, FinalizeResponseSerializer,
)
from rest_framework.exceptions import ValidationError as DRFValidationError
from .permissions import (
    IsCitizen, IsSecretary, IsManager, IsSuperAdmin,
    IsManagerOrSecretary, IsAssignedToDocument
)
from apps.accounts.serializers import ErrorResponseSerializer
from apps.notifications.services import notify_user, notify_staff
from apps.notifications.models import Notification
from .services import DocumentService

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


@extend_schema(tags=['Documents: Core'])
class DocumentViewSet(viewsets.ModelViewSet):
    """
    Hujjatlarni boshqarishning asosiy ViewSet'i.

    **Ko'rinish qoidalari:**
    - CITIZEN: O'zi yuborgan va unga tahriz uchun biriktirilgan hujjatlar
    - SECRETARY/MANAGER/SUPERADMIN: Barcha hujjatlar

    **Tahrizchi tizimi:**
    - Har qanday foydalanuvchi tahrizchi sifatida biriktirilishi mumkin
    - Hujjat egasi o'z hujjatiga tahrizchi sifatida biriktirilishi mumkin emas
    - Bitta hujjat bir nechta tahrizchiga biriktirilishi mumkin
    - Kotib va Rais teng huquqlarga ega
    """
    serializer_class = DocumentSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    filterset_fields = ['status', 'category', 'owner']
    search_fields = ['title', 'owner__email']
    ordering_fields = ['created_at', 'updated_at', 'title']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.service = DocumentService()

    def get_permissions(self):
        if self.action == 'create':
            return [IsCitizen()]
        
        # Har bir action uchun o'ziga xos permissionlarni decorator dan olish
        # Agar decorator da ko'rsatilmagan bo'sa, default larni qo'llaymiz
        return super().get_permissions()

    def get_serializer_class(self):
        if self.action == 'create':
            return DocumentCreateSerializer
        return DocumentSerializer

    def get_queryset(self):
        # Swagger schema generatsiyasida AnonymousUser xatolikni oldini olish
        if getattr(self, 'swagger_fake_view', False):
            return Document.objects.none()

        user = self.request.user
        if not user.is_authenticated:
            return Document.objects.none()

        base_qs = Document.objects.select_related(
            'owner', 'category'
        ).prefetch_related(
            'assignments__reviewer',
            'assignments__assigned_by',
            'reviews__reviewer',
            'history__user',
        )

        if user.role == 'CITIZEN':
            # O'z hujjatlari YOKI unga tahrir uchun biriktirilgan hujjatlar
            return base_qs.filter(Q(owner=user) | Q(assignments__reviewer=user)).distinct()
        
        # MANAGER and SECRETARY see all
        return base_qs.all()

    # -------- LIST --------
    @extend_schema(
        tags=['Documents: Core'],
        summary="Hujjatlar ro'yxatini olish",
        description=(
            "Foydalanuvchi roliga qarab hujjatlar ro'yxatini "
            "sahifalab (paginated) qaytaradi.\n\n"
            "**Rolga qarab ko'rinadigan hujjatlar:**\n"
            "- **CITIZEN** — o'zi yuborgan + unga tahriz uchun "
            "biriktirilgan hujjatlar\n"
            "- **SECRETARY / MANAGER / SUPERADMIN** — "
            "barcha hujjatlar\n\n"
            "**Filtrlash:**\n"
            "- `status` — NEW, SEEN, PENDING, UNDER_REVIEW, "
            "REVIEWED, WAITING_FOR_DISPATCH, APPROVED, REJECTED\n"
            "- `category` — kategoriya ID si\n"
            "- `owner` — hujjat egasining ID si\n\n"
            "**Qidirish:** `search=` — `title` yoki `owner__email` bo'yicha\n\n"
            "**Tartiblash:** `ordering=` — `created_at`, `updated_at`, `title`\n\n"
            "**Javob:** Har bir hujjat bilan birga assignments, reviews "
            "va history ham qaytariladi. CITIZEN uchun tahrizchi "
            "ma'lumotlari anonimlashtirigan."
        ),
        responses={200: DocumentSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    # -------- RETRIEVE --------
    @extend_schema(
        tags=['Documents: Core'],
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
            "**Ruxsat:** Faqat o'z hujjatini ko'rish (CITIZEN), "
            "biriktirilgan hujjatni tahrizchi sifatida "
            "ko'rish yoki barcha hujjatlarni "
            "(SECRETARY/MANAGER/SUPERADMIN) ko'rish mumkin."
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
        tags=['Documents: Core'],
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

    @transaction.atomic
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
        # Notification: Fuqaroga "yuborildi"
        notify_user(
            self.request.user, doc,
            Notification.Type.DOCUMENT_SUBMITTED,
            f"✅ Sizning hujjatingiz muvaffaqiyatli yuborildi: \"{doc.title}\""
        )
        # Notification: Kotib va Manager ga "yangi hujjat"
        notify_staff(
            doc,
            Notification.Type.NEW_DOCUMENT,
            f"📄 Yangi hujjat kelib tushdi: \"{doc.title}\""
        )

    # -------- UPDATE --------
    @extend_schema(
        tags=['Documents: Core'],
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
            "**Ruxsat:** CITIZEN (o'ziniki, faqat NEW), "
            "MANAGER, SECRETARY, SUPERADMIN. (Tahrizchi sifatidagi "
            "faylni tahrirlash huquqi yo'q)"
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
            if document.is_seen or document.status == Document.Status.SEEN:
                return Response(
                    {"error": "Hujjat kotib yoki rais tomonidan ko'rilgan, "
                     "uni endi tahrirlab bo'lmaydi"},
                    status=status.HTTP_400_BAD_REQUEST
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
        tags=['Documents: Core'],
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
        tags=['Documents: Core'],
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
            if document.is_seen or document.status == Document.Status.SEEN:
                return Response(
                    {"error": "Hujjat kotib yoki rais tomonidan ko'rilgan, "
                     "uni endi o'chirib bo'lmaydi"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if document.status != Document.Status.NEW:
                return Response(
                    {"error": "Faqat 'Yangi' holatdagi "
                     "hujjatni o'chirish mumkin"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            # Agar ko'rilmagan bo'lsa - bazadan butunlay o'chirish (hard delete)
            document.hard_delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        elif request.user.role not in ['MANAGER', 'SECRETARY', 'SUPERADMIN']:
            return Response(
                {"error": "Sizda o'chirish huquqi yo'q"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Soft delete — bazadan o'chirmaydi, faqat belgilaydi (Rais/Kotib/Admin uchun)
        document.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # -------- STATS --------
    @extend_schema(
        tags=['Documents: Core'],
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
            seen=Count('id', filter=Q(status=Document.Status.SEEN)),
            pending=Count('id', filter=Q(status=Document.Status.PENDING)),
            under_review=Count('id', filter=Q(status=Document.Status.UNDER_REVIEW)),
            reviewed=Count('id', filter=Q(status=Document.Status.REVIEWED)),
            approved=Count('id', filter=Q(status=Document.Status.APPROVED)),
            rejected=Count('id', filter=Q(status=Document.Status.REJECTED)),
        )
        return Response(data)

    # -------- MARK AS SEEN --------
    @extend_schema(
        tags=['Documents: Workflow'],
        summary="Hujjatni ko'rildi deb belgilash",
        description=(
            "Kotib (SECRETARY) yoki Rais (MANAGER) yangi kelgan hujjatni "
            "ko'rganligini tasdiqlaydi. Bu orqali hujjat holati SEEN ga o'tadi "
            "va fuqaro uni o'chira olmaydi.\n\n"
            "**Ruxsat:** Faqat MANAGER va SECRETARY"
        ),
        request=None,
        responses={200: OpenApiTypes.OBJECT}
    )
    @decorators.action(
        detail=True,
        methods=['post'],
        permission_classes=[IsManager | IsSecretary],
    )
    @transaction.atomic
    def mark_as_seen(self, request, pk=None):
        document = self.get_object()
        msg = self.service.mark_as_seen(document, request.user)
        return Response({"status": msg})

    # -------- ASSIGN REVIEWERS (bir nechta tahrizchi) --------
    @extend_schema(
        tags=['Documents: Workflow'],
        summary="Tahrizchilarni biriktirish",
        description=(
            "Hujjatga bir yoki bir nechta foydalanuvchini tahrizchi "
            "sifatida biriktiradi. **Har qanday foydalanuvchi** "
            "(roldan qat'i nazar) tahrizchi bo'la oladi.\n\n"
            "**So'rov tanasi:**\n"
            "```json\n"
            "{\"reviewers\": [1, 5, 12]}\n"
            "```\n\n"
            "**Qoidalar:**\n"
            "- Hujjat NEW, SEEN, PENDING yoki UNDER_REVIEW holatida "
            "bo'lishi kerak\n"
            "- **Hujjat egasi o'z hujjatiga tahrizchi sifatida "
            "biriktirilishi mumkin emas** (400 xato)\n"
            "- Allaqachon biriktirilgan tahrizchi o'tkazib yuboriladi\n"
            "- Barcha tanlangan tahrizchilar allaqachon biriktirilgan "
            "bo'lsa, `400` xatosi\n\n"
            "**Status o'zgarishi:**\n"
            "- NEW/SEEN → PENDING (avtomatik)\n"
            "- PENDING/UNDER_REVIEW → o'zgarmaydi\n\n"
            "**Ruxsat:** MANAGER va SECRETARY"
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
    @transaction.atomic
    def assign_reviewer(self, request, pk=None):
        document = self.get_object()

        serializer = DocumentAssignReviewersSerializer(data=request.data, context={'document': document})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        reviewers = serializer.validated_data['reviewers']
        try:
            self.service.assign_reviewers(document, reviewers, request.user)
        except (DRFValidationError, ValueError) as e:
            if isinstance(e, DRFValidationError):
                return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        doc = Document.objects.prefetch_related(
            'assignments__reviewer', 'assignments__assigned_by',
            'reviews__reviewer', 'history__user'
        ).select_related('owner', 'category').get(pk=document.pk)

        return Response(DocumentSerializer(doc, context={'request': request}).data)

    # -------- START REVIEW --------
    @extend_schema(
        tags=['Documents: Reviewers'],
        summary="Tahrizni boshlash",
        description=(
            "Biriktirilgan foydalanuvchi hujjatni ko'rib "
            "chiqishni boshlaganini tizimga bildiradi.\n\n"
            "**So'rov tanasi kerak emas** — bo'sh POST yuborish kifoya.\n\n"
            "**Qoidalar:**\n"
            "- Foydalanuvchi hujjatga biriktirilgan bo'lishi kerak\n"
            "- Assignment holati PENDING bo'lishi kerak\n"
            "- Allaqachon IN_PROGRESS/COMPLETED bo'lsa → `400` xato\n\n"
            "**Status o'zgarishlari:**\n"
            "- Assignment: PENDING → IN_PROGRESS\n"
            "- Hujjat: PENDING → UNDER_REVIEW\n\n"
            "**Ruxsat:** Faqat hujjatga biriktirilgan foydalanuvchi"
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
        permission_classes=[IsAssignedToDocument],
    )
    @transaction.atomic
    def start_review(self, request, pk=None):
        document = self.get_object()
        self.service.start_review(document, request.user)
        
        doc = Document.objects.prefetch_related(
            'assignments__reviewer', 'reviews__reviewer', 'history__user'
        ).select_related('owner', 'category').get(pk=document.pk)
        return Response(DocumentSerializer(doc, context={'request': request}).data)

    # -------- SUBMIT REVIEW --------
    # -------- SUBMIT REVIEW --------
    @extend_schema(
        tags=['Documents: Reviewers'],
        summary="Tahriz xulosasini yuklash",
        description=(
            "Biriktirilgan foydalanuvchi o'z ko'rib chiqish "
            "xulosasini PDF fayl ko'rinishida yuklaydi.\n\n"
            "**So'rov maydonlari (multipart/form-data):**\n"
            "- `review_file` — tahriz xulosasi PDF fayli (majburiy, maks 10 MB)\n"
            "- `score` — ball (ixtiyoriy, 0-100)\n"
            "- `comment` — izoh (ixtiyoriy)\n\n"
            "**Qoidalar:**\n"
            "- Avval `start_review` chaqirilgan bo'lishi kerak\n"
            "- Rais/Kotib ko'rgan tahrizni yangilab bo'lmaydi\n"
            "- Rais rad etgan tahrizni qayta yuklash mumkin\n\n"
            "**Status o'zgarishlari:**\n"
            "- Assignment: IN_PROGRESS → COMPLETED\n"
            "- Hujjat: Barcha tahrizchilar tugatsa → REVIEWED\n\n"
            "**Javob:** Birinchi marta → `201`, yangilash → `200`\n\n"
            "**Ruxsat:** Faqat hujjatga biriktirilgan foydalanuvchi"
        ),
        request={
            'multipart/form-data': ReviewSerializer,
        },
        responses={
            201: ReviewSerializer,
            200: ReviewSerializer,
            400: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
        },
    )
    @decorators.action(
        detail=True,
        methods=['post'],
        permission_classes=[IsAssignedToDocument],
        parser_classes=[MultiPartParser, FormParser],
    )
    @transaction.atomic
    def submit_review(self, request, pk=None):
        document = self.get_object()

        # ReviewSerializer faqat review_file va boshqa maydonlarni validatsiya qiladi
        serializer = ReviewSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        review_file = request.FILES.get('review_file')
        try:
            document, is_update = self.service.submit_review(document, request.user, serializer.validated_data, review_file)
        except DRFValidationError as e:
            # Testlar dict qaytishini kutadi: {"error": "..."} yoki {"score": [...]}
            if isinstance(e.detail, list) and len(e.detail) > 0 and isinstance(e.detail[0], str):
                return Response({"error": e.detail[0]}, status=status.HTTP_400_BAD_REQUEST)
            return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        doc = Document.objects.prefetch_related(
            'assignments__reviewer', 'reviews__reviewer', 'history__user'
        ).select_related('owner', 'category').get(pk=document.pk)

        resp_status = status.HTTP_201_CREATED if not is_update else status.HTTP_200_OK
        return Response(DocumentSerializer(doc, context={'request': request}).data, status=resp_status)

    @extend_schema(
        tags=['Documents: Reviewers'],
        summary="Tahrizni o'chirish",
        description="Biriktirilgan foydalanuvchi o'zi yuborgan tahrizni o'chiradi. Bu faqat tahriz hali ko'rib chiqilmagan bo'lsa mumkin.",
        request=None,
        responses={200: OpenApiTypes.OBJECT, 400: ErrorResponseSerializer}
    )
    @decorators.action(
        detail=True,
        methods=['post'],
        permission_classes=[IsAssignedToDocument],
    )
    @transaction.atomic
    def delete_review(self, request, pk=None):
        """Tahrizchi o'z tahrizini o'chiradi (agar hali ko'rilmagan bo'lsa)"""
        document = self.get_object()
        try:
            self.service.delete_review(document, request.user)
        except DRFValidationError as e:
            if isinstance(e.detail, list) and len(e.detail) > 0 and isinstance(e.detail[0], str):
                return Response({"error": e.detail[0]}, status=status.HTTP_400_BAD_REQUEST)
            return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"status": "Tahriz muvaffaqiyatli o'chirildi"}, status=status.HTTP_200_OK)

    # -------- REVIEW ACTIONS (Rais uchun) --------
    @extend_schema(
        tags=['Documents: Management'],
        summary="Tahrizni qabul qilish",
        description=(
            "Rais yoki Kotib bitta tahrizchining xulosasini qabul qiladi.\n\n"
            "**So'rov tanasi:**\n"
            "```json\n"
            "{\"reviewer_id\": 5, \"comment\": \"Yaxshi ish\"}\n"
            "```\n\n"
            "**Qoidalar:**\n"
            "- Faqat COMPLETED holatdagi tahrizni qabul qilish mumkin\n"
            "- Tahrizchiga bildirishnoma yuboriladi\n\n"
            "**Ruxsat:** MANAGER va SECRETARY"
        ),
        request=ReviewActionSerializer,
        responses={200: DocumentSerializer, 400: ErrorResponseSerializer}
    )
    @decorators.action(detail=True, methods=['post'], permission_classes=[IsManagerOrSecretary])
    @transaction.atomic
    def accept_review(self, request, pk=None):
        document = self.get_object()
        serializer = ReviewActionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        reviewer_id = serializer.validated_data['reviewer_id']
        comment = serializer.validated_data.get('comment', '')

        self.service.accept_review(document, reviewer_id, request.user, comment)
        return Response(DocumentSerializer(document, context={'request': request}).data)

    @extend_schema(
        tags=['Documents: Management'],
        summary="Tahrizni rad etish (qayta ko'rish uchun)",
        description=(
            "Rais yoki Kotib bitta tahrizchining xulosasini rad etadi. "
            "Tahrizchi uni qayta ko'rishi kerak bo'ladi.\n\n"
            "**So'rov tanasi:**\n"
            "```json\n"
            "{\"reviewer_id\": 5, \"comment\": \"Sifatsiz tahriz\"}\n"
            "```\n\n"
            "**Status o'zgarishlari:**\n"
            "- Assignment: COMPLETED → IN_PROGRESS\n"
            "- Hujjat: REVIEWED → UNDER_REVIEW\n"
            "- Tahrizchiga bildirishnoma yuboriladi\n\n"
            "**Ruxsat:** MANAGER va SECRETARY"
        ),
        request=ReviewActionSerializer,
        responses={200: DocumentSerializer, 400: ErrorResponseSerializer}
    )
    @decorators.action(detail=True, methods=['post'], permission_classes=[IsManagerOrSecretary])
    @transaction.atomic
    def reject_review(self, request, pk=None):
        document = self.get_object()
        serializer = ReviewActionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        reviewer_id = serializer.validated_data['reviewer_id']
        comment = serializer.validated_data.get('comment', '')

        self.service.reject_review(document, reviewer_id, request.user, comment)
        return Response(DocumentSerializer(document, context={'request': request}).data)

    @extend_schema(
        tags=['Documents: Management'],
        summary="Barcha tahrizlarni rad etish",
        description=(
            "Rais yoki Kotib barcha biriktirilgan tahrizchilarning "
            "xulosalarini rad etadi. Har biriga bildirishnoma yuboriladi.\n\n"
            "**So'rov tanasi:**\n"
            "```json\n"
            "{\"comment\": \"Barcha tahrizlar sifatsiz\"}\n"
            "```\n\n"
            "**Ruxsat:** MANAGER va SECRETARY"
        ),
        request=ReviewActionSerializer,
        responses={200: DocumentSerializer}
    )
    @decorators.action(detail=True, methods=['post'], permission_classes=[IsManagerOrSecretary])
    @transaction.atomic
    def reject_all_reviews(self, request, pk=None):
        document = self.get_object()
        comment = request.data.get('comment', 'Barcha tahrizlar rad etildi')

        assignments = DocumentAssignment.objects.filter(document=document)
        for assignment in assignments:
            self.service.reject_review(document, assignment.reviewer_id, request.user, comment)

        return Response(DocumentSerializer(document, context={'request': request}).data)

    @extend_schema(
        tags=['Documents: Management'],
        summary="Tahrizni ko'rildi deb belgilash",
        description=(
            "Rais (MANAGER) yoki Kotib (SECRETARY) tahrizchi yuborgan xulosani "
            "ko'rganligini tasdiqlaydi. Bundan so'ng tahrizchi xulosasini "
            "o'zgartira olmaydi.\n\n"
            "**Ruxsat:** Faqat MANAGER va SECRETARY"
        ),
        request=ReviewSeenSerializer,
        responses={200: OpenApiTypes.OBJECT, 400: ErrorResponseSerializer}
    )
    @decorators.action(detail=True, methods=['post'], permission_classes=[IsManagerOrSecretary])
    @transaction.atomic
    def mark_review_as_seen(self, request, pk=None):
        document = self.get_object()
        serializer = ReviewSeenSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        reviewer_id = serializer.validated_data['reviewer_id']
        msg = self.service.mark_review_as_seen(document, reviewer_id, request.user)
        return Response({"status": msg})

    # -------- FINALIZE --------
    @extend_schema(
        tags=['Documents: Management'],
        summary="Yakuniy qaror — tasdiqlash yoki rad etish",
        description=(
            "Rais yoki Kotib hujjat bo'yicha yakuniy qaror "
            "qabul qiladi.\n\n"
            "**So'rov tanasi:**\n"
            "```json\n"
            "{\"decision\": \"APPROVE\", \"comment\": \"\"}\n"
            "```\n\n"
            "**APPROVE (tasdiqlash):**\n"
            "- Hujjat: REVIEWED → WAITING_FOR_DISPATCH\n"
            "- Barcha PENDING tahrizlar avtomatik ACCEPTED bo'ladi\n"
            "- Fuqaro va staff ga bildirishnoma yuboriladi\n\n"
            "**REJECT (rad etish):**\n"
            "- Hujjat: REVIEWED → REJECTED\n"
            "- Fuqaroga bildirishnoma yuboriladi\n\n"
            "**Qoidalar:**\n"
            "- Hujjat REVIEWED holatida bo'lishi kerak\n\n"
            "**Ruxsat:** MANAGER va SECRETARY"
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
        permission_classes=[IsManagerOrSecretary],
    )
    @transaction.atomic
    def finalize(self, request, pk=None):
        document = self.get_object()

        serializer = FinalizeRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        decision = serializer.validated_data['decision']
        comment = serializer.validated_data.get('comment', '')

        try:
            status_msg = self.service.finalize_document(document, request.user, decision, comment)
        except DRFValidationError as e:
            if isinstance(e.detail, list) and len(e.detail) > 0 and isinstance(e.detail[0], str):
                return Response({"error": e.detail[0]}, status=status.HTTP_400_BAD_REQUEST)
            return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)

        return Response({"status": status_msg})

    # -------- SEND TO CITIZEN --------
    @extend_schema(
        tags=['Documents: Dispatch'],
        summary="Hujjatni fuqaroga yuborish",
        description=(
            "Rais yoki Kotib tasdiqlangan hujjatni fuqaroga "
            "rasmiy yuboradi.\n\n"
            "**Status o'zgarishi:**\n"
            "- Hujjat: WAITING_FOR_DISPATCH → APPROVED\n"
            "- Fuqaroga bildirishnoma yuboriladi\n\n"
            "**Qoidalar:**\n"
            "- Hujjat WAITING_FOR_DISPATCH holatida bo'lishi kerak\n\n"
            "**Ruxsat:** MANAGER va SECRETARY"
        ),
        request=None,
        responses={
            200: FinalizeResponseSerializer,
            400: ErrorResponseSerializer,
        },
    )
    @decorators.action(
        detail=True,
        methods=['post'],
        permission_classes=[IsManagerOrSecretary],
    )
    @transaction.atomic
    def send_to_citizen(self, request, pk=None):
        document = self.get_object()
        status_msg = self.service.dispatch_document(document, request.user)
        return Response({"status": status_msg})
