from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.register, name="register"),
    path("login/", auth_views.LoginView.as_view(template_name="accounts/login.html", redirect_authenticated_user=True), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("profile/", views.profile, name="profile"),
    path(
        "password-change/",
        auth_views.PasswordChangeView.as_view(
            template_name="accounts/simple_form.html",
            success_url=reverse_lazy("accounts:profile"),
            extra_context={"title": "Change password", "button": "Update password"},
        ),
        name="password_change",
    ),
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="accounts/simple_form.html",
            email_template_name="accounts/emails/password_reset.txt",
            subject_template_name="accounts/emails/password_reset_subject.txt",
            success_url=reverse_lazy("accounts:password_reset_done"),
            extra_context={"title": "Reset your password", "button": "Send reset link",
                           "intro": "Enter your email and we will send you a link to choose a new password."},
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="accounts/message.html",
            extra_context={"title": "Check your email", "icon": "envelope-check",
                           "text": "If an account exists for that email, a reset link has been sent."},
        ),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="accounts/simple_form.html",
            success_url=reverse_lazy("accounts:password_reset_complete"),
            extra_context={"title": "Choose a new password", "button": "Save password"},
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/message.html",
            extra_context={"title": "Password updated", "icon": "check-circle",
                           "text": "Your password has been changed. You can now log in.", "login": True},
        ),
        name="password_reset_complete",
    ),
]
