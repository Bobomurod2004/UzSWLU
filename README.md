# E-ijro Document Management Backend

Ushbu loyiha professional hujjatlar aylanishi tizimi uchun backend qismi hisoblanadi.

## Xususiyatlari
- **Rollar**: Fuqaro, Kotib, Rais, Tahrizchi.
- **Workflow**: Hujjat yuborish, yo'naltirish, tahriz yozish va tasdiqlash.
- **Soft Delete**: Bazadan ma'lumotlar o'chib ketmaydi.
- **Swagger Documentation**: `/api/docs/` manzilida.

## Ishga tushirish

1. Virtual muhitni faollashtiring:
   ```bash
   source .venv/bin/activate
   ```
2. Migratsiyalarni bajaring (agar bajarilmagan bo'lsa):
   ```bash
   python manage.py migrate
   ```
3. Serverni ishga tushiring:
   ```bash
   python manage.py runserver
   ```

## Test Foydalanuvchilari (Credentials)

Dastlabki testlar uchun quyidagi foydalanuvchilar yaratilgan:

| Email | Parol | Rol |
| :--- | :--- | :--- |
| `admin@example.com` | `adminpassword` | Superadmin (Rais) |
| `kotib@example.com` | `kotib123` | Kotib |
| `rais@example.com` | `rais123` | Rais/Manager |
| `tahrizchi@example.com` | `tahriz123` | Tahrizchi |
| `user1@example.com` | `user123` | Fuqaro |

## API Dokumentatsiya
Loyiha ishga tushgach, brauzerda quyidagi manzillarga kirish mumkin:
- **Swagger**: `http://127.0.0.1:8000/api/docs/`
- **Admin Panel**: `http://127.0.0.1:8000/admin/`
