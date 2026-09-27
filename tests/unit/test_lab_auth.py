"""AI Testing Lab auth: token scopes keep lab users and ShopBot customers apart; sign-up rules."""

import pytest
from graphql import GraphQLError

from services.gateway.app.schema import LabSignupInput, _validate_signup
from shared.security import create_token, decode_token

SECRET = "test-secret-at-least-32-bytes-long!!"


def test_token_scopes_are_not_interchangeable():
    lab = create_token(7, SECRET, 5, scope="lab")
    shop = create_token(7, SECRET, 5)
    assert decode_token(lab, SECRET, scope="lab") == 7
    assert decode_token(shop, SECRET) == 7
    # a lab user id must never be read as a customer id (would expose that customer's orders)
    assert decode_token(lab, SECRET) is None
    assert decode_token(shop, SECRET, scope="lab") is None
    assert decode_token(lab, "wrong-secret", scope="lab") is None


def test_signup_validation():
    ok = LabSignupInput(email="  Ada@Example.com ", full_name=" Ada ", password="secret123")
    assert _validate_signup(ok) == ("ada@example.com", "Ada", "secret123")
    for email, name, password in [
        ("not-an-email", "Ada", "secret123"),
        ("ada@example.com", "   ", "secret123"),
        ("ada@example.com", "Ada", "short1"),       # < 8 chars
        ("ada@example.com", "Ada", "lettersonly"),  # no number
        ("ada@example.com", "Ada", "12345678"),     # no letter
    ]:
        with pytest.raises(GraphQLError):
            _validate_signup(LabSignupInput(email=email, full_name=name, password=password))
