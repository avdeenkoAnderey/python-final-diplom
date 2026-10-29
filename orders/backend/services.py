from pathlib import Path

import yaml
from django.db import transaction

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


@transaction.atomic
def import_catalog(file_path, user):
    """Создать или обновить каталог поставщика."""
    if user.type != User.UserType.SHOP:
        raise ValueError("Импорт доступен только поставщикам")

    data = read_catalog(file_path)

    # Создаём или обновляем магазин поставщика.
    shop, _ = Shop.objects.update_or_create(
        user=user,
        defaults={"name": data["shop"]},
    )

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

    return shop