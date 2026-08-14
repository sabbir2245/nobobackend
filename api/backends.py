# myapp/backends.py
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

User = get_user_model()

class EmailOrPhoneBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        # DRF's serializer passes the input string as 'username' 
        # regardless of whether the user typed an email, phone, or username.
        if username is None:
            return None

        try:
            # 1. Try to find the user by email
            user = User.objects.get(email=username)
        except User.DoesNotExist:
            try:
                # 2. If email fails, try to find the user by phone number
                # Assumes your User model has a field named 'phone_number'
                user = User.objects.get(phone_number=username)
            except User.DoesNotExist:
                # 3. Optional: Fallback to standard username check if you still use it
                try:
                    user = User.objects.get(username=username)
                except User.DoesNotExist:
                    return None

        # Check the password if a user was successfully found
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        
        return None