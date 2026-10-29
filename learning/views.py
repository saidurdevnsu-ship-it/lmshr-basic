from django.contrib.auth import logout
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect

from .forms import SignInForm


def home(request):
    """Site root: the dashboard for staff, otherwise the sign-in page.

    A signed-in account without dashboard access is signed out first; sending it to /admin/ would loop back here.
    """
    if request.user.is_authenticated and not request.user.is_staff:
        logout(request)
    return redirect("admin:index" if request.user.is_authenticated else "login")


class RememberMeLoginView(LoginView):
    """Login view that ends the session on browser close unless "remember me" is ticked."""

    form_class = SignInForm

    def form_valid(self, form):
        response = super().form_valid(form)
        if not self.request.POST.get("remember_me"):
            self.request.session.set_expiry(0)
        return response
