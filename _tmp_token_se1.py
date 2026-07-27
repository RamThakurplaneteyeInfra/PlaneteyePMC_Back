from django.test import Client
from django.contrib.auth import authenticate, get_user_model

User = get_user_model()
u = User.objects.get(username="pmc_se1")
# Ensure known password
u.set_password("Pmc@SE1")
u.is_active = True
u.save(update_fields=["password", "is_active"])
print("auth", authenticate(username="pmc_se1", password="Pmc@SE1") is not None)

c = Client()
for payload in [
    {"username": "pmc_se1", "password": "Pmc@SE1"},
    {"username": "pmc_se1", "password": "Project@123"},
    {"username": "PMC_SE1", "password": "Pmc@SE1"},
]:
    r = c.post("/api/token/", data=payload, content_type="application/json")
    print("payload", payload, "status", r.status_code, "keys", list(r.json().keys()) if r.content else None)
    if r.status_code != 200:
        print(" body", r.json())
