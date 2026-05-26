from django.conf import settings
from django.conf.urls import include
from django.urls import path

urlpatterns = [
    path('user', include('api.user.urls')),

    path('agents', include('api.agent.urls')),
    path('admins', include('api.admin.urls')),
    path('consumers', include('api.consumer.urls')),
    path('roles', include('api.role.urls')),

    path('images', include('api.image.urls')),
    path('files', include('api.file.urls')),

    path('posts', include('api.post.urls')),

    path('questions', include('api.question.urls')),
    path('attributes', include('api.attribute.urls')),

    path('packages', include('api.package.urls')),
    path('subscriptions', include('api.subscription.urls')),

    path('onboarding', include('api.onboarding.urls')),
    path('survey', include('api.survey.urls')),
    
    path('sessions', include('api.session.urls')),
    path('messages', include('api.message.urls')),
    path('summaries', include('api.summary.urls')),

    path('exercises', include('api.exercise.urls')),
    path('exercise-summaries', include('api.exercise_summary.urls')),

    path('tags', include('api.tag.urls')),
    path('assets', include('api.asset.urls')),
    path('feedback', include('api.feedback.urls')), 
    path('settings', include('api.setting.urls')),

    path('ai', include('api.ai.urls')),
]


if settings.DEBUG:
    import debug_toolbar
    urlpatterns = [
        path('__debug__/', include(debug_toolbar.urls)),
    ] + urlpatterns


