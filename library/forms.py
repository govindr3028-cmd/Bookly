import re

from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from accounts.forms import BootstrapFormMixin

from .models import Book, Loan

DATE_WIDGET = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class BookForm(BootstrapFormMixin, forms.ModelForm):
    # Longer than the model field so hyphens/spaces can be typed; clean_isbn() normalises to 10/13 chars.
    isbn = forms.CharField(label="ISBN", max_length=17, help_text="ISBN-10 or ISBN-13; hyphens are fine.")

    class Meta:
        model = Book
        fields = ["title", "author", "isbn", "category", "total_copies"]

    def clean_isbn(self):
        isbn = re.sub(r"[\s-]", "", self.cleaned_data["isbn"]).upper()
        if not re.fullmatch(r"[0-9]{13}|[0-9]{9}[0-9X]", isbn):
            raise ValidationError("Enter a valid ISBN-10 or ISBN-13 (hyphens allowed).")
        return isbn

    def clean_total_copies(self):
        total = self.cleaned_data["total_copies"]
        if self.instance.pk:
            on_loan = self.instance.loans.filter(return_date__isnull=True).count()
            if total < on_loan:
                raise ValidationError(f"{on_loan} copies are currently on loan; the total can't be lower than that.")
        return total


class LoanForm(BootstrapFormMixin, forms.ModelForm):
    """Staff-only form. Availability rules live in Loan.clean()."""

    class Meta:
        model = Loan
        fields = ["book", "member", "borrow_date", "due_date", "return_date"]
        widgets = {"borrow_date": DATE_WIDGET, "due_date": DATE_WIDGET, "return_date": DATE_WIDGET}
        help_texts = {"return_date": "Leave empty while the book is still out."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["book"].queryset = Book.objects.order_by("title")
        self.fields["member"].queryset = User.objects.filter(is_active=True).order_by("username")
        self.fields["member"].label_from_instance = lambda u: f"{u.first_name or u.username} ({u.username})"
