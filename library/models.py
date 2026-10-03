from django.conf import settings
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Count, Q
from django.utils import timezone


class BookQuerySet(models.QuerySet):
    def with_availability(self):
        """Annotate each book with the number of copies currently on loan (avoids N+1 queries)."""
        return self.annotate(active_count=Count("loans", filter=Q(loans__return_date__isnull=True))).order_by("title", "id")


class Book(models.Model):
    CATEGORY_CHOICES = [
        ("fiction", "Fiction"),
        ("non_fiction", "Non-fiction"),
        ("science", "Science"),
        ("technology", "Technology"),
        ("history", "History"),
        ("biography", "Biography"),
        ("children", "Children"),
        ("reference", "Reference"),
        ("other", "Other"),
    ]

    title = models.CharField(max_length=200)
    author = models.CharField(max_length=150)
    isbn = models.CharField("ISBN", max_length=13, unique=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="other")
    total_copies = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    created_at = models.DateTimeField(auto_now_add=True)

    objects = BookQuerySet.as_manager()

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return f"{self.title} — {self.author}"

    @property
    def available_copies(self):
        active = getattr(self, "active_count", None)
        if active is None:
            active = self.loans.filter(return_date__isnull=True).count()
        return max(self.total_copies - active, 0)

    @property
    def is_available(self):
        return self.available_copies > 0


class Loan(models.Model):
    book = models.ForeignKey(Book, on_delete=models.PROTECT, related_name="loans")
    member = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="loans")
    borrow_date = models.DateField(default=timezone.localdate)
    due_date = models.DateField()
    return_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-borrow_date", "-id"]
        constraints = [
            # A member can't hold two unreturned copies of the same book (also enforced by the DB).
            models.UniqueConstraint(
                fields=["book", "member"],
                condition=Q(return_date__isnull=True),
                name="one_active_loan_per_member_book",
                violation_error_message="This member already has an unreturned copy of this book.",
            )
        ]

    def __str__(self):
        return f"{self.book.title} → {self.member}"

    def clean(self):
        errors = {}
        if self.borrow_date and self.due_date and self.due_date < self.borrow_date:
            errors["due_date"] = "Due date cannot be before the borrow date."
        if self.borrow_date and self.return_date and self.return_date < self.borrow_date:
            errors["return_date"] = "Return date cannot be before the borrow date."

        # Availability / limit checks only matter while the loan is still open.
        if self.return_date is None and self.book_id:
            others = Loan.objects.filter(return_date__isnull=True).exclude(pk=self.pk)
            if others.filter(book_id=self.book_id).count() >= self.book.total_copies:
                errors["book"] = "No copies of this book are currently available."
            if self.member_id and others.filter(member_id=self.member_id).count() >= settings.MAX_ACTIVE_LOANS:
                errors[NON_FIELD_ERRORS] = (
                    f"This member has reached the limit of {settings.MAX_ACTIVE_LOANS} active loans."
                )
        if errors:
            raise ValidationError(errors)

    @property
    def is_returned(self):
        return self.return_date is not None

    @property
    def is_overdue(self):
        return self.return_date is None and self.due_date < timezone.localdate()

    @property
    def status(self):
        if self.is_returned:
            return "Returned"
        return "Overdue" if self.is_overdue else "Borrowed"

    @property
    def badge_class(self):
        return {"Returned": "success", "Overdue": "danger", "Borrowed": "primary"}[self.status]
