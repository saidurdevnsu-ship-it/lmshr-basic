from django.contrib.auth.views import LoginView
from django.shortcuts import redirect


def home(request):
    """Site root: the dashboard when signed in, otherwise the sign-in page."""
    return redirect("admin:index" if request.user.is_authenticated else "login")


class RememberMeLoginView(LoginView):
    """Login view that ends the session on browser close unless "remember me" is ticked."""

    def form_valid(self, form):
        response = super().form_valid(form)
        if not self.request.POST.get("remember_me"):
            self.request.session.set_expiry(0)
        return response
