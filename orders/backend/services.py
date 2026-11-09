from pathlib import Path

import yaml
from django.db import transaction
from rest_framework import serializers

from .models import (
    Category,
    Parameter,
    Product,
    ProductInfo,
    ProductParameter,
    Shop,
    User,
)


def read_catalog(file_path):
    """Прочитать каталог из YAML-файла."""
    with Path(file_path).open(encoding="utf-8") as file:
        return yaml.safe_load(file)


def import_catalog(file_path, user):
    """Создать или обновить каталог поставщика."""
    return import_catalog_data(read_catalog(file_path), user)


class CategoryInput(serializers.Serializer):
    id = serializers.IntegerField(min_value=1)
    name = serializers.CharField(max_length=100)


class GoodsInput(serializers.Serializer):
    id = serializers.IntegerField(min_value=1)
    category = serializers.IntegerField(min_value=1)
    name = serializers.CharField(max_length=200)
    model = serializers.CharField(max_length=100, allow_blank=True, default='')
    quantity = serializers.IntegerField(min_value=0)
    price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    price_rrc = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    parameters = serializers.DictField(default=dict)

    def validate_parameters(self, value):
        for key, item in value.items():
            if not isinstance(item, (str, int, float, bool)) or len(str(item)) > 100:
                raise serializers.ValidationError('Значение характеристики должно быть строкой или числом длиной до 100 символов.')
        return {key: str(item) for key, item in value.items()}


class CatalogInput(serializers.Serializer):
    shop = serializers.CharField(max_length=100)
    categories = CategoryInput(many=True)
    goods = GoodsInput(many=True)

    def validate(self, attrs):
        category_ids = [c['id'] for c in attrs['categories']]
        goods_ids = [g['id'] for g in attrs['goods']]
        if len(set(category_ids)) != len(category_ids) or len(set(goods_ids)) != len(goods_ids):
            raise serializers.ValidationError('Повторяющиеся коды категорий или товаров.')
        for item in attrs['goods']:
            if item['category'] not in category_ids:
                raise serializers.ValidationError('Категория товара отсутствует в файле.')
            if any(not name.strip() or len(name) > 100 for name in item['parameters']):
                raise serializers.ValidationError('Некорректное название характеристики.')
        return attrs


@transaction.atomic
def import_catalog_data(data, user):
    """Проверить и атомарно обновить каталог без удаления позиций заказов."""
    if user.type != User.UserType.SHOP:
        raise ValueError("Импорт доступен только поставщикам")
    serializer = CatalogInput(data=data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    User.objects.select_for_update().get(pk=user.pk)

    # Создаём или обновляем магазин поставщика.
    shop, _ = Shop.objects.update_or_create(
        user=user,
        defaults={"name": data["shop"]},
    )
    Shop.objects.select_for_update().get(pk=shop.pk)

    # Загружаем категории и связываем их с магазином.
    for category_data in data["categories"]:
        category, _ = Category.objects.update_or_create(
            id=category_data["id"],
            defaults={"name": category_data["name"]},
        )
        category.shops.add(shop)

    # Загружаем товары и предложения магазина.
    for item in data["goods"]:
        product, _ = Product.objects.get_or_create(
            name=item["name"],
            category_id=item["category"],
        )

        product_info, _ = ProductInfo.objects.update_or_create(
            shop=shop,
            external_id=item["id"],
            defaults={
                "product": product,
                "model": item["model"],
                "quantity": item["quantity"],
                "price": item["price"],
                "price_rrc": item["price_rrc"],
            },
        )

        # Загружаем характеристики предложения.
        for name, value in item["parameters"].items():
            parameter, _ = Parameter.objects.get_or_create(
                name=name,
            )

            ProductParameter.objects.update_or_create(
                product_info=product_info,
                parameter=parameter,
                defaults={"value": str(value)},
            )

        product_info.product_parameters.exclude(parameter__name__in=item['parameters']).delete()

    # Missing offers remain available to historical orders but cannot be purchased.
    shop.product_infos.exclude(external_id__in=[item['id'] for item in data['goods']]).update(quantity=0)
    shop.categories.set([category['id'] for category in data['categories']])

    return shop
