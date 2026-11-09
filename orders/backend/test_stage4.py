"""Сценарии API выполняются исключительно в тестовой базе Django."""
import re
from decimal import Decimal

import yaml
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .models import Category, ConfirmEmailToken, Contact, Order, OrderItem, Product, ProductInfo, Shop, User


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
                   ADMINS=[('Admin', 'admin@example.com')])
class StageFourTests(APITestCase):
    def setUp(self):
        self.buyer = User.objects.create_user('buyer@test.example', 'Strong-Test!123')
        self.other = User.objects.create_user('other@test.example', 'Strong-Test!123')
        self.supplier = User.objects.create_user('supplier@test.example', 'Strong-Test!123', type='shop')
        self.supplier2 = User.objects.create_user('supplier2@test.example', 'Strong-Test!123', type='shop')
        self.shop = Shop.objects.create(user=self.supplier, name='Shop 1')
        self.shop2 = Shop.objects.create(user=self.supplier2, name='Shop 2')
        self.category = Category.objects.create(name='Phones')
        self.product = Product.objects.create(name='Phone', category=self.category)
        self.offer = ProductInfo.objects.create(product=self.product, shop=self.shop, external_id=1,
                                                quantity=10, price='100.00', price_rrc='110.00')
        self.offer2 = ProductInfo.objects.create(product=self.product, shop=self.shop2, external_id=1,
                                                 quantity=10, price='150.00', price_rrc='160.00')
        self.contact = Contact.objects.create(user=self.buyer, city='City', street='Street', house='1', phone='+70000000000')
        self.authenticate(self.buyer)

    def authenticate(self, user):
        token, _ = Token.objects.get_or_create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token.key)

    def add(self, offer=None, quantity=2):
        response = self.client.post('/api/v1/basket', {'product_info': (offer or self.offer).pk, 'quantity': quantity}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def checkout(self, basket):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post('/api/v1/order', {'id': basket['id'], 'contact': self.contact.pk}, format='json')

    def test_register_confirm_login(self):
        self.client.credentials()
        payload = {'email': 'new@test.example', 'password': 'Strong-New!7418', 'first_name': 'New', 'last_name': 'Buyer'}
        self.assertEqual(self.client.post('/api/v1/user/register', payload).status_code, 201)
        user = User.objects.get(email=payload['email'])
        self.assertFalse(user.is_active)
        self.assertEqual(self.client.post('/api/v1/user/login', payload).status_code, 400)
        token = ConfirmEmailToken.objects.get(user=user)
        confirm = {'email': user.email, 'token': token.key}
        self.assertEqual(self.client.post('/api/v1/user/register/confirm', confirm).status_code, 200)
        self.assertEqual(self.client.post('/api/v1/user/register/confirm', confirm).status_code, 400)
        result = self.client.post('/api/v1/user/login/', payload)
        self.assertEqual(result.status_code, 200)
        self.assertIn('token', result.data)
        self.assertEqual(len(mail.outbox), 1)

    def test_profile_and_contact_ownership(self):
        self.assertEqual(self.client.get('/api/v1/user/details').data['id'], self.buyer.pk)
        contact = self.client.post('/api/v1/user/contact', {'city':'City', 'street':'Street', 'house':'2', 'phone':'123', 'user':self.other.pk})
        self.assertEqual(contact.status_code, 201)
        self.assertEqual(Contact.objects.get(pk=contact.data['id']).user_id, self.buyer.pk)
        route = f"/api/v1/user/contact/{contact.data['id']}"
        self.assertEqual(self.client.patch(route, {'apartment':'12'}).status_code, 200)
        self.authenticate(self.other)
        self.assertEqual(self.client.get(route).status_code, 404)
        self.assertEqual(self.client.patch(route, {'house':'9'}).status_code, 404)
        self.assertEqual(self.client.delete(route).status_code, 404)
        self.authenticate(self.buyer)
        self.assertEqual(self.client.delete(route).status_code, 204)

    def test_anonymous_endpoints(self):
        self.client.credentials()
        for route in ('basket', 'order', 'user/details', 'user/contact', 'partner/state', 'partner/orders'):
            self.assertEqual(self.client.get('/api/v1/' + route).status_code, 401)
        self.assertEqual(self.client.get('/api/v1/products').status_code, 200)

    def test_basket_updates_delete_and_owner(self):
        self.assertIsNone(self.client.get('/api/v1/basket').data['id'])
        basket = self.add()
        item = basket['ordered_items'][0]['id']
        self.assertEqual(self.add(quantity=1)['ordered_items'][0]['quantity'], 3)
        route = f'/api/v1/basket/{item}'
        self.assertEqual(self.client.patch(route, {'quantity':4}).status_code, 200)
        self.assertEqual(self.client.patch(route, {'quantity':0}).status_code, 400)
        self.authenticate(self.other)
        self.assertEqual(self.client.delete(route).status_code, 404)
        self.authenticate(self.buyer)
        self.assertEqual(self.client.delete(route).status_code, 204)

    def test_invalid_basket_and_disabled_shop(self):
        for qty in (-1, 0, 11, 'bad'):
            self.assertEqual(self.client.post('/api/v1/basket', {'product_info':self.offer.pk, 'quantity':qty}).status_code, 400)
        self.shop.state = False
        self.shop.save()
        self.assertEqual(self.client.post('/api/v1/basket', {'product_info':self.offer.pk, 'quantity':1}).status_code, 400)
        self.assertEqual(self.client.get(f'/api/v1/products/{self.offer.pk}').status_code, 404)

    def test_checkout_multiple_suppliers_and_notifications(self):
        basket = self.add()
        basket = self.add(self.offer2, 1)
        response = self.checkout(basket)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Decimal(response.data['total']), Decimal('350.00'))
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.quantity, 8)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[0].to, [self.buyer.email])
        self.assertEqual(mail.outbox[1].to, ['admin@example.com'])
        self.assertIn('350.00', mail.outbox[1].body)
        self.assertEqual(self.checkout(basket).status_code, 404)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(self.client.get('/api/v1/order').data[0]['id'], basket['id'])
        self.offer.price = 999
        self.offer.save()
        self.assertEqual(Decimal(self.client.get(f"/api/v1/order/{basket['id']}").data['total']), Decimal('350.00'))
        self.authenticate(self.other)
        self.assertEqual(self.client.get(f"/api/v1/order/{basket['id']}").status_code, 404)
        self.assertEqual(self.client.get('/api/v1/order').data, [])

    def test_checkout_rejects_foreign_contact_empty_and_stock_changes(self):
        basket = self.add()
        foreign = Contact.objects.create(user=self.other, city='X', street='Y', house='1', phone='123')
        self.assertEqual(self.client.post('/api/v1/order', {'id':basket['id'], 'contact':foreign.pk}).status_code, 404)
        self.offer.quantity = 1
        self.offer.save()
        self.assertEqual(self.checkout(basket).status_code, 400)
        self.assertEqual(Order.objects.get(pk=basket['id']).state, 'basket')
        OrderItem.objects.filter(order_id=basket['id']).delete()
        self.assertEqual(self.checkout(basket).status_code, 400)

    def test_checkout_atomic_when_one_offer_unavailable(self):
        self.add()
        basket = self.add(self.offer2)
        self.offer2.quantity = 0
        self.offer2.save()
        self.assertEqual(self.checkout(basket).status_code, 400)
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.quantity, 10)

    def test_supplier_only_sees_own_items(self):
        self.add()
        basket = self.add(self.offer2, 1)
        self.assertEqual(self.checkout(basket).status_code, 201)
        self.assertEqual(self.client.get('/api/v1/partner/orders').status_code, 403)
        self.authenticate(self.supplier)
        result = self.client.get('/api/v1/partner/orders')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.data[0]['ordered_items']), 1)
        self.assertEqual(Decimal(result.data[0]['total']), Decimal('200.00'))
        self.assertEqual(self.client.post('/api/v1/basket', {'product_info':self.offer.pk, 'quantity':1}).status_code, 403)
        self.assertEqual(self.client.post('/api/v1/partner/state', {'state':False}, format='json').status_code, 200)
        self.shop.refresh_from_db()
        self.assertFalse(self.shop.state)

    def upload(self, data):
        file = SimpleUploadedFile('catalog.yaml', yaml.safe_dump(data).encode(), content_type='application/yaml')
        return self.client.post('/api/v1/partner/update', {'file':file}, format='multipart')

    def catalog(self):
        return {'shop':'Updated shop', 'categories':[{'id':self.category.pk, 'name':'Phones'}], 'goods':[
            {'id':1, 'category':self.category.pk, 'name':'Phone', 'model':'Model', 'quantity':9,
             'price':200, 'price_rrc':210, 'parameters':{'Color':'black', 'Smart':True, 'Size':6.5}}]}

    def test_supplier_import_validated_idempotent_and_preserves_orders(self):
        basket = self.add()
        self.assertEqual(self.checkout(basket).status_code, 201)
        self.authenticate(self.supplier)
        for _ in range(2):
            response = self.upload(self.catalog())
            self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.shop.product_infos.count(), 1)
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.price, Decimal('200'))
        self.assertEqual(self.offer.product_parameters.count(), 3)
        self.assertEqual(OrderItem.objects.get(order_id=basket['id']).price, Decimal('100'))
        invalid = self.catalog()
        invalid['goods'][0]['price'] = -1
        self.assertEqual(self.upload(invalid).status_code, 400)
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.price, Decimal('200'))
        empty = self.catalog()
        empty['goods'] = []
        self.assertEqual(self.upload(empty).status_code, 200)
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.quantity, 0)
        self.assertTrue(OrderItem.objects.filter(order_id=basket['id']).exists())

    def test_malformed_catalog_and_buyer_denied(self):
        self.assertEqual(self.upload(self.catalog()).status_code, 403)
        self.authenticate(self.supplier)
        self.assertEqual(self.upload({'shop':'Broken'}).status_code, 400)
        bad = self.catalog()
        bad['goods'][0]['category'] = 999
        self.assertEqual(self.upload(bad).status_code, 400)

    def test_status_changes_restore_stock_and_notify(self):
        basket = self.add()
        self.assertEqual(self.checkout(basket).status_code, 201)
        route = f"/api/v1/order/{basket['id']}/status"
        self.assertEqual(self.client.patch(route, {'state':'canceled'}).status_code, 403)
        self.buyer.is_staff = True
        self.buyer.save()
        self.assertEqual(self.client.patch(route, {'state':'delivered'}).status_code, 400)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.client.patch(route, {'state':'canceled'}).status_code, 200)
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.quantity, 10)
        self.assertEqual(self.client.patch(route, {'state':'canceled'}).status_code, 400)
        self.assertEqual(self.client.patch(route, {}).status_code, 400)
        self.assertEqual(len(mail.outbox), 4)

    def test_used_contact_cannot_be_deleted(self):
        self.assertEqual(self.checkout(self.add()).status_code, 201)
        self.assertEqual(self.client.delete(f'/api/v1/user/contact/{self.contact.pk}').status_code, 400)

    def test_password_reset_reusable_token_rejected_and_login_token_revoked(self):
        self.client.credentials()
        self.assertEqual(self.client.post('/api/v1/user/password_reset', {'email':self.buyer.email}).status_code, 200)
        body = mail.outbox[-1].body
        uid = re.search(r'uid: (\S+)', body).group(1)
        token = re.search(r'token: (\S+)', body).group(1)
        data = {'uid':uid, 'token':token, 'password':'New-Strong!86421'}
        self.assertEqual(self.client.post('/api/v1/user/password_reset/confirm', data).status_code, 200)
        self.assertFalse(Token.objects.filter(user=self.buyer).exists())
        self.assertEqual(self.client.post('/api/v1/user/password_reset/confirm', data).status_code, 400)
        self.assertEqual(self.client.post('/api/v1/user/login', {'email':self.buyer.email,'password':data['password']}).status_code, 200)

    def test_unknown_reset_and_invalid_filter(self):
        self.client.credentials()
        self.assertEqual(self.client.post('/api/v1/user/password_reset', {'email':'missing@test.example'}).status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(self.client.get('/api/v1/products?shop_id=invalid').status_code, 400)
        self.assertEqual(self.client.get('/api/v1/products?category_id=-1').status_code, 400)
        self.assertEqual(self.client.get('/api/v1/products?search=missing').data, [])
