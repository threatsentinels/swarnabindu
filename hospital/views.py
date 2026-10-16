
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import connection, models, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import (
    HospitalSettingForm,
    PatientForm,
    SessionDateChangeForm,
    VaccinationRecordForm,
    VaccinationSessionForm,
)
from .models import (
    AuditLog,
    BackupRecord,
    HospitalSetting,
    Patient,
    SessionDateAudit,
    VaccinationRecord,
    VaccinationSession,
)
from .nepali_date import (
    calculate_exact_age,
    format_bs_date,
    parse_bs_string,
)
from .permissions import (
    ROLE_ADMIN,
    ROLE_OPERATOR,
    ROLE_READONLY,
    get_user_role,
    require_role,
)
from .reports import generate_session_report
from .services import detect_duplicate_patients, log_audit_event


User = get_user_model()


# =============================================================================
# GLOBAL CONTEXT
# =============================================================================

def global_hospital_context(request):
    """
    Context processor providing hospital settings, today's AD date,
    today's BS date, and the authenticated user's application role.
    """

    today_ad = timezone.localdate()
    setting = HospitalSetting.get_settings()

    user_role = (
        get_user_role(request.user)
        if request.user.is_authenticated
        else None
    )

    return {
        "hospital_setting": setting,
        "today_ad": today_ad,
        "today_bs": format_bs_date(today_ad),
        "user_role": user_role,
    }


# =============================================================================
# DASHBOARD
# =============================================================================

@login_required
def dashboard_view(request):
    today = timezone.localdate()

    today_session = (
        VaccinationSession.objects
        .filter(session_date=today)
        .order_by("session_time", "id")
        .first()
    )

    total_patients = Patient.objects.count()

    today_vaccinations = (
        VaccinationRecord.objects
        .filter(vaccination_date=today)
        .count()
    )

    completed_today = (
        VaccinationRecord.objects
        .filter(
            vaccination_date=today,
            status="Completed",
        )
        .count()
    )

    upcoming_sessions = (
        VaccinationSession.objects
        .filter(session_date__gte=today)
        .exclude(status="Cancelled")
        .order_by("session_date", "session_time")[:5]
    )

    context = {
        "today_session": today_session,
        "total_patients": total_patients,
        "today_vaccinations": today_vaccinations,
        "completed_today": completed_today,
        "upcoming_sessions": upcoming_sessions,
    }

    return render(
        request,
        "dashboard.html",
        context,
    )


# =============================================================================
# PATIENT MANAGEMENT
# =============================================================================

@login_required
def patient_list_view(request):
    """
    Search and paginate patient records.

    Available to all authenticated application users because the role
    matrix permits patient lookup for operational/reporting purposes.
    """

    query = request.GET.get("q", "").strip()

    patients_qs = Patient.objects.all()

    if query:
        parsed_date = parse_bs_string(query)

        date_q = (
            models.Q(date_of_birth=parsed_date)
            if parsed_date
            else models.Q(pk__isnull=True)
        )

        patients_qs = (
            patients_qs
            .filter(
                models.Q(patient_id__icontains=query)
                | models.Q(child_name__icontains=query)
                | models.Q(nepali_name__icontains=query)
                | models.Q(guardian_name__icontains=query)
                | models.Q(phone_number__icontains=query)
                | date_q
            )
            .distinct()
        )

    paginator = Paginator(
        patients_qs.order_by("-created_at"),
        15,
    )

    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "patients/list.html",
        {
            "page_obj": page_obj,
            "query": query,
        },
    )


@login_required
@require_role([ROLE_ADMIN, ROLE_OPERATOR])
def patient_register_view(request):
    """
    Register a new patient.

    Duplicate detection occurs before creation. A duplicate can only
    be overridden by explicitly confirming the warning.
    """

    confirm_duplicate = (
        request.POST.get("confirm_duplicate") == "1"
        if request.method == "POST"
        else False
    )

    duplicates = []

    if request.method == "POST":
        form = PatientForm(request.POST)

        if form.is_valid():
            child_name = form.cleaned_data["child_name"]
            guardian_name = form.cleaned_data["guardian_name"]
            phone_number = form.cleaned_data["phone_number"]
            dob_ad = form.cleaned_data["dob_bs_input"]

            possible_dups = detect_duplicate_patients(
                child_name,
                guardian_name,
                phone_number,
                dob_ad,
            )

            if possible_dups.exists() and not confirm_duplicate:
                duplicates = possible_dups

                messages.warning(
                    request,
                    "Possible duplicate patient record(s) found. "
                    "Please review the existing records before continuing.",
                )

            else:
                with transaction.atomic():
                    patient = form.save()

                    log_audit_event(
                        request.user,
                        "PATIENT_CREATED",
                        "Patient",
                        patient.patient_id,
                        (
                            f"Registered patient "
                            f"{patient.child_name} "
                            f"(ID: {patient.patient_id})"
                        ),
                    )

                messages.success(
                    request,
                    (
                        "Patient registered successfully. "
                        f"Patient ID: {patient.patient_id}"
                    ),
                )

                return redirect(
                    "patient_detail",
                    patient_id=patient.patient_id,
                )

    else:
        form = PatientForm()

    return render(
        request,
        "patients/register.html",
        {
            "form": form,
            "duplicates": duplicates,
        },
    )


@login_required
def patient_detail_view(request, patient_id):
    """
    View the complete patient profile and vaccination history.

    Available to all authenticated application roles.
    """

    patient = get_object_or_404(
        Patient,
        patient_id=patient_id,
    )

    vaccinations = (
        patient.vaccinations
        .select_related(
            "vaccination_session",
            "next_vaccination_session",
            "operator",
        )
        .order_by("-vaccination_date", "-id")
    )

    latest_record = vaccinations.first()

    next_session = (
        latest_record.next_vaccination_session
        if latest_record
        else None
    )

    return render(
        request,
        "patients/detail.html",
        {
            "patient": patient,
            "vaccinations": vaccinations,
            "next_session": next_session,
        },
    )


@login_required
def patient_print_history_view(request, patient_id):
    """
    Printable vaccination history.

    Available to all authenticated application roles.
    """

    patient = get_object_or_404(
        Patient,
        patient_id=patient_id,
    )

    vaccinations = (
        patient.vaccinations
        .select_related(
            "vaccination_session",
            "operator",
        )
        .order_by(
            "vaccination_date",
            "id",
        )
    )

    return render(
        request,
        "patients/print_history.html",
        {
            "patient": patient,
            "vaccinations": vaccinations,
            "printed_at": timezone.localtime(),
        },
    )


# =============================================================================
# VACCINATION WORKFLOW
# =============================================================================

@login_required
@require_role([ROLE_ADMIN, ROLE_OPERATOR])
def vaccination_record_view(request, patient_id):
    """
    Record a vaccination for a patient.

    Only administrators and vaccination operators can create records.
    """

    patient = get_object_or_404(
        Patient,
        patient_id=patient_id,
    )

    session_id = request.GET.get("session_id")
    selected_session = None

    if session_id:
        try:
            selected_session = get_object_or_404(
                VaccinationSession,
                pk=int(session_id),
            )
        except (TypeError, ValueError):
            raise Http404("Invalid vaccination session.")

        if selected_session.status == "Cancelled":
            messages.error(
                request,
                "A cancelled vaccination session cannot be used "
                "for recording vaccination.",
            )
            selected_session = None

    if request.method == "POST":
        form = VaccinationRecordForm(
            request.POST,
            patient=patient,
        )

        if form.is_valid():
            with transaction.atomic():

                record = form.save(commit=False)

                record.patient = patient
                record.operator = request.user

                vaccination_session = (
                    record.vaccination_session
                )

                # The historical vaccination date is derived from
                # the session date, not from arbitrary user input.
                record.vaccination_date = (
                    vaccination_session.session_date
                )

                record.save()

                log_audit_event(
                    request.user,
                    "VACCINATION_RECORDED",
                    "VaccinationRecord",
                    record.id,
                    (
                        f"Recorded vaccination for patient "
                        f"{patient.patient_id} in session "
                        f"{vaccination_session.program_name}"
                    ),
                )

            messages.success(
                request,
                (
                    "Vaccination recorded successfully for "
                    f"Patient {patient.patient_id}."
                ),
            )

            return redirect(
                "patient_detail",
                patient_id=patient.patient_id,
            )

    else:
        initial_data = {}

        if selected_session:
            initial_data["vaccination_session"] = selected_session

        form = VaccinationRecordForm(
            patient=patient,
            initial=initial_data,
        )

    ref_date = (
        selected_session.session_date
        if selected_session
        else timezone.localdate()
    )

    try:
        calculated_age = calculate_exact_age(
            patient.date_of_birth,
            ref_date,
        )
    except ValueError:
        calculated_age = None

    return render(
        request,
        "vaccination/record.html",
        {
            "patient": patient,
            "form": form,
            "calculated_age": calculated_age,
            "selected_session": selected_session,
        },
    )


@login_required
def today_program_view(request):
    """
    Display today's vaccination program and records.

    Available to all authenticated roles.
    """

    today = timezone.localdate()

    sessions = (
        VaccinationSession.objects
        .filter(session_date=today)
        .exclude(status="Cancelled")
        .order_by("session_time", "id")
    )

    active_session = sessions.first()

    today_records = VaccinationRecord.objects.none()

    if active_session:
        today_records = (
            VaccinationRecord.objects
            .filter(vaccination_session=active_session)
            .select_related("patient", "operator")
            .order_by("id")
        )

    return render(
        request,
        "vaccination/today.html",
        {
            "sessions": sessions,
            "active_session": active_session,
            "today_records": today_records,
        },
    )


# =============================================================================
# VACCINATION SESSION MANAGEMENT
# =============================================================================

@login_required
def session_list_view(request):
    """
    Display vaccination sessions.

    Available to all authenticated roles.
    """

    sessions = (
        VaccinationSession.objects
        .select_related("created_by")
        .order_by(
            "-session_date",
            "-session_time",
            "-id",
        )
    )

    return render(
        request,
        "sessions/list.html",
        {
            "sessions": sessions,
        },
    )


@login_required
@require_role([ROLE_ADMIN])
def session_create_view(request):
    """
    Create a vaccination session.

    Only administrators can create sessions.
    """

    if request.method == "POST":
        form = VaccinationSessionForm(request.POST)

        if form.is_valid():
            with transaction.atomic():
                session = form.save(commit=False)
                session.created_by = request.user
                session.save()

                log_audit_event(
                    request.user,
                    "SESSION_CREATED",
                    "VaccinationSession",
                    session.id,
                    (
                        f"Created session "
                        f"{session.program_name} on BS date "
                        f"{session.session_date_bs}"
                    ),
                )

            messages.success(
                request,
                (
                    f"Vaccination session "
                    f"'{session.program_name}' created successfully."
                ),
            )

            return redirect("session_list")

    else:
        form = VaccinationSessionForm()

    return render(
        request,
        "sessions/create_edit.html",
        {
            "form": form,
            "title": "Create New Vaccination Session",
        },
    )


@login_required
@require_role([ROLE_ADMIN])
def session_edit_date_view(request, session_id):
    """
    Change the date of a vaccination session.

    A session with existing vaccination records cannot be silently
    rescheduled because those records use the session date as their
    historical vaccination date.
    """

    session = get_object_or_404(
        VaccinationSession,
        pk=session_id,
    )

    associated_records_count = session.records.count()

    if request.method == "POST":
        form = SessionDateChangeForm(request.POST)

        if form.is_valid():

            new_date = form.cleaned_data["new_date_bs"]
            reason = form.cleaned_data["reason"]
            old_date = session.session_date

            if new_date == old_date:
                form.add_error(
                    "new_date_bs",
                    "The new session date is the same as the current date.",
                )

            elif associated_records_count > 0:
                form.add_error(
                    None,
                    (
                        "This session already has "
                        f"{associated_records_count} vaccination record(s). "
                        "Its date cannot be changed because doing so could "
                        "alter the historical meaning of those records."
                    ),
                )

            else:
                with transaction.atomic():

                    session.session_date = new_date

                    if session.status == "Scheduled":
                        session.status = "Postponed"

                    session.save(
                        update_fields=[
                            "session_date",
                            "status",
                            "updated_at",
                        ]
                    )

                    SessionDateAudit.objects.create(
                        session=session,
                        old_date=old_date,
                        new_date=new_date,
                        reason=reason,
                        changed_by=request.user,
                    )

                    log_audit_event(
                        request.user,
                        "SESSION_DATE_CHANGED",
                        "VaccinationSession",
                        session.id,
                        (
                            f"Session {session.program_name} "
                            f"rescheduled from "
                            f"{format_bs_date(old_date)} to "
                            f"{format_bs_date(new_date)}. "
                            f"Reason: {reason}"
                        ),
                    )

                messages.success(
                    request,
                    (
                        "Session date updated to "
                        f"{format_bs_date(new_date)}. "
                        "The change has been recorded in the audit trail."
                    ),
                )

                return redirect("session_list")

    else:
        form = SessionDateChangeForm()

    return render(
        request,
        "sessions/change_date.html",
        {
            "session": session,
            "form": form,
            "associated_records_count": associated_records_count,
        },
    )


# =============================================================================
# REPORTS & STATISTICS
# =============================================================================

@login_required
@require_role([
    ROLE_ADMIN,
    ROLE_OPERATOR,
    ROLE_READONLY,
])
def daily_session_report_view(request):
    """
    Generate vaccination session reports.

    All three application roles may view reports.
    """

    session_id = request.GET.get("session")

    sex_filter = request.GET.get("sex")
    status_filter = request.GET.get("status")
    age_group_filter = request.GET.get("age_group")

    sessions = (
        VaccinationSession.objects
        .order_by(
            "-session_date",
            "-session_time",
        )
    )

    selected_session = None

    if session_id:
        try:
            selected_session = (
                VaccinationSession.objects
                .filter(pk=int(session_id))
                .first()
            )
        except (TypeError, ValueError):
            selected_session = None

    report_data = generate_session_report(
        session_id=(
            selected_session.id
            if selected_session
            else None
        ),
        sex_filter=sex_filter,
        status_filter=status_filter,
        age_group_filter=age_group_filter,
    )

    context = {
        "sessions": sessions,
        "selected_session": selected_session,
        "report_data": report_data,
        "sex_filter": sex_filter,
        "status_filter": status_filter,
        "age_group_filter": age_group_filter,
    }

    return render(
        request,
        "reports/daily_session.html",
        context,
    )


# =============================================================================
# ADMINISTRATION
# =============================================================================

@login_required
@require_role([ROLE_ADMIN])
def hospital_settings_view(request):
    """
    Edit hospital-wide configuration.

    Administrator only.
    """

    setting = HospitalSetting.get_settings()

    if request.method == "POST":
        form = HospitalSettingForm(
            request.POST,
            request.FILES,
            instance=setting,
        )

        if form.is_valid():
            with transaction.atomic():
                form.save()

                log_audit_event(
                    request.user,
                    "SETTINGS_UPDATED",
                    "HospitalSetting",
                    setting.id,
                    "Updated hospital configuration.",
                )

            messages.success(
                request,
                "Hospital settings saved successfully.",
            )

            return redirect("hospital_settings")

    else:
        form = HospitalSettingForm(
            instance=setting,
        )

    return render(
        request,
        "admin/settings.html",
        {
            "form": form,
        },
    )


@login_required
@require_role([ROLE_ADMIN])
def user_management_view(request):
    """
    Display application users.

    User creation/editing can be added to dedicated administrative
    actions without changing this listing endpoint.
    """

    users = (
        User.objects
        .all()
        .prefetch_related("groups")
        .order_by(
            "-is_active",
            "username",
        )
    )

    return render(
        request,
        "admin/users.html",
        {
            "users": users,
        },
    )


@login_required
@require_role([ROLE_ADMIN])
def audit_log_view(request):
    """
    Display recent application audit information.
    """

    logs = (
        AuditLog.objects
        .select_related("user")
        .order_by("-timestamp")[:200]
    )

    date_audits = (
        SessionDateAudit.objects
        .select_related(
            "session",
            "changed_by",
        )
        .order_by("-timestamp")[:100]
    )

    return render(
        request,
        "admin/audit_log.html",
        {
            "logs": logs,
            "date_audits": date_audits,
        },
    )


@login_required
@require_role([ROLE_ADMIN])
def system_health_view(request):
    """
    Display basic application/database health information.

    This performs an actual database connection check rather than
    displaying a static SQLite/PostgreSQL label.
    """

    latest_backup = (
        BackupRecord.objects
        .order_by("-timestamp")
        .first()
    )

    db_status = "Connected"
    db_error = None

    try:
        connection.ensure_connection()
    except Exception as exc:
        db_status = "Database connection error"
        db_error = str(exc)

    total_patients = Patient.objects.count()
    total_records = VaccinationRecord.objects.count()

    return render(
        request,
        "admin/system_health.html",
        {
            "latest_backup": latest_backup,
            "db_status": db_status,
            "db_error": db_error,
            "total_patients": total_patients,
            "total_records": total_records,
        },
    )

