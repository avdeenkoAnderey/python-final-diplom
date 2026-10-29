from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Shop, Category, Product, ProductInfo, Parameter, ProductParameter,Contact,Order,OrderItem


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    ordering = ("email",)
    list_display = ("email", "first_name", "last_name", "type", "is_staff")
    search_fields = ("email", "first_name", "last_name")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Личные данные", {
            "fields": ("first_name", "last_name", "company", "position", "type"),
        }),
        ("Права доступа", {
            "fields": (
                "is_active", "is_staff", "is_superuser",
                "groups", "user_permissions",
            ),
        }),
        ("Даты", {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "password1", "password2", "type"),
        }),
    )

@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "state")
    list_filter = ("state",)
    search_fields = ("name", "user__email")

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)
    filter_horizontal = ("shops",)

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "category")
    list_filter = ("category",)
    search_fields = ("name",)
    list_select_related = ("category",)

@admin.register(ProductInfo)
class ProductInfoAdmin(admin.ModelAdmin):
    list_display = ("product", "shop", "price", "quantity", "external_id")
    list_filter = ("shop",)
    search_fields = ("product__name", "model")
    list_select_related = ("product", "shop")

@admin.register(Parameter)
class ParameterAdmin(admin.ModelAdmin):
    search_fields = ("name",)


@admin.register(ProductParameter)
class ProductParameterAdmin(admin.ModelAdmin):
    list_display = ("product_info", "parameter", "value")
    list_filter = ("parameter",)
    search_fields = ("product_info__product__name", "value")
    list_select_related = (
        "product_info__product",
        "product_info__shop",
        "parameter",
    )
@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ("user", "city", "street", "house", "phone")
    search_fields = ("user__email", "city", "street", "phone")
    list_select_related = ("user",)

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):

    list_display = ("id", "user", "state", "dt", "contact", "total")
    list_filter = ("state",)
    search_fields = ("user__email",)
    list_select_related = ("user", "contact")
    readonly_fields = ("dt","total")

@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("order", "product_info", "quantity", "price", "total")
    search_fields = ("product_info__product__name",)
    list_select_related = (
        "order",
        "product_info__product",
        "product_info__shop",
    )

from .models import ConfirmEmailToken


@admin.register(ConfirmEmailToken)
class ConfirmEmailTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "key", "created_at")
    list_select_related = ("user",)
    readonly_fields = ("key", "created_at")
