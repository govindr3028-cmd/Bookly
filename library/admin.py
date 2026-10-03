from django.contrib import admin

from .models import Book, Loan


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ("title", "author", "isbn", "category", "total_copies")
    list_filter = ("category",)
    search_fields = ("title", "author", "isbn")


@admin.register(Loan)
class LoanAdmin(admin.ModelAdmin):
    list_display = ("book", "member", "borrow_date", "due_date", "return_date")
    list_filter = ("return_date",)
    search_fields = ("book__title", "member__username")
