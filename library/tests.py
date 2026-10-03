from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile

from .models import Book, Loan


def make_user(name, staff=False, verified=True):
    user = User.objects.create_user(name, f"{name}@example.com", "Str0ng!Pass#42", is_staff=staff, first_name=name.title())
    if not staff:
        Profile.objects.create(user=user, mobile="9876543210", is_verified=verified)
    return user


class LibraryTests(TestCase):
    def setUp(self):
        self.alice, self.bob = make_user("alice"), make_user("bob")
        self.staff = make_user("lib", staff=True)
        self.book = Book.objects.create(title="Dune", author="Frank Herbert", isbn="9780441013593", total_copies=1)

    def borrow(self, user, book=None):
        self.client.force_login(user)
        return self.client.post(reverse("borrow_book", args=[(book or self.book).pk]), follow=True)

    def test_borrow_then_no_copies_left(self):
        self.assertContains(self.borrow(self.alice), "You borrowed")
        r = self.borrow(self.bob)
        self.assertContains(r, "No copies of this book are currently available")
        self.assertEqual(Loan.objects.count(), 1)

    def test_same_member_cannot_borrow_twice(self):
        self.book.total_copies = 3
        self.book.save()
        self.borrow(self.alice)
        self.assertContains(self.borrow(self.alice), "already has an unreturned copy")
        self.assertEqual(Loan.objects.count(), 1)

    def test_return_frees_copy(self):
        self.borrow(self.alice)
        loan = Loan.objects.get()
        self.client.force_login(self.staff)
        self.client.post(reverse("loan_return", args=[loan.pk]))
        self.assertTrue(Book.objects.get().is_available)
        self.assertContains(self.borrow(self.bob), "You borrowed")

    def test_loan_limit(self):
        for i in range(5):
            b = Book.objects.create(title=f"B{i}", author="A", isbn=f"97800000000{i:02d}", total_copies=1)
            Loan.objects.create(book=b, member=self.alice, due_date=timezone.localdate())
        self.assertContains(self.borrow(self.alice), "limit of 5 active loans")

    def test_member_cannot_see_other_members_loan(self):
        self.borrow(self.alice)
        loan = Loan.objects.get()
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(reverse("loan_detail", args=[loan.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("loan_list")), "Dune")
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse("loan_detail", args=[loan.pk])).status_code, 200)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("loan_detail", args=[loan.pk])).status_code, 200)

    def test_member_cannot_manage_books_or_loans(self):
        self.client.force_login(self.alice)
        for name, args in [("book_create", []), ("book_update", [self.book.pk]), ("book_delete", [self.book.pk]),
                           ("loan_create", [])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 403, name)
        self.assertEqual(self.client.post(reverse("book_delete", args=[self.book.pk])).status_code, 403)
        self.assertTrue(Book.objects.exists())

    def test_staff_book_crud(self):
        self.client.force_login(self.staff)
        r = self.client.post(reverse("book_create"), {
            "title": "Emma", "author": "Jane Austen", "isbn": "978-0-14-143958-7", "category": "fiction", "total_copies": 2})
        book = Book.objects.get(title="Emma")
        self.assertRedirects(r, reverse("book_detail", args=[book.pk]))
        self.assertEqual(book.isbn, "9780141439587")
        self.client.post(reverse("book_update", args=[book.pk]), {
            "title": "Emma", "author": "Jane Austen", "isbn": book.isbn, "category": "fiction", "total_copies": 5})
        self.assertEqual(Book.objects.get(pk=book.pk).total_copies, 5)
        self.client.post(reverse("book_delete", args=[book.pk]))
        self.assertFalse(Book.objects.filter(pk=book.pk).exists())

    def test_staff_issue_loan_respects_availability(self):
        Loan.objects.create(book=self.book, member=self.alice, due_date=timezone.localdate())
        self.client.force_login(self.staff)
        today = timezone.localdate()
        r = self.client.post(reverse("loan_create"), {
            "book": self.book.pk, "member": self.bob.pk, "borrow_date": today, "due_date": today})
        self.assertContains(r, "No copies of this book are currently available")
        self.assertEqual(Loan.objects.count(), 1)

    def test_cannot_delete_book_with_loans(self):
        Loan.objects.create(book=self.book, member=self.alice, due_date=timezone.localdate())
        self.client.force_login(self.staff)
        self.client.post(reverse("book_delete", args=[self.book.pk]))
        self.assertTrue(Book.objects.exists())

    def test_cannot_lower_total_below_copies_on_loan(self):
        Loan.objects.create(book=self.book, member=self.alice, due_date=timezone.localdate())
        self.client.force_login(self.staff)
        r = self.client.post(reverse("book_update", args=[self.book.pk]), {
            "title": "Dune", "author": "Frank Herbert", "isbn": self.book.isbn, "category": "other", "total_copies": 0})
        self.assertIn("total_copies", r.context["form"].errors)

    def test_anonymous_and_unverified_are_redirected(self):
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)
        self.client.force_login(make_user("carl", verified=False))
        self.assertEqual(self.client.get(reverse("book_list")).status_code, 302)

    def test_pages_render(self):
        self.borrow(self.alice)
        for name in ("dashboard", "book_list", "loan_list"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.assertEqual(self.client.get(reverse("book_detail", args=[self.book.pk])).status_code, 200)


class SiteWideSmokeTests(TestCase):
    """Every GET page renders (no template/500 errors) for anonymous, member and staff users."""

    def setUp(self):
        self.member, self.staff = make_user("mia"), make_user("sam", staff=True)
        self.book = Book.objects.create(title="Emma", author="Jane Austen", isbn="9780141439587", total_copies=2)
        self.loan = Loan.objects.create(book=self.book, member=self.member, due_date=timezone.localdate())

    def urls(self):
        b, l = self.book.pk, self.loan.pk
        return [reverse(n) for n in ("home", "dashboard", "book_list", "loan_list", "book_create", "loan_create")] + [
            reverse("book_detail", args=[b]), reverse("book_update", args=[b]), reverse("book_delete", args=[b]),
            reverse("loan_detail", args=[l]), reverse("loan_update", args=[l]), reverse("loan_delete", args=[l]),
            reverse("book_list") + "?q=em&category=fiction&available=1&page=9",
            reverse("loan_list") + "?status=overdue&q=emma",
        ]

    def test_public_pages(self):
        for name in ("login", "register"):
            r = self.client.get(reverse(name))
            self.assertContains(r, "Bookly")

    def test_member_and_staff_never_hit_a_500(self):
        for user in (self.member, self.staff):
            self.client.force_login(user)
            for url in self.urls():
                r = self.client.get(url)
                self.assertIn(r.status_code, (200, 302, 403, 404), f"{user} {url} -> {r.status_code}")
        self.client.force_login(self.staff)
        for url in self.urls():
            expected = 302 if url == "/" else 200
            self.assertEqual(self.client.get(url).status_code, expected, url)

    def test_custom_error_pages(self):
        self.client.force_login(self.member)
        self.assertContains(self.client.get("/nope/"), "Page not found", status_code=404)
        self.assertContains(self.client.get(reverse("book_create")), "Only library staff", status_code=403)
