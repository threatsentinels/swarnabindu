
from django.db.models import Q

from .models import AuditLog, Patient


def _clean_text(value):
    """
    Normalize a text value for duplicate comparison.

    Converts None to an empty string and removes surrounding whitespace.
    """
    if value is None:
        return ""

    return str(value).strip()


def _clean_phone(value):
    """
    Normalize a phone number for duplicate comparison.

    At this stage we intentionally do not rewrite the number into a
    different format (for example, adding +977), because that could
    produce unexpected matches. We only remove surrounding whitespace.
    """
    return _clean_text(value)


def log_audit_event(
    user,
    action,
    object_type,
    object_id,
    description,
):
    """
    Centralized application audit logger.

    Audit events are deliberately stored as separate records rather
    than relying only on Django's admin history.

    Parameters:
        user:
            Django User instance responsible for the action.

        action:
            Machine-readable action name, e.g. PATIENT_CREATED.

        object_type:
            Model/entity type affected by the action.

        object_id:
            Identifier of the affected object.

        description:
            Human-readable description of what happened.
    """

    authenticated_user = None

    if (
        user is not None
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
    ):
        authenticated_user = user

    AuditLog.objects.create(
        user=authenticated_user,
        action=_clean_text(action),
        object_type=_clean_text(object_type),
        object_id=_clean_text(object_id),
        description=_clean_text(description),
    )


def detect_duplicate_patients(
    child_name,
    guardian_name,
    phone_number,
    dob_ad,
):
    """
    Find possible duplicate patient records.

    A patient is considered a possible duplicate when at least one of
    these combinations matches:

        1. Child name + date of birth
        2. Guardian name + phone number
        3. Child name + guardian name
        4. Phone number + date of birth

    The function intentionally returns POSSIBLE matches rather than
    declaring a record to be a definite duplicate. The registration
    workflow allows authorized staff to review the matches before
    deciding whether to continue.

    Returns:
        QuerySet[Patient]
    """

    child_name = _clean_text(child_name)
    guardian_name = _clean_text(guardian_name)
    phone_number = _clean_phone(phone_number)

    duplicate_query = Q()

    has_condition = False

    # ------------------------------------------------------------------
    # 1. Child name + DOB
    # ------------------------------------------------------------------
    if child_name and dob_ad:
        duplicate_query |= Q(
            child_name__iexact=child_name,
            date_of_birth=dob_ad,
        )
        has_condition = True

    # ------------------------------------------------------------------
    # 2. Guardian name + phone
    # ------------------------------------------------------------------
    if guardian_name and phone_number:
        duplicate_query |= Q(
            guardian_name__iexact=guardian_name,
            phone_number=phone_number,
        )
        has_condition = True

    # ------------------------------------------------------------------
    # 3. Child name + guardian
    # ------------------------------------------------------------------
    if child_name and guardian_name:
        duplicate_query |= Q(
            child_name__iexact=child_name,
            guardian_name__iexact=guardian_name,
        )
        has_condition = True

    # ------------------------------------------------------------------
    # 4. Phone + DOB
    # ------------------------------------------------------------------
    if phone_number and dob_ad:
        duplicate_query |= Q(
            phone_number=phone_number,
            date_of_birth=dob_ad,
        )
        has_condition = True

    # If there is not enough information to perform a meaningful
    # duplicate check, return an empty queryset without querying
    # every patient in the database.
    if not has_condition:
        return Patient.objects.none()

    return (
        Patient.objects
        .filter(duplicate_query)
        .order_by("child_name", "id")
        .distinct()
    )

