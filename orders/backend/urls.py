from django.urls import path

from .views import CategoryView, ShopView, ProductInfoView, ProductInfoDetailView, RegisterAccount,ConfirmAccount,LoginAccount, ContactDetailView
from .account_api import ProfileView, PasswordResetView, PasswordResetConfirmView
from .order_api import BasketView, BasketItemView, OrderView, OrderDetailView, OrderStatusView
from .partner_api import PartnerUpdate, PartnerState, PartnerOrders

app_name = "backend"

urlpatterns = [
    path("categories", CategoryView.as_view(), name="categories"),
    path("shops", ShopView.as_view(), name="shops"),
    path("products", ProductInfoView.as_view(), name="products"),
    path("products/<int:pk>",ProductInfoDetailView.as_view(),name="product-detail"),
    path("user/register",RegisterAccount.as_view(),name="user-register"),
    path("user/register/confirm",ConfirmAccount.as_view(),name="user-register-confirm"),
    path("user/login", LoginAccount.as_view(), name="user-login"),
    path("user/login/", LoginAccount.as_view()),
    path("user/details",ProfileView.as_view(),name="user-details"),
    path("user/contact/<int:pk>",ContactDetailView.as_view(),name="user-contact-detail")
]

from .views import ContactView

urlpatterns += [
    path("user/contact", ContactView.as_view(), name="user-contact"),
    path('basket', BasketView.as_view(), name='basket'),
    path('basket/<int:pk>', BasketItemView.as_view(), name='basket-item'),
    path('order', OrderView.as_view(), name='order'),
    path('order/<int:pk>', OrderDetailView.as_view(), name='order-detail'),
    path('order/<int:pk>/status', OrderStatusView.as_view(), name='order-status'),
    path('partner/update', PartnerUpdate.as_view(), name='partner-update'),
    path('partner/state', PartnerState.as_view(), name='partner-state'),
    path('partner/orders', PartnerOrders.as_view(), name='partner-orders'),
    path('user/password_reset', PasswordResetView.as_view(), name='password-reset'),
    path('user/password_reset/confirm', PasswordResetConfirmView.as_view(), name='password-reset-confirm'),
]

# Accept both address styles, including for POST requests without redirects.
urlpatterns += [path(str(route.pattern) + '/', route.callback)
                for route in list(urlpatterns) if not str(route.pattern).endswith('/')]
