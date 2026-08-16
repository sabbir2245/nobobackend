from django.shortcuts import render
from django.views.decorators.http import require_GET


@require_GET
def landing_page(request):
    return render(request, 'landing.html', {})