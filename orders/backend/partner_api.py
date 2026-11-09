"""API поставщика: загрузка YAML-файла, состояние магазина и заказы."""
import yaml
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Shop, User
from .order_api import OrderSerializer, orders_queryset
from .serializers import ShopSerializer
from .services import import_catalog_data


class SupplierPermission(IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.type == User.UserType.SHOP


class PartnerState(APIView):
    permission_classes = (SupplierPermission,)

    def get(self, request):
        return Response(ShopSerializer(get_object_or_404(Shop, user=request.user)).data)

    @transaction.atomic
    def post(self, request):
        class StateInput(serializers.Serializer):
            state = serializers.BooleanField()
        data = StateInput(data=request.data)
        data.is_valid(raise_exception=True)
        shop = get_object_or_404(Shop.objects.select_for_update(), user=request.user)
        shop.state = data.validated_data['state']
        shop.save(update_fields=['state'])
        return Response(ShopSerializer(shop).data)

    patch = post


class PartnerOrders(APIView):
    permission_classes = (SupplierPermission,)

    def get(self, request):
        shop = get_object_or_404(Shop, user=request.user)
        orders = orders_queryset().filter(ordered_items__product_info__shop=shop).exclude(state='basket').distinct()
        return Response(OrderSerializer(orders, many=True, context={'shop': shop}).data)


class PartnerUpdate(APIView):
    permission_classes = (SupplierPermission,)
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request):
        upload = request.FILES.get('file')
        if upload is None:
            raise serializers.ValidationError({'file': 'Прикрепите YAML-файл прайс-листа.'})
        if upload.size > 2 * 1024 * 1024:
            raise serializers.ValidationError({'file': 'Максимальный размер файла — 2 МБ.'})
        try:
            data = yaml.safe_load(upload.read().decode('utf-8-sig'))
        except (UnicodeError, yaml.YAMLError, RecursionError) as error:
            raise serializers.ValidationError({'file': 'Некорректный YAML-файл.'}) from error
        shop = import_catalog_data(data, request.user)
        return Response(ShopSerializer(shop).data)
