import os
import re
import tempfile

import pytest

from smsguard import create_app
from smsguard.security import limiter

VALID_IMEI = "354940123456781"
INVALID_IMEI = "354940123456789"


@pytest.fixture()
def app():
    tmp = tempfile.mkdtemp()
    # The rate limiter is a process-wide singleton; reset it so hits from one
    # test never bleed into the next.
    limiter._hits.clear()
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "DATABASE": os.path.join(tmp, "test.db"),
        }
    )
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


def csrf(html):
    if isinstance(html, bytes):
        html = html.decode()
    return re.search(r'name="_csrf_token" value="([0-9a-f]+)"', html).group(1)


def signup(client, email="alice@example.com", password="password1"):
    r = client.get("/signup")
    return client.post(
        "/signup",
        data={
            "_csrf_token": csrf(r.data),
            "name": "Alice",
            "email": email,
            "password": password,
            "confirm": password,
        },
        follow_redirects=True,
    )


def login(client, email="alice@example.com", password="password1"):
    r = client.get("/login")
    return client.post(
        "/login",
        data={"_csrf_token": csrf(r.data), "email": email, "password": password},
        follow_redirects=True,
    )


def logout(client):
    return client.get("/logout")


def register_device(client, imei=VALID_IMEI, model="Pixel 8"):
    r = client.get("/register")
    return client.post(
        "/register",
        data={"_csrf_token": csrf(r.data), "imei": imei, "model": model},
        follow_redirects=True,
    )
