"""Приёмка: полный путь покупателя через API с реальными commit в тестовой БД."""
from decimal import Decimal
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient, APITransactionTestCase

from .models import Contact, Order, ProductInfo, ProductParameter, User


TEST_SETTINGS = {
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
    'ADMINS': [('Acceptance admin', 'admin@acceptance.example')],
    # Only test credentials use this hasher; production settings are unchanged.
    'PASSWORD_HASHERS': ['django.contrib.auth.hashers.MD5PasswordHasher'],
}


@override_settings(**TEST_SETTINGS)
class PurchaseAcceptanceTests(APITransactionTestCase):
    def login(self, email, password):
        client = APIClient()
        result = client.post('/api/v1/user/login', {'email': email, 'password': password}, format='json')
        self.assertEqual(result.status_code, 200)
        client.credentials(HTTP_AUTHORIZATION='Token ' + result.data['token'])
        return client

    def supplier(self, index, price):
        email = f'supplier{index}@acceptance.example'
        password = 'Supplier-Acceptance!4819'
        User.objects.create_user(email, password, type='shop')
        client = self.login(email, password)
        catalog = {
            'shop': f'Shop {index}',
            'categories': [{'id': 224, 'name': 'Смартфоны'}],
            'goods': [{'id': 100, 'category': 224, 'name': 'Тестовый телефон',
                       'model': 'phone', 'quantity': 10, 'price': price,
                       'price_rrc': price + 10, 'parameters': {'Цвет': 'Чёрный'}}],
        }
        upload = SimpleUploadedFile('catalog.yaml', yaml.safe_dump(catalog, allow_unicode=True).encode('utf-8'))
        self.assertEqual(client.post('/api/v1/partner/update', {'file': upload}, format='multipart').status_code, 200)
        return client

    def test_registration_to_delivered_order(self):
        supplier1 = self.supplier(1, 100)
        supplier2 = self.supplier(2, 150)
        client = APIClient()
        registration = {'email': 'buyer@acceptance.example', 'password': 'Buyer-Acceptance!4928',
                        'first_name': 'Иван', 'last_name': 'Иванов'}
        self.assertEqual(client.post('/api/v1/user/register', registration, format='json').status_code, 201)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [registration['email']])
        # Obtain the confirmation token from the actual generated message, not the DB.
        confirmation_token = mail.outbox[0].body.rsplit(':', 1)[1].strip()
        self.assertEqual(client.post('/api/v1/user/login', registration, format='json').status_code, 400)
        self.assertEqual(client.post('/api/v1/user/register/confirm', {
            'email': registration['email'], 'token': confirmation_token}, format='json').status_code, 200)
        client = self.login(registration['email'], registration['password'])
        self.assertEqual(client.get('/api/v1/user/details').data['first_name'], 'Иван')
        self.assertEqual(len(client.get('/api/v1/categories').data), 1)
        shops = client.get('/api/v1/shops').data
        self.assertEqual(len(shops), 2)
        offers = client.get('/api/v1/products?category_id=224').data
        self.assertEqual(len(offers), 2)
        for offer in offers:
            detail = client.get(f"/api/v1/products/{offer['id']}")
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.data['product_parameters'][0]['value'], 'Чёрный')
            added = client.post('/api/v1/basket', {'product_info': offer['id'], 'quantity': 2}, format='json')
            self.assertEqual(added.status_code, 201)
        basket = client.get('/api/v1/basket').data
        self.assertEqual(len(basket['ordered_items']), 2)
        self.assertEqual(Decimal(basket['total']), Decimal('500.00'))
        contact = client.post('/api/v1/user/contact', {
            'city': 'Москва', 'street': 'Ленина', 'house': '10', 'phone': '+79990000000'}, format='json')
        self.assertEqual(contact.status_code, 201)
        saved = Contact.objects.get(pk=contact.data['id'])
        self.assertEqual((saved.city, saved.street), ('Москва', 'Ленина'))
        # TransactionTestCase allows on_commit callbacks to run naturally here.
        placed = client.post('/api/v1/order', {'id': basket['id'], 'contact': saved.pk}, format='json')
        self.assertEqual(placed.status_code, 201)
        self.assertEqual(placed.data['state'], 'new')
        self.assertEqual(len(mail.outbox), 3)
        self.assertEqual(mail.outbox[1].to, [registration['email']])
        self.assertEqual(mail.outbox[2].to, ['admin@acceptance.example'])
        for message in mail.outbox[1:]:
            for text in ('Москва', 'Ленина', '500.00', 'Shop 1', 'Shop 2'):
                self.assertIn(text, message.body)
        self.assertEqual(list(ProductInfo.objects.values_list('quantity', flat=True)), [8, 8])
        order_id = placed.data['id']
        self.assertEqual(client.get('/api/v1/order').data[0]['id'], order_id)
        self.assertEqual(client.get(f'/api/v1/order/{order_id}').data['total'], '500.00')
        self.assertIsNone(client.get('/api/v1/basket').data['id'])
        for supplier in (supplier1, supplier2):
            own_order = supplier.get('/api/v1/partner/orders').data[0]
            self.assertEqual(len(own_order['ordered_items']), 1)
            self.assertEqual(own_order['id'], order_id)
        self.assertEqual(supplier1.post('/api/v1/partner/state', {'state': False}, format='json').status_code, 200)
        self.assertEqual(len(client.get('/api/v1/shops').data), 1)
        self.assertEqual(len(client.get('/api/v1/products').data), 1)
        User.objects.create_superuser('admin@acceptance.example', 'Administrator!46815')
        admin = self.login('admin@acceptance.example', 'Administrator!46815')
        for state in ('confirmed', 'assembled', 'sent', 'delivered'):
            result = admin.patch(f'/api/v1/order/{order_id}/status', {'state': state}, format='json')
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.data['state'], state)
        self.assertEqual(len(mail.outbox), 11)
        self.assertEqual(Order.objects.get(pk=order_id).state, 'delivered')


@override_settings(**TEST_SETTINGS)
class ImportCommandAcceptanceTests(TestCase):
    def test_import_command_on_empty_database_and_repeat(self):
        supplier = User.objects.create_user('supplier@cli.example', 'Supplier!8146', type='shop')
        fixture = Path(__file__).resolve().parents[2] / 'data' / 'shop1.yaml'
        catalog = yaml.safe_load(fixture.read_text(encoding='utf-8'))
        for _ in range(2):
            call_command('import_catalog', str(fixture), email=supplier.email, stdout=StringIO())
        self.assertEqual(ProductInfo.objects.filter(shop__user=supplier).count(), len(catalog['goods']))
        expected_parameters = sum(len(item['parameters']) for item in catalog['goods'])
        self.assertEqual(ProductParameter.objects.filter(product_info__shop__user=supplier).count(), expected_parameters)
        with TemporaryDirectory() as directory:
            bad_file = Path(directory) / 'bad.yaml'
            bad_file.write_text('shop: Broken', encoding='utf-8')
            with self.assertRaises(CommandError):
                call_command('import_catalog', str(bad_file), email=supplier.email, stdout=StringIO())
        self.assertEqual(ProductInfo.objects.count(), len(catalog['goods']))
