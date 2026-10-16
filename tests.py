from django.contrib.auth import get_user_model
from django.urls import reverse

from eventhub.testutils import PASSWORD, BaseTestCase

User = get_user_model()

REG = {"username": "newuser", "first_name": "New", "last_name": "User", "email": "new@example.com",
       "password1": PASSWORD, "password2": PASSWORD, "role": "customer", "phone": "+8801711111111"}


class AuthenticationTests(BaseTestCase):
    def test_register_customer(self):
        resp = self.client.post(reverse("accounts:register"), REG)
        self.assertRedirects(resp, reverse("dashboard:home"), fetch_redirect_response=False)
        user = User.objects.get(username="newuser")
        self.assertEqual(user.profile.role, "customer")
        self.assertEqual(user.profile.phone, "+8801711111111")
        self.assertIn("_auth_user_id", self.client.session)  # logged in

    def test_register_organizer(self):
        self.client.post(reverse("accounts:register"), {**REG, "role": "organizer"})
        self.assertEqual(User.objects.get(username="newuser").profile.role, "organizer")

    def test_cannot_self_register_as_admin(self):
        resp = self.client.post(reverse("accounts:register"), {**REG, "role": "admin"})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username="newuser").exists())

    def test_duplicate_email_rejected(self):
        resp = self.client.post(reverse("accounts:register"), {**REG, "email": "CUST1@example.com"})
        self.assertContains(resp, "already exists")

    def test_weak_password_rejected(self):
        resp = self.client.post(reverse("accounts:register"), {**REG, "password1": "12345678", "password2": "12345678"})
        self.assertFalse(User.objects.filter(username="newuser").exists())
        self.assertEqual(resp.status_code, 200)

    def test_password_is_hashed(self):
        self.client.post(reverse("accounts:register"), REG)
        stored = User.objects.get(username="newuser").password
        self.assertNotIn(PASSWORD, stored)
        self.assertIn("$", stored)  # algorithm$salt$hash

    def test_login_and_logout(self):
        resp = self.client.post(reverse("accounts:login"), {"username": "cust1", "password": PASSWORD})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)
        self.client.post(reverse("accounts:logout"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_wrong_password(self):
        resp = self.client.post(reverse("accounts:login"), {"username": "cust1", "password": "wrong"})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_inactive_user_cannot_login(self):
        self.customer.is_active = False
        self.customer.save()
        self.client.post(reverse("accounts:login"), {"username": "cust1", "password": PASSWORD})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_csrf_enforced_on_login(self):
        from django.test import Client

        resp = Client(enforce_csrf_checks=True).post(reverse("accounts:login"), {"username": "cust1", "password": PASSWORD})
        self.assertEqual(resp.status_code, 403)

    def test_profile_requires_login(self):
        resp = self.client.get(reverse("accounts:profile"))
        self.assertRedirects(resp, f"{reverse('accounts:login')}?next={reverse('accounts:profile')}")

    def test_profile_update(self):
        self.login(self.customer)
        resp = self.client.post(reverse("accounts:profile"), {"first_name": "Changed", "last_name": "Name", "email": "x@example.com",
                                                              "phone": "+8801799999999", "city": "Dhaka", "address": "", "bio": ""})
        self.assertRedirects(resp, reverse("accounts:profile"))
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.first_name, "Changed")
        self.assertEqual(self.customer.profile.phone, "+8801799999999")

    def test_profile_email_must_be_unique(self):
        self.login(self.customer)
        resp = self.client.post(reverse("accounts:profile"), {"first_name": "A", "last_name": "B", "email": self.organizer.email,
                                                              "phone": "", "city": "", "address": "", "bio": ""})
        self.assertEqual(resp.status_code, 200)
        self.customer.refresh_from_db()
        self.assertNotEqual(self.customer.email, self.organizer.email)

    def test_dashboard_redirects_by_role(self):
        for user, name in [(self.customer, "customer"), (self.organizer, "organizer"), (self.admin, "admin")]:
            self.client.force_login(user)
            self.assertRedirects(self.client.get(reverse("dashboard:home")), reverse(f"dashboard:{name}"))

    def test_superuser_gets_admin_role(self):
        su = User.objects.create_superuser("root", "root@example.com", PASSWORD)
        self.assertEqual(su.profile.role, "admin")
