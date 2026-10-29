import yaml
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from backend.models import User
from backend.services import import_catalog


class Command(BaseCommand):
    help = "Загрузить каталог поставщика из YAML-файла"

    def add_arguments(self, parser):
        parser.add_argument("file_path", help="Путь к YAML-файлу")
        parser.add_argument(
            "--email",
            required=True,
            help="Email поставщика",
        )

    def handle(self, *args, **options):
        try:
            supplier = User.objects.get(email=options["email"])
        except User.DoesNotExist:
            raise CommandError("Пользователь с таким email не найден")

        try:
            shop = import_catalog(options["file_path"], supplier)
        except (
            OSError,
            yaml.YAMLError,
            ValueError,
            KeyError,
            TypeError,
            ValidationError,
            IntegrityError,
        ) as error:
            raise CommandError(f"Не удалось загрузить каталог: {error}") from error

        self.stdout.write(
            self.style.SUCCESS(
                f"Каталог загружен. Магазин: {shop.name}. "
                f"Всего предложений: {shop.product_infos.count()}."
            )
        )