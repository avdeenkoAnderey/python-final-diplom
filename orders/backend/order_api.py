"""Корзина, оформление и история заказов."""
from decimal import Decimal

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Contact, Order, OrderItem, ProductInfo, Shop, User
from .serializers import ContactSerializer, ProductInfoSerializer


class BuyerPermission(IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.type == User.UserType.BUYER


class ItemSerializer(serializers.ModelSerializer):
    product_info = ProductInfoSerializer(read_only=True)
    total = serializers.DecimalField(max_digits=24, decimal_places=2, read_only=True)

    class Meta:
        model = OrderItem
        fields = ('id', 'product_info', 'quantity', 'price', 'total')


class OrderSerializer(serializers.ModelSerializer):
    ordered_items = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    contact = ContactSerializer(read_only=True)

    def visible_items(self, obj):
        items = obj.ordered_items.all()
        shop = self.context.get('shop')
        return [item for item in items if shop is None or item.product_info.shop_id == shop.pk]

    def get_ordered_items(self, obj):
        return ItemSerializer(self.visible_items(obj), many=True).data

    def get_total(self, obj):
        return str(sum((item.total for item in self.visible_items(obj)), Decimal('0.00')))

    class Meta:
        model = Order
        fields = ('id', 'state', 'dt', 'contact', 'ordered_items', 'total')


def orders_queryset():
    return Order.objects.select_related('contact').prefetch_related(
        'ordered_items__product_info__shop',
        'ordered_items__product_info__product__category',
        'ordered_items__product_info__product_parameters__parameter',
    )


class BasketInput(serializers.Serializer):
    product_info = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1)


class QuantityInput(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1)


class CheckoutInput(serializers.Serializer):
    id = serializers.IntegerField(min_value=1)
    contact = serializers.IntegerField(min_value=1)


def check_offer(offer, quantity):
    if not offer.shop.state:
        raise ValidationError('Магазин не принимает заказы.')
    if quantity > offer.quantity:
        raise ValidationError({'quantity': 'Недостаточно товара на складе.'})
    if offer.price < 0:
        raise ValidationError('Цена товара некорректна.')


class BasketView(APIView):
    permission_classes = (BuyerPermission,)

    def get(self, request):
        basket = orders_queryset().filter(user=request.user, state=Order.State.BASKET).first()
        return Response(OrderSerializer(basket).data if basket else {
            'id': None, 'state': 'basket', 'ordered_items': [], 'total': '0.00', 'contact': None,
        })

    @transaction.atomic
    def post(self, request):
        data = BasketInput(data=request.data)
        data.is_valid(raise_exception=True)
        # Serialize basket creation and modifications for a given customer.
        User.objects.select_for_update().get(pk=request.user.pk)
        basket, _ = Order.objects.get_or_create(user=request.user, state=Order.State.BASKET)
        offer = get_object_or_404(ProductInfo.objects.select_related('shop'), pk=data.validated_data['product_info'])
        item = basket.ordered_items.filter(product_info=offer).first()
        quantity = data.validated_data['quantity'] + (item.quantity if item else 0)
        check_offer(offer, quantity)
        OrderItem.objects.update_or_create(order=basket, product_info=offer,
                                          defaults={'quantity': quantity, 'price': offer.price})
        return Response(OrderSerializer(orders_queryset().get(pk=basket.pk)).data, status=status.HTTP_201_CREATED)


class BasketItemView(APIView):
    permission_classes = (BuyerPermission,)

    @transaction.atomic
    def patch(self, request, pk):
        data = QuantityInput(data=request.data)
        data.is_valid(raise_exception=True)
        User.objects.select_for_update().get(pk=request.user.pk)
        item = get_object_or_404(OrderItem.objects.select_related('product_info__shop'),
                                pk=pk, order__user=request.user, order__state=Order.State.BASKET)
        check_offer(item.product_info, data.validated_data['quantity'])
        item.quantity = data.validated_data['quantity']
        item.price = item.product_info.price
        item.save(update_fields=['quantity', 'price'])
        return Response(ItemSerializer(item).data)

    @transaction.atomic
    def delete(self, request, pk):
        User.objects.select_for_update().get(pk=request.user.pk)
        item = get_object_or_404(OrderItem, pk=pk, order__user=request.user, order__state=Order.State.BASKET)
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


def notify_order(order_id):
    order = orders_queryset().select_related('user').get(pk=order_id)
    lines = [f'Заказ №{order.pk}. Статус: {order.get_state_display()}.',
             f'Адрес: {order.contact}. Телефон: {order.contact.phone}.']
    lines += [f'{item.product_info}: {item.quantity} × {item.price} = {item.total}'
              for item in order.ordered_items.all()]
    lines.append(f'Итого: {order.total}')
    message = '\n'.join(lines)
    send_mail(f'Заказ №{order.pk}', message, settings.DEFAULT_FROM_EMAIL, [order.user.email])
    recipients = [email for _, email in settings.ADMINS]
    if recipients:
        send_mail(f'Накладная: заказ №{order.pk}', message, settings.DEFAULT_FROM_EMAIL, recipients)


class OrderView(APIView):
    permission_classes = (BuyerPermission,)

    def get(self, request):
        orders = orders_queryset().filter(user=request.user).exclude(state=Order.State.BASKET)
        return Response(OrderSerializer(orders, many=True).data)

    @transaction.atomic
    def post(self, request):
        data = CheckoutInput(data=request.data)
        data.is_valid(raise_exception=True)
        User.objects.select_for_update().get(pk=request.user.pk)
        basket = get_object_or_404(Order.objects.select_for_update(), pk=data.validated_data['id'],
                                  user=request.user, state=Order.State.BASKET)
        contact = get_object_or_404(Contact, pk=data.validated_data['contact'], user=request.user)
        items = list(basket.ordered_items.order_by('product_info_id'))
        if not items:
            raise ValidationError('Корзина пуста.')
        offers = {o.pk: o for o in ProductInfo.objects.select_for_update().select_related('shop')
                  .filter(pk__in=[i.product_info_id for i in items]).order_by('pk')}
        # Lock shops as well so a concurrent supplier operation cannot disable acceptance.
        shops = {s.pk: s for s in Shop.objects.select_for_update().filter(
            pk__in={offer.shop_id for offer in offers.values()}).order_by('pk')}
        for item in items:
            offer = offers[item.product_info_id]
            offer.shop = shops[offer.shop_id]
            check_offer(offer, item.quantity)
        for item in items:
            offer = offers[item.product_info_id]
            updated = ProductInfo.objects.filter(pk=offer.pk, quantity__gte=item.quantity).update(
                quantity=F('quantity') - item.quantity)
            if not updated:
                raise ValidationError('Остаток изменился. Повторите оформление.')
            item.price = offer.price
            item.save(update_fields=['price'])
        basket.contact = contact
        basket.state = Order.State.NEW
        basket.save(update_fields=['contact', 'state'])
        transaction.on_commit(lambda: notify_order(basket.pk), robust=True)
        return Response(OrderSerializer(orders_queryset().get(pk=basket.pk)).data, status=201)


class OrderDetailView(APIView):
    permission_classes = (BuyerPermission,)

    def get(self, request, pk):
        order = get_object_or_404(orders_queryset().exclude(state=Order.State.BASKET), pk=pk, user=request.user)
        return Response(OrderSerializer(order).data)


class OrderStatusView(APIView):
    permission_classes = (IsAuthenticated,)

    @transaction.atomic
    def patch(self, request, pk):
        if not request.user.is_staff:
            raise PermissionDenied('Изменять статус может только администратор.')
        order = get_object_or_404(Order.objects.select_for_update().exclude(state=Order.State.BASKET), pk=pk)
        transitions = {'new': 'confirmed', 'confirmed': 'assembled', 'assembled': 'sent', 'sent': 'delivered'}
        target = request.data.get('state')
        if target != transitions.get(order.state) and not (
            target == 'canceled' and order.state in ('new', 'confirmed', 'assembled')
        ):
            raise ValidationError({'state': 'Недопустимый переход статуса.'})
        if target is None:
            raise ValidationError({'state': 'Укажите статус.'})
        if target == 'canceled':
            for item in order.ordered_items.order_by('product_info_id'):
                ProductInfo.objects.filter(pk=item.product_info_id).update(quantity=F('quantity') + item.quantity)
        order.state = target
        order.save(update_fields=['state'])
        transaction.on_commit(lambda: notify_order(order.pk), robust=True)
        return Response(OrderSerializer(orders_queryset().get(pk=pk)).data)
