from django import forms
from .models import Review, WaitingList


class CustomerForm(forms.Form):
    customer_name = forms.CharField(max_length=120, label="Your name")
    customer_phone = forms.CharField(max_length=30, label="Phone number")
    customer_email = forms.EmailField(required=False, label="Email (optional — for reminders)")
    notes = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False, label="Notes")


class ReviewForm(forms.Form):
    rating = forms.ChoiceField(
        choices=[(i, f"{i} star{'s' if i > 1 else ''}") for i in range(1, 6)],
        widget=forms.RadioSelect,
        label="Rating",
    )
    comment = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
        label="Write a review",
    )


class OwnerReplyForm(forms.Form):
    owner_reply = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        label="Your reply",
    )


class WaitingListForm(forms.ModelForm):
    class Meta:
        model = WaitingList
        fields = ("service", "staff", "date", "customer_name", "customer_phone", "customer_email", "notes")
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }
