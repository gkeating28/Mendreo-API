"""
URL configuration for mendreo project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.urls import path, include
from django.http import JsonResponse


def home(_request):
    return JsonResponse({
        "service": "mendreo-api",
        "status": "ok",
        "docs": "DRF endpoints live under /sessions, /consumers, etc.",
    })


def elevenlabs_config(_request):
    """TEMPORARY: presence-only probe for Railway env debugging. Do not return values."""
    from api.voice.elevenlabs_client import config_presence

    return JsonResponse(config_presence())


urlpatterns = [
    path("", home, name="home"),
    # Not intercepted by wsgi.py (`/` and `/healthz` are static). Remove after debug.
    path("healthz/elevenlabs", elevenlabs_config, name="elevenlabs_config"),
    path("internal/", include("api.internal.urls")),
    path("", include('api.urls')),
]
