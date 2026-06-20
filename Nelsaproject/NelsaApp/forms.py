from django import forms
from .models import Login, Booking, Passenger
from .phone_utils import normalize_cameroon_phone
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm, UsernameField
from django.contrib.auth.models import User

_LOGIN_INPUT_CLASS = (
    "login-field block w-full rounded-xl border border-slate-200/90 bg-white px-4 py-3.5 pl-12 "
    "text-slate-800 placeholder-slate-400 shadow-inner shadow-slate-900/5 transition "
    "focus:border-blue-500 focus:outline-none focus:ring-4 focus:ring-blue-500/15"
)


class LoginForm(AuthenticationForm):
    # UsernameField matches Django’s auth validators (same as default AuthenticationForm).
    username = UsernameField(
        label="Username",
        widget=forms.TextInput(
            attrs={
                "class": _LOGIN_INPUT_CLASS,
                "placeholder": "Enter your username",
                "autocomplete": "username",
            }
        ),
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(
            attrs={
                "class": _LOGIN_INPUT_CLASS,
                "placeholder": "Enter your password",
                "autocomplete": "current-password",
            }
        ),
    )


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
        label='Email Address',
        widget=forms.EmailInput(attrs={
            'class': 'w-full px-4 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent',
            'placeholder': 'Enter your email'
        })
    )
    phone_number = forms.CharField(
        required=True,
        max_length=20,
        label='Phone Number',
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent',
            'placeholder': 'e.g. 699123456 (+237 added automatically)',
            'inputmode': 'tel',
            'autocomplete': 'tel',
        })
    )
    
    class Meta:
        model = User
        fields = ('username', 'email', 'phone_number', 'password1', 'password2')
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Style all fields consistently
        self.fields['username'].widget.attrs.update({
            'class': 'w-full px-4 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent',
            'placeholder': 'Choose a username'
        })
        self.fields['password1'].widget.attrs.update({
            'class': 'w-full px-4 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent',
            'placeholder': 'Enter password'
        })
        self.fields['password2'].widget.attrs.update({
            'class': 'w-full px-4 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent',
            'placeholder': 'Confirm password'
        })
    
    def clean_phone_number(self):
        raw = (self.cleaned_data.get('phone_number') or '').strip()
        if not raw:
            raise forms.ValidationError("Phone number is required.")
        normalized = normalize_cameroon_phone(raw)
        if not normalized:
            raise forms.ValidationError(
                "Enter a valid Cameroon number (e.g. 699123456 or +237699123456). +237 is added for you."
            )
        return normalized
    
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email:
            # Check if email already exists
            if User.objects.filter(email=email).exists():
                raise forms.ValidationError("This email address is already registered. Please use a different email.")
        return email
    
    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
            # Create or update Passenger profile
            phone_number = self.cleaned_data['phone_number']
            passenger, created = Passenger.objects.get_or_create(
                email=user.email,
                defaults={
                    'name': user.get_full_name() or user.username,
                    'phone': phone_number
                }
            )
            # Update if passenger already exists
            if not created:
                passenger.phone = phone_number
                passenger.name = user.get_full_name() or user.username
                passenger.save()
        return user

class BookingForm(forms.Form):
    class Meta:
        model = Booking
        fields = '__all__'

    app_name = 'booking'



