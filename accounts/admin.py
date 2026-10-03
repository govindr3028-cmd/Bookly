from django.contrib import admin

from .models import Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "mobile", "is_verified", "verified_at")
    list_filter = ("is_verified",)
    search_fields = ("user__username", "user__email", "mobile")
