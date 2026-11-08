"""User registration and administration."""
import re

from common.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from common.validation import normalize_email, require_text
from users.models import Role, User

HANDLE_PATTERN = re.compile(r"^[a-z0-9_.]{2,30}$")


def normalize_handle(handle):
    """'@Alice ' -> 'alice'. Handles are case-insensitive."""
    return str(handle or "").strip().lstrip("@").lower()


class UserService:
    def __init__(self, repository, ids, clock):
        self._users = repository
        self._ids = ids
        self._clock = clock

    def register(self, email, name, role=Role.MEMBER, handle=None):
        email = normalize_email(email)
        name = require_text(name, "name", max_length=80)
        handle = normalize_handle(handle or email.split("@")[0])
        if not HANDLE_PATTERN.match(handle):
            raise ValidationError(f"invalid handle: {handle}")
        if self._users.list(lambda user: user.email == email):
            raise ConflictError(f"email already registered: {email}")
        if self._users.list(lambda user: user.handle == handle):
            raise ConflictError(f"handle already taken: {handle}")
        user = User(id=self._ids.next(), email=email, name=name, handle=handle,
                    created_at=self._clock.now(), role=Role(role))
        return self._users.add(user)

    def get(self, user_id):
        return self._users.get(user_id)

    def get_by_email(self, email):
        email = normalize_email(email)
        matches = self._users.list(lambda user: user.email == email)
        if not matches:
            raise NotFoundError(f"no user with email {email}")
        return matches[0]

    def find_by_handle(self, handle):
        """The user with this handle, or None."""
        wanted = normalize_handle(handle)
        matches = self._users.list(lambda user: user.handle == wanted)
        return matches[0] if matches else None

    def require_active(self, user_id):
        """Return the user, or raise if the account was deactivated."""
        user = self._users.get(user_id)
        if not user.active:
            raise PermissionDeniedError(f"user {user_id} is deactivated")
        return user

    def _require_admin(self, actor_id):
        actor = self.require_active(actor_id)
        if actor.role != Role.ADMIN:
            raise PermissionDeniedError("only admins can manage users")
        return actor

    def change_role(self, user_id, role, actor_id):
        self._require_admin(actor_id)
        user = self._users.get(user_id)
        user.role = Role(role)
        return self._users.update(user)

    def deactivate(self, user_id, actor_id):
        self._require_admin(actor_id)
        if user_id == actor_id:
            raise PermissionDeniedError("admins cannot deactivate themselves")
        user = self._users.get(user_id)
        user.active = False
        return self._users.update(user)
