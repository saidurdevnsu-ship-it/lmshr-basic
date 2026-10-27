from django.contrib import admin
from django.urls import include, path

from learning.views import RememberMeLoginView

admin.site.site_header = "STS LMS & HR Administration"
admin.site.site_title = "STS LMS & HR Administration"
admin.site.index_title = "STS LMS & HR Administration"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/login/", RememberMeLoginView.as_view(), name="login"),
    path("accounts/", include("django.contrib.auth.urls")),
]
