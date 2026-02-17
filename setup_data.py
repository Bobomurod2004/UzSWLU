import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'setting.settings')
django.setup()

from apps.accounts.models import User
from apps.documents.models import Category

def setup_initial_data():
    # 1. Create Superuser (Manager)
    if not User.objects.filter(email='admin@example.com').exists():
        User.objects.create_superuser(
            email='admin@example.com',
            password='adminpassword',
            role=User.Role.MANAGER
        )
        print("Superuser 'admin@example.com' yaratildi (parol: adminpassword).")

    # 2. Create sample Roles for testing
    roles = [
        ('kotib@example.com', 'kotib123', User.Role.SECRETARY),
        ('rais@example.com', 'rais123', User.Role.MANAGER),
        ('tahrizchi@example.com', 'tahriz123', User.Role.REVIEWER),
        ('user1@example.com', 'user123', User.Role.CITIZEN),
    ]
    for email, password, role in roles:
        if not User.objects.filter(email=email).exists():
            User.objects.create_user(
                email=email,
                password=password,
                role=role
            )
            print(f"User '{email}' yaratildi (rol: {role}).")

    # 3. Create Categories
    categories = [
        "IT va Texnologiyalar",
        "Iqtisodiyot",
        "Tibbiyot",
        "Huquqshunoslik",
    ]
    for cat_name in categories:
        if not Category.objects.filter(name=cat_name).exists():
            Category.objects.create(name=cat_name)
            print(f"Kategoriya '{cat_name}' yaratildi.")

if __name__ == '__main__':
    setup_initial_data()
