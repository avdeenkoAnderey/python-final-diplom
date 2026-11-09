"""Редактирование профиля и восстановление пароля."""
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework import serializers
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import User
from .serializers import UserSerializer
from .views import AccountDetails


class ProfileInput(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'company', 'position')


class ProfileView(AccountDetails):
    def patch(self, request):
        data = ProfileInput(request.user, data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        data.save()
        return Response(UserSerializer(request.user).data)

    post = patch


class ResetRequest(serializers.Serializer):
    email = serializers.EmailField()


class ResetConfirm(serializers.Serializer):
    uid = serializers.CharField(max_length=128)
    token = serializers.CharField(max_length=128)
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class PasswordResetView(APIView):
    permission_classes = (AllowAny,)
    authentication_classes = ()

    def post(self, request):
        data = ResetRequest(data=request.data)
        data.is_valid(raise_exception=True)
        user = User.objects.filter(email=data.validated_data['email'], is_active=True).first()
        if user and user.has_usable_password():
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            send_mail('Восстановление пароля',
                      f'Для сброса пароля отправьте uid: {uid} и token: {token} вместе с новым password '
                      'на /api/v1/user/password_reset/confirm.',
                      settings.DEFAULT_FROM_EMAIL, [user.email])
        return Response({'detail': 'Если активный аккаунт существует, письмо отправлено.'})


class PasswordResetConfirmView(APIView):
    permission_classes = (AllowAny,)
    authentication_classes = ()

    @transaction.atomic
    def post(self, request):
        data = ResetConfirm(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            pk = urlsafe_base64_decode(data.validated_data['uid']).decode()
            user = User.objects.select_for_update().get(pk=pk, is_active=True)
        except (ValueError, OverflowError, UnicodeError, User.DoesNotExist):
            raise serializers.ValidationError('Недействительный токен.')
        if not default_token_generator.check_token(user, data.validated_data['token']):
            raise serializers.ValidationError('Недействительный или просроченный токен.')
        try:
            validate_password(data.validated_data['password'], user=user)
        except DjangoValidationError as error:
            raise serializers.ValidationError({'password': error.messages}) from error
        user.set_password(data.validated_data['password'])
        user.save(update_fields=['password'])
        Token.objects.filter(user=user).delete()
        return Response({'detail': 'Пароль изменён. Войдите с новым паролем.'})
