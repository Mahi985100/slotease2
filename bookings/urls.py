from django.urls import path
from . import views

urlpatterns = [
    path("<slug:slug>/book/", views.book, name="book"),
    path("<slug:slug>/book/<int:pk>/", views.booking_detail, name="booking_detail"),
    path("<slug:slug>/book/<int:pk>/review/", views.review_view, name="booking_review"),
    path("<slug:slug>/waitlist/", views.waiting_list_view, name="waiting_list"),
    path("<slug:slug>/review/", views.review_lookup_view, name="review_lookup"),
]
