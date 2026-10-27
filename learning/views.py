from django.contrib.auth.views import LoginView


class RememberMeLoginView(LoginView):
    """Login view that ends the session on browser close unless "remember me" is ticked."""

    def form_valid(self, form):
        response = super().form_valid(form)
        if not self.request.POST.get("remember_me"):
            self.request.session.set_expiry(0)
        return response
