from django.contrib.auth.models import AbstractUser
from django.db import models
from django.contrib.auth.base_user import BaseUserManager
from decimal import Decimal
from django_rest_passwordreset.tokens import get_token_generator


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Укажите email")

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Суперпользователь должен иметь is_staff=True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Суперпользователь должен иметь is_superuser=True")

        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    username = None

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()
    class UserType(models.TextChoices):
        SHOP = "shop", "Поставщик"
        BUYER = "buyer", "Покупатель"

    email = models.EmailField("Email", unique=True)
    company = models.CharField("Компания", max_length=100, blank=True)
    position = models.CharField("Должность", max_length=100, blank=True)
    type = models.CharField(
        "Тип пользователя",
        max_length=5,
        choices=UserType.choices,
        default=UserType.BUYER,
    )

    def __str__(self):
        return self.email

    class Meta:
        verbose_name = 'Пользователь'
        verbose_name_plural = 'Список пользователей'

class Shop(models.Model):
    name = models.CharField("Название", max_length=100)
    url = models.URLField("Сайт", blank=True)
    user = models.OneToOneField(
        "backend.User",
        on_delete=models.PROTECT,
        related_name="shop",
        verbose_name="Поставщик",
    )
    state = models.BooleanField("Принимает заказы", default=True)

    class Meta:
        verbose_name = "Магазин"
        verbose_name_plural = "Список магазинов"
        ordering = ("name",)

    def __str__(self):
        return self.name

class Category(models.Model):
    name = models.CharField("Название", max_length=100)
    shops = models.ManyToManyField(
        Shop,
        related_name="categories",
        verbose_name="Магазины",
        blank=True,
    )

    class Meta:
        verbose_name = "Категория"
        verbose_name_plural = "Список категорий"
        ordering = ("name",)

    def __str__(self):
        return self.name

class Product(models.Model):
    name = models.CharField("Название", max_length=200)
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="products",
        verbose_name="Категория",
    )

    class Meta:
        verbose_name = "Продукт"
        verbose_name_plural = "Список продуктов"
        ordering = ("name",)

    def __str__(self):
        return self.name

class ProductInfo(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="product_infos",
        verbose_name="Товар",
    )
    shop = models.ForeignKey(
        Shop,
        on_delete=models.PROTECT,
        related_name="product_infos",
        verbose_name="Магазин",
    )
    external_id = models.PositiveIntegerField("Код товара у поставщика")
    model = models.CharField("Модель", max_length=100, blank=True)
    quantity = models.PositiveIntegerField("Остаток", default=0)
    price = models.DecimalField(
        "Цена",
        max_digits=12,
        decimal_places=2,
    )
    price_rrc = models.DecimalField(
        "Рекомендуемая розничная цена",
        max_digits=12,
        decimal_places=2,
    )

    class Meta:
        verbose_name = "Информация о продукте"
        verbose_name_plural = "Информационный список о продуктах"
        constraints = [
            models.UniqueConstraint(
                fields=("shop", "external_id"),
                name="unique_shop_external_id",
            ),
        ]

    def __str__(self):
        return f"{self.product} — {self.shop}"


class Parameter(models.Model):
    name = models.CharField(
        "Название",
        max_length=100,
        unique=True,
    )

    class Meta:
        verbose_name = "Имя параметра"
        verbose_name_plural = "Список имен параметров"
        ordering = ("name",)

    def __str__(self):
        return self.name


class ProductParameter(models.Model):
    product_info = models.ForeignKey(
        ProductInfo,
        on_delete=models.CASCADE,
        related_name="product_parameters",
        verbose_name="Информация о продукте",
    )
    parameter = models.ForeignKey(
        Parameter,
        on_delete=models.PROTECT,
        related_name="product_parameters",
        verbose_name="Значение",
    )
    value = models.CharField("Значение", max_length=100)

    class Meta:
        verbose_name = "Параметр"
        verbose_name_plural = "Список параметров"
        constraints = [
            models.UniqueConstraint(
                fields=("product_info", "parameter"),
                name="unique_product_parameter",
            ),
        ]

    def __str__(self):
        return f"{self.parameter}: {self.value}"

class Contact(models.Model):
    user = models.ForeignKey(
        "backend.User",
        on_delete=models.CASCADE,
        related_name="contacts",
        verbose_name="Пользователь",
    )
    city = models.CharField("Город", max_length=100)
    street = models.CharField("Улица", max_length=150)
    house = models.CharField("Дом", max_length=20)
    structure = models.CharField("Корпус", max_length=20, blank=True)
    building = models.CharField("Строение", max_length=20, blank=True)
    apartment = models.CharField("Квартира", max_length=20, blank=True)
    phone = models.CharField("Телефон", max_length=20)

    class Meta:
        verbose_name = "Контакты пользователя"
        verbose_name_plural = "Список контактов пользователя"

    def __str__(self):
        return f"{self.city}, {self.street}, {self.house}"

class Order(models.Model):
    class State(models.TextChoices):
        BASKET = "basket", "Корзина"
        NEW = "new", "Новый"
        CONFIRMED = "confirmed", "Подтверждён"
        ASSEMBLED = "assembled", "Собран"
        SENT = "sent", "Отправлен"
        DELIVERED = "delivered", "Доставлен"
        CANCELED = "canceled", "Отменён"

    user = models.ForeignKey(
        "backend.User",
        on_delete=models.PROTECT,
        related_name="orders",
        verbose_name="Пользователь",
    )
    dt = models.DateTimeField("Дата создания", auto_now_add=True)
    state = models.CharField(
        "Статус",
        max_length=15,
        choices=State.choices,
        default=State.BASKET,
    )
    contact = models.ForeignKey(
        Contact,
        on_delete=models.PROTECT,
        related_name="orders",
        verbose_name="Контакт доставки",
        blank=True,
        null=True,
    )

    class Meta:
        verbose_name = "Заказ"
        verbose_name_plural = "Список заказ"
        ordering = ("-dt",)
        constraints = [
            models.UniqueConstraint(
                fields=("user",),
                condition=models.Q(state="basket"),
                name="unique_user_basket",
            ),
        ]

    def __str__(self):
        return f"Заказ №{self.pk}"
    
    @property
    def total(self):
        return sum(
            (item.total for item in self.ordered_items.all()),
            Decimal("0.00"),
        )

class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="ordered_items",
        verbose_name="Заказ",
    )
    product_info = models.ForeignKey(
        ProductInfo,
        on_delete=models.PROTECT,
        related_name="ordered_items",
        verbose_name="Информация о продукте",
    )
    quantity = models.PositiveIntegerField("Количество")
    price = models.DecimalField(
        "Цена за единицу на момент заказа",
        max_digits=12,
        decimal_places=2,
    )

    class Meta:
        verbose_name = "Заказанная позиция"
        verbose_name_plural = "Список заказанных позиций"
        constraints = [
            models.UniqueConstraint(
                fields=("order", "product_info"),
                name="unique_order_product_info",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="order_item_quantity_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(price__gte=0),
                name="order_item_price_nonnegative",
            ),
        ]

    def __str__(self):
        return f"{self.product_info} × {self.quantity}"

    @property
    def total(self):
        return self.price * self.quantity

class ConfirmEmailToken(models.Model):
    class Meta:
        verbose_name = 'Токен подтверждения Email'
        verbose_name_plural = 'Токены подтверждения Email'

    @staticmethod
    def generate_key():
        """ generates a pseudo random code using os.urandom and binascii.hexlify """
        return get_token_generator().generate_token()

    user = models.ForeignKey(
        User,
        related_name='confirm_email_tokens',
        on_delete=models.CASCADE,
        verbose_name='Пользователь'
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Created at"
    )

    # Key field, though it is not the primary key of the model
    key = models.CharField(
        "Key",
        max_length=64,
        db_index=True,
        unique=True
    )

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = self.generate_key()
        return super(ConfirmEmailToken, self).save(*args, **kwargs)

    def __str__(self):
        return "Password reset token for user {user}".format(user=self.user)
