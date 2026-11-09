from rest_framework.generics import ListAPIView, RetrieveAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from .models import Category, Shop, ConfirmEmailToken, ProductInfo
from .serializers import CategorySerializer, ShopSerializer, ProductInfoSerializer, RegisterSerializer, ConfirmAccountSerializer, LoginSerializer, UserSerializer
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models.deletion import ProtectedError
from rest_framework.exceptions import ValidationError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth import authenticate
from rest_framework.authtoken.models import Token

class CategoryView(ListAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = (AllowAny,)


class ShopView(ListAPIView):
    queryset = Shop.objects.filter(state=True)
    serializer_class = ShopSerializer
    permission_classes = (AllowAny,)


class ProductInfoView(ListAPIView):
    serializer_class = ProductInfoSerializer
    permission_classes = (AllowAny,)

    def get_queryset(self):
        queryset = (
            ProductInfo.objects
            .filter(shop__state=True)
            .select_related("product__category", "shop")
            .prefetch_related("product_parameters__parameter")
        )

        shop_id = self.request.query_params.get("shop_id")
        category_id = self.request.query_params.get("category_id")

        if shop_id and (not shop_id.isdecimal() or int(shop_id) < 1):
            raise ValidationError({'shop_id': 'Укажите положительное целое число.'})
        if category_id and (not category_id.isdecimal() or int(category_id) < 1):
            raise ValidationError({'category_id': 'Укажите положительное целое число.'})
        if shop_id:
            queryset = queryset.filter(shop_id=shop_id)

        if category_id:
            queryset = queryset.filter(product__category_id=category_id)

        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(product__name__icontains=search)

        return queryset

class ProductInfoDetailView(RetrieveAPIView):
    serializer_class = ProductInfoSerializer
    permission_classes = (AllowAny,)
    queryset = (
        ProductInfo.objects
        .filter(shop__state=True)
        .select_related("product__category", "shop")
        .prefetch_related("product_parameters__parameter")
    )

class RegisterAccount(APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            user = serializer.save()
            token = ConfirmEmailToken.objects.create(user=user)

            send_mail(
                subject="Подтверждение регистрации",
                message=f"Ваш токен подтверждения: {token.key}",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
            )

        return Response(
            {"detail": "Пользователь создан. Подтвердите email."},
            status=status.HTTP_201_CREATED,
        )

class ConfirmAccount(APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        serializer = ConfirmAccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            token = (
                ConfirmEmailToken.objects
                .select_for_update()
                .select_related("user")
                .filter(
                    user__email=serializer.validated_data["email"],
                    key=serializer.validated_data["token"],
                )
                .first()
            )

            if token is None:
                return Response(
                    {"detail": "Неверный email или токен."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            user = token.user
            user.is_active = True
            user.save(update_fields=["is_active"])
            token.delete()

        return Response({"detail": "Email подтверждён."})

class LoginAccount(APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = authenticate(
            request=request,
            email=serializer.validated_data["email"],
            password=serializer.validated_data["password"],
        )

        if user is None:
            return Response(
                {"detail": "Неверный email или пароль либо аккаунт не активирован."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        token, _ = Token.objects.get_or_create(user=user)

        return Response({"token": token.key})


class AccountDetails(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

from rest_framework.generics import ListCreateAPIView
from rest_framework.permissions import IsAuthenticated
from .models import Contact
from .serializers import ContactSerializer


class ContactView(ListCreateAPIView):
    serializer_class = ContactSerializer
    permission_classes = (IsAuthenticated,)

    def get_queryset(self):
        return Contact.objects.filter(user=self.request.user).order_by("id")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class ContactDetailView(RetrieveUpdateDestroyAPIView):
    serializer_class = ContactSerializer
    permission_classes = (IsAuthenticated,)

    def get_queryset(self):
        return Contact.objects.filter(user=self.request.user)

    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError as error:
            raise ValidationError('Контакт используется в заказе и не может быть удалён.') from error
