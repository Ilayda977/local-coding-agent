import pytest

from common.errors import ConflictError, PermissionDeniedError, ValidationError
from users.models import Role


def test_register_normalizes_email(app):
    user = app.users.register("  Ali@Example.COM ", " Ali ")
    assert user.email == "ali@example.com"
    assert user.name == "Ali"
    assert user.role == Role.MEMBER


@pytest.mark.parametrize("email", ["ali@", "ali.example.com", "ali@example", "a li@example.com"])
def test_register_rejects_invalid_email(app, email):
    with pytest.raises(ValidationError):
        app.users.register(email, "Ali")


def test_register_rejects_duplicate_email_case_insensitive(app, alice):
    with pytest.raises(ConflictError):
        app.users.register("ALICE@taskflow.dev", "Another Alice")


def test_change_role_requires_admin(app, alice, bob):
    with pytest.raises(PermissionDeniedError):
        app.users.change_role(bob.id, Role.ADMIN, actor_id=alice.id)


def test_admin_can_change_role(app, admin, bob):
    app.users.change_role(bob.id, Role.ADMIN, actor_id=admin.id)
    assert app.users.get(bob.id).role == Role.ADMIN


def test_deactivated_user_cannot_create_project(app, admin, bob):
    app.users.deactivate(bob.id, actor_id=admin.id)
    with pytest.raises(PermissionDeniedError):
        app.projects.create(bob.id, "Secret")


def test_handle_defaults_to_email_local_part(app):
    user = app.users.register("Bob.Smith@Example.com", "Bob")
    assert user.handle == "bob.smith"
    assert app.users.find_by_handle("@BOB.smith").id == user.id
    assert app.users.find_by_handle("nobody") is None


def test_duplicate_handle_is_rejected(app, alice):
    with pytest.raises(ConflictError):
        app.users.register("other@example.com", "Other", handle="Alice")
