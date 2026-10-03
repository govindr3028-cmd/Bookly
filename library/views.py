from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F, Q
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import staff_required, verified_required

from .forms import BookForm, LoanForm
from .models import Book, Loan


# ---------- helpers ----------
def visible_loans(user):
    """Loans the user may see: staff see all, members only their own (blocks ID-guessing)."""
    qs = Loan.objects.select_related("book", "member")
    return qs if user.is_staff else qs.filter(member=user)


def _paginate(request, queryset, per_page):
    page_obj = Paginator(queryset, per_page).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return page_obj, params.urlencode()


def _form_page(request, form, title, cancel_url, submit_label="Save"):
    context = {"form": form, "title": title, "cancel_url": cancel_url, "submit_label": submit_label}
    return render(request, "form_page.html", context)


def _lock_book(raw_pk):
    """Row-lock the book (no-op on SQLite) so concurrent borrows can't oversell the last copy."""
    try:
        Book.objects.select_for_update().get(pk=raw_pk)
    except (Book.DoesNotExist, ValueError, TypeError):
        pass


# ---------- dashboard ----------
@verified_required
def dashboard(request):
    mine = Loan.objects.filter(member=request.user).select_related("book")
    today = timezone.localdate()
    active = mine.filter(return_date__isnull=True).order_by("due_date")
    context = {
        "active_loans": active,
        "recent_history": mine.filter(return_date__isnull=False)[:5],
        "overdue_count": active.filter(due_date__lt=today).count(),
        "total_borrowed": mine.count(),
    }
    if request.user.is_staff:
        open_loans = Loan.objects.filter(return_date__isnull=True)
        context.update(
            staff_books=Book.objects.count(),
            staff_open=open_loans.count(),
            staff_overdue=open_loans.filter(due_date__lt=today).count(),
        )
    return render(request, "library/dashboard.html", context)


# ---------- books ----------
@verified_required
def book_list(request):
    books = Book.objects.with_availability()
    q = request.GET.get("q", "").strip()
    category = request.GET.get("category", "")
    if q:
        books = books.filter(Q(title__icontains=q) | Q(author__icontains=q) | Q(isbn__icontains=q))
    if category in dict(Book.CATEGORY_CHOICES):
        books = books.filter(category=category)
    if request.GET.get("available"):
        books = books.filter(active_count__lt=F("total_copies"))
    page_obj, qs = _paginate(request, books, 9)
    context = {
        "page_obj": page_obj,
        "qs": qs,
        "q": q,
        "category": category,
        "only_available": bool(request.GET.get("available")),
        "categories": Book.CATEGORY_CHOICES,
    }
    return render(request, "library/book_list.html", context)


@verified_required
def book_detail(request, pk):
    book = get_object_or_404(Book.objects.with_availability(), pk=pk)
    context = {"book": book}
    if request.user.is_staff:
        context["open_loans"] = book.loans.filter(return_date__isnull=True).select_related("member")
    return render(request, "library/book_detail.html", context)


@staff_required
def book_create(request):
    form = BookForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        book = form.save()
        messages.success(request, f"“{book.title}” was added to the catalogue.")
        return redirect("book_detail", pk=book.pk)
    return _form_page(request, form, "Add a book", reverse("book_list"), "Save book")


@staff_required
def book_update(request, pk):
    book = get_object_or_404(Book, pk=pk)
    form = BookForm(request.POST if request.method == "POST" else None, instance=book)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"“{book.title}” was updated.")
        return redirect("book_detail", pk=book.pk)
    return _form_page(request, form, f"Edit “{book.title}”", reverse("book_detail", args=[pk]), "Save changes")


@staff_required
def book_delete(request, pk):
    book = get_object_or_404(Book, pk=pk)
    if request.method == "POST":
        title = book.title
        try:
            book.delete()
        except ProtectedError:
            messages.error(request, "This book has borrowing records, so it can't be deleted.")
            return redirect("book_detail", pk=pk)
        messages.success(request, f"“{title}” was deleted.")
        return redirect("book_list")
    context = {
        "title": "Delete book",
        "object_label": f"{book.title} by {book.author}",
        "cancel_url": reverse("book_detail", args=[pk]),
        "note": "Books that already have borrowing records can't be deleted.",
    }
    return render(request, "confirm_delete.html", context)


# ---------- loans ----------
@verified_required
@require_POST
def borrow_book(request, pk):
    """Self-service borrowing for the logged-in member."""
    with transaction.atomic():
        book = get_object_or_404(Book.objects.select_for_update(), pk=pk)
        today = timezone.localdate()
        loan = Loan(
            book=book, member=request.user, borrow_date=today, due_date=today + timedelta(days=settings.LOAN_PERIOD_DAYS)
        )
        try:
            loan.full_clean()
        except ValidationError as exc:
            for msg in dict.fromkeys(exc.messages):
                messages.error(request, msg)
        else:
            loan.save()
            messages.success(request, f"You borrowed “{book.title}”. Please return it by {loan.due_date:%d %b %Y}.")
    return redirect("book_detail", pk=pk)


@verified_required
def loan_list(request):
    loans = visible_loans(request.user)
    status = request.GET.get("status", "")
    q = request.GET.get("q", "").strip()
    today = timezone.localdate()
    if status == "active":
        loans = loans.filter(return_date__isnull=True)
    elif status == "overdue":
        loans = loans.filter(return_date__isnull=True, due_date__lt=today)
    elif status == "returned":
        loans = loans.filter(return_date__isnull=False)
    if q:
        cond = Q(book__title__icontains=q) | Q(book__isbn__icontains=q)
        if request.user.is_staff:
            cond |= Q(member__username__icontains=q) | Q(member__first_name__icontains=q)
        loans = loans.filter(cond)
    page_obj, qs = _paginate(request, loans, 10)
    return render(request, "library/loan_list.html", {"page_obj": page_obj, "qs": qs, "q": q, "status": status})


@verified_required
def loan_detail(request, pk):
    # Scoped queryset: another member's loan simply 404s, whatever ID is typed into the URL.
    loan = get_object_or_404(visible_loans(request.user), pk=pk)
    return render(request, "library/loan_detail.html", {"loan": loan})


def _loan_form_view(request, loan, title, initial=None):
    if request.method == "POST":
        with transaction.atomic():
            _lock_book(request.POST.get("book"))
            form = LoanForm(request.POST, instance=loan)
            if form.is_valid():
                saved = form.save()
                messages.success(request, "Borrowing record saved.")
                return redirect("loan_detail", pk=saved.pk)
    else:
        form = LoanForm(instance=loan, initial=initial)
    return _form_page(request, form, title, reverse("loan_list"), "Save record")


@staff_required
def loan_create(request):
    today = timezone.localdate()
    initial = {
        "borrow_date": today,
        "due_date": today + timedelta(days=settings.LOAN_PERIOD_DAYS),
        "book": request.GET.get("book"),
    }
    return _loan_form_view(request, None, "Issue a book", initial)


@staff_required
def loan_update(request, pk):
    loan = get_object_or_404(Loan, pk=pk)
    return _loan_form_view(request, loan, "Edit borrowing record")


@staff_required
@require_POST
def loan_return(request, pk):
    loan = get_object_or_404(Loan, pk=pk)
    if loan.is_returned:
        messages.warning(request, "This book was already returned.")
    else:
        loan.return_date = timezone.localdate()
        loan.save(update_fields=["return_date"])
        messages.success(request, f"“{loan.book.title}” marked as returned.")
    return redirect("loan_list")


@staff_required
def loan_delete(request, pk):
    loan = get_object_or_404(Loan.objects.select_related("book", "member"), pk=pk)
    if request.method == "POST":
        loan.delete()
        messages.success(request, "Borrowing record deleted.")
        return redirect("loan_list")
    context = {
        "title": "Delete borrowing record",
        "object_label": f"{loan.book.title} — {loan.member.first_name or loan.member.username}",
        "cancel_url": reverse("loan_detail", args=[pk]),
        "note": "This permanently removes the record from the member's history.",
    }
    return render(request, "confirm_delete.html", context)
