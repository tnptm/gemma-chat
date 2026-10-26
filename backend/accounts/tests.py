from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

User = get_user_model()


class UserManagementTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin", password="admin-password", is_staff=True
        )
        self.client.force_authenticate(self.admin)

    def test_admin_can_list_and_create_users(self):
        response = self.client.get("/api/admin/users/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertNotIn("password", response.data[0])

        response = self.client.post(
            "/api/admin/users/",
            {
                "username": "new-user",
                "email": "new-user@example.com",
                "password": "a-long-safe-password",
                "is_admin": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        user = User.objects.get(username="new-user")
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.check_password("a-long-safe-password"))
        self.assertEqual(user.email, "new-user@example.com")
        self.assertEqual(response.data["email"], "new-user@example.com")

    def test_admin_can_edit_user_and_change_password(self):
        user = User.objects.create_user(username="regular", password="old-password")
        response = self.client.patch(
            f"/api/admin/users/{user.pk}",
            {
                "username": "renamed",
                "email": "renamed@example.com",
                "password": "a-new-safe-password",
                "is_admin": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.username, "renamed")
        self.assertEqual(user.email, "renamed@example.com")
        self.assertEqual(response.data["email"], "renamed@example.com")
        self.assertTrue(user.is_staff)
        self.assertTrue(user.check_password("a-new-safe-password"))

    def test_admin_can_delete_another_user(self):
        user = User.objects.create_user(username="remove-me", password="some-password")
        response = self.client.delete(f"/api/admin/users/{user.pk}")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(User.objects.filter(pk=user.pk).exists())

    def test_admin_cannot_delete_or_demote_self(self):
        response = self.client.delete(f"/api/admin/users/{self.admin.pk}")
        self.assertEqual(response.status_code, 400)
        response = self.client.patch(
            f"/api/admin/users/{self.admin.pk}", {"is_admin": False}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_staff)

    def test_non_admin_cannot_manage_users(self):
        regular = User.objects.create_user(username="regular", password="some-password")
        self.client.force_authenticate(regular)
        self.assertEqual(self.client.get("/api/admin/users/").status_code, 403)

    def test_new_user_requires_valid_password(self):
        response = self.client.post(
            "/api/admin/users/",
            {"username": "short-password", "password": "short", "is_admin": False},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username="short-password").exists())
