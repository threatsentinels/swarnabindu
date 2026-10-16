
from functools import wraps

from django.core.exceptions import PermissionDenied


# =============================================================================
# ROLE DEFINITIONS
# =============================================================================

ROLE_ADMIN = "Administrator"
ROLE_OPERATOR = "Vaccination Operator"
ROLE_READONLY = "Report / Read-only User"

ALL_ROLES = {
    ROLE_ADMIN,
    ROLE_OPERATOR,
    ROLE_READONLY,
}


# =============================================================================
# ROLE RESOLUTION
# =============================================================================

def get_user_role(user):
    """
    Return the effective application role for a Django user.

    Role precedence:

        1. Superuser / Administrator
        2. Vaccination Operator
        3. Report / Read-only User
        4. None

    Access is deny-by-default.

    A normal authenticated user who has not been explicitly assigned
    to an application role does NOT automatically become an operator.
    """

    if not user or not user.is_authenticated:
        return None

    if not user.is_active:
        return None

    # Django superusers always have administrative privileges.
    if user.is_superuser:
        return ROLE_ADMIN

    group_names = set(
        user.groups.values_list("name", flat=True)
    )

    # Explicit priority prevents ambiguous access when a user belongs
    # to more than one application group.
    if ROLE_ADMIN in group_names:
        return ROLE_ADMIN

    if ROLE_OPERATOR in group_names:
        return ROLE_OPERATOR

    if ROLE_READONLY in group_names:
        return ROLE_READONLY

    # Unknown/unassigned users receive no application role.
    return None


# =============================================================================
# ROLE CHECKING
# =============================================================================

def user_has_role(user, allowed_roles):
    """
    Return True when the user has an allowed effective role.

    Administrators are treated as having access to all application
    functions protected by require_role().
    """

    role = get_user_role(user)

    if role is None:
        return False

    if role == ROLE_ADMIN:
        return True

    return role in set(allowed_roles)


def require_role(allowed_roles):
    """
    Decorator restricting a view to explicitly permitted application roles.

    Example:

        @login_required
        @require_role([ROLE_ADMIN, ROLE_OPERATOR])
        def patient_register_view(request):
            ...

    Administrators automatically receive access.

    Unauthenticated, inactive, unassigned, or unauthorized users
    receive PermissionDenied.
    """

    allowed_roles = set(allowed_roles)

    invalid_roles = allowed_roles - ALL_ROLES

    if invalid_roles:
        raise ValueError(
            f"Unknown application role(s): {sorted(invalid_roles)}"
        )

    def decorator(view_func):

        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):

            user = request.user

            if not user.is_authenticated:
                raise PermissionDenied(
                    "Authentication required."
                )

            if not user.is_active:
                raise PermissionDenied(
                    "This user account is inactive."
                )

            role = get_user_role(user)

            if role is None:
                raise PermissionDenied(
                    "No application role has been assigned to this user."
                )

            if role == ROLE_ADMIN:
                return view_func(request, *args, **kwargs)

            if role in allowed_roles:
                return view_func(request, *args, **kwargs)

            raise PermissionDenied(
                "You do not have permission to access "
                "this healthcare function."
            )

        return _wrapped_view

    return decorator

