from django import forms
from django.contrib.auth.forms import UserCreationForm
from accounts.models import User
from .models import Tenant, Service, StaffMember, Availability
from bookings.models import LeaveRequest


class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)
    business_name = forms.CharField(max_length=120)
    phone = forms.CharField(max_length=20, required=False)
    address = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")


class ServiceForm(forms.ModelForm):
    class Meta:
        model = Service
        fields = ("name", "duration_minutes", "price", "is_active")


class StaffForm(forms.ModelForm):
    username = forms.CharField(
        max_length=150, required=False,
        help_text="Login username for this staff member (leave blank to skip creating a login).",
    )
    email = forms.EmailField(required=False)
    password = forms.CharField(
        widget=forms.PasswordInput(render_value=False), required=False,
        help_text="Set on create, or to reset an existing staff login.",
    )

    class Meta:
        model = StaffMember
        fields = ("name", "bio", "services", "is_active")

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        if tenant:
            self.fields["services"].queryset = Service.objects.filter(tenant=tenant)
            self.fields["services"].widget = forms.CheckboxSelectMultiple()
            self.fields["services"].queryset = Service.objects.filter(tenant=tenant)
        # Prefill login fields when editing
        if self.instance and self.instance.pk and self.instance.user_id:
            self.fields["username"].initial = self.instance.user.username
            self.fields["email"].initial = self.instance.user.email

    def clean_username(self):
        uname = (self.cleaned_data.get("username") or "").strip()
        if not uname:
            return ""
        qs = User.objects.filter(username=uname)
        # Allow keeping the same username when editing
        if self.instance and self.instance.pk and self.instance.user_id:
            qs = qs.exclude(pk=self.instance.user_id)
        if qs.exists():
            raise forms.ValidationError("This username is already taken.")
        return uname

    def clean(self):
        cleaned = super().clean()
        uname = cleaned.get("username")
        pwd = cleaned.get("password")
        # Require password when creating a brand-new login
        creating_login = uname and (not self.instance or not self.instance.user_id)
        if creating_login and not pwd:
            self.add_error("password", "Set a password for the new staff login.")
        return cleaned


class AvailabilityForm(forms.ModelForm):
    class Meta:
        model = Availability
        fields = ("day_of_week", "start_time", "end_time", "is_active")
        widgets = {
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "end_time": forms.TimeInput(attrs={"type": "time"}),
        }

    def clean(self):
        cleaned = super().clean()
        s, e = cleaned.get("start_time"), cleaned.get("end_time")
        if s and e and s >= e:
            raise forms.ValidationError("Start time must be before end time.")
        return cleaned


class LeaveRequestForm(forms.ModelForm):
    class Meta:
        model = LeaveRequest
        fields = ("start_date", "end_date", "reason")
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "reason": forms.Textarea(attrs={"rows": 2}),
        }

    def clean(self):
        cleaned = super().clean()
        s, e = cleaned.get("start_date"), cleaned.get("end_date")
        if s and e and s > e:
            raise forms.ValidationError("Start date must be on or before end date.")
        return cleaned
