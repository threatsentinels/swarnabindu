
from datetime import time

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from .nepali_date import (
    ad_to_bs,
    format_bs_date,
    calculate_exact_age,
)


# ============================================================
# HOSPITAL SETTINGS
# ============================================================

class HospitalSetting(models.Model):
    """
    Stores the configuration for the hospital using the system.

    The application is designed to be deployable to multiple
    hospitals. Therefore, the defaults are intentionally neutral
    and must not imply that the hospital is a Government of Nepal
    institution.
    """

    hospital_name = models.CharField(
        max_length=255,
        default="Hospital Name",
    )

    nepali_hospital_name = models.CharField(
        max_length=255,
        default="अस्पतालको नाम",
    )

    address = models.CharField(
        max_length=255,
        blank=True,
    )

    district = models.CharField(
        max_length=100,
        blank=True,
    )

    municipality = models.CharField(
        max_length=100,
        blank=True,
    )

    ward = models.CharField(
        max_length=20,
        blank=True,
    )

    province = models.CharField(
        max_length=100,
        blank=True,
    )

    phone = models.CharField(
        max_length=50,
        blank=True,
    )

    email = models.EmailField(
        blank=True,
    )

    report_header = models.TextField(
        blank=True,
    )

    report_footer = models.TextField(
        blank=True,
    )

    logo = models.ImageField(
        upload_to="hospital/",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "Hospital Setting"
        verbose_name_plural = "Hospital Settings"

    @classmethod
    def get_settings(cls):
        """
        Return the singleton hospital configuration.

        The application currently uses ID=1 as its single
        hospital configuration record.
        """
        obj, created = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return self.hospital_name


# ============================================================
# PATIENT
# ============================================================

class Patient(models.Model):

    SEX_CHOICES = [
        ("M", "Male (पुरुष)"),
        ("F", "Female (महिला)"),
        ("O", "Other (अन्य)"),
    ]

    patient_id = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        db_index=True,
    )

    child_name = models.CharField(
        max_length=150,
        verbose_name="Child Full Name",
    )

    nepali_name = models.CharField(
        max_length=150,
        blank=True,
        verbose_name="Child Name (Nepali)",
    )

    sex = models.CharField(
        max_length=1,
        choices=SEX_CHOICES,
    )

    date_of_birth = models.DateField(
        verbose_name="Date of Birth (AD)",
    )

    guardian_name = models.CharField(
        max_length=150,
        verbose_name="Parent / Guardian Name",
    )

    # IMPORTANT:
    # This field intentionally is NOT unique.
    # Multiple children may share the same guardian's phone number.
    phone_number = models.CharField(
        max_length=20,
        db_index=True,
        verbose_name="Primary Phone Number",
    )

    secondary_phone = models.CharField(
        max_length=20,
        blank=True,
        verbose_name="Secondary Phone",
    )

    province = models.CharField(
        max_length=100,
        default="Bagmati Province",
    )

    district = models.CharField(
        max_length=100,
        default="Kavrepalanchok",
    )

    municipality = models.CharField(
        max_length=100,
        default="Panauti Municipality",
    )

    ward = models.CharField(
        max_length=20,
        default="04",
    )

    locality = models.CharField(
        max_length=150,
        verbose_name="Tole / Village / Address",
    )

    identification_info = models.TextField(
        blank=True,
        help_text="Citizenship/Birth Certificate number of parent",
    )

    notes = models.TextField(
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["-created_at"]

        indexes = [
            models.Index(
                fields=["child_name"],
                name="patient_child_name_idx",
            ),
            models.Index(
                fields=["guardian_name"],
                name="patient_guardian_name_idx",
            ),
            models.Index(
                fields=["date_of_birth"],
                name="patient_dob_idx",
            ),
            models.Index(
                fields=["district", "municipality"],
                name="patient_location_idx",
            ),
        ]

    def save(self, *args, **kwargs):
        """
        Generate a patient ID from the database primary key.

        Previous implementation queried the last Patient and added
        one to its ID. That is vulnerable to race conditions when
        two receptionists register patients simultaneously.

        PostgreSQL generates the primary key safely. We then derive
        the human-readable patient ID from that primary key.
        """

        if not self.patient_id:
            # First save obtains the PostgreSQL/Django primary key.
            super().save(*args, **kwargs)

            self.patient_id = f"SW-{self.pk:06d}"

            # Only update the generated identifier.
            super().save(update_fields=["patient_id"])

            return

        super().save(*args, **kwargs)

    def clean(self):
        """
        Model-level validation for patient records.
        """

        errors = {}

        if self.date_of_birth:
            today = timezone.localdate()

            if self.date_of_birth > today:
                errors["date_of_birth"] = (
                    "Date of birth cannot be in the future."
                )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.patient_id} - {self.child_name}"

    @property
    def dob_bs(self):
        return format_bs_date(self.date_of_birth)

    @property
    def current_age_info(self):
        return calculate_exact_age(
            self.date_of_birth,
            timezone.localdate(),
        )


# ============================================================
# VACCINATION SESSION
# ============================================================

class VaccinationSession(models.Model):

    STATUS_CHOICES = [
        ("Scheduled", "Scheduled"),
        ("Open", "Open"),
        ("Completed", "Completed"),
        ("Postponed", "Postponed"),
        ("Cancelled", "Cancelled"),
    ]

    program_name = models.CharField(
        max_length=200,
        help_text="e.g. Swarnabindu Session 19 Ashoj 2083",
    )

    session_date = models.DateField(
        help_text="Official session date",
        db_index=True,
    )

    session_time = models.TimeField(
        default=time(9, 0),
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="Scheduled",
        db_index=True,
    )

    notes = models.TextField(
        blank=True,
    )

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_sessions",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["session_date", "session_time"]

        indexes = [
            models.Index(
                fields=["session_date", "status"],
                name="session_date_status_idx",
            ),
        ]

    def clean(self):
        errors = {}

        if self.session_date:
            # We intentionally do not prohibit past dates because
            # historical sessions must remain editable/auditable
            # according to the application's permission rules.

            pass

        if self.session_time is None:
            errors["session_time"] = "Session time is required."

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.program_name} "
            f"({format_bs_date(self.session_date)})"
        )

    @property
    def session_date_bs(self):
        return format_bs_date(self.session_date)


# ============================================================
# SESSION DATE AUDIT
# ============================================================

class SessionDateAudit(models.Model):

    session = models.ForeignKey(
        VaccinationSession,
        on_delete=models.CASCADE,
        related_name="date_audits",
    )

    old_date = models.DateField()

    new_date = models.DateField()

    reason = models.TextField()

    changed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    timestamp = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    class Meta:
        ordering = ["-timestamp"]

        indexes = [
            models.Index(
                fields=["session", "timestamp"],
                name="session_audit_time_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.session.program_name}: "
            f"{format_bs_date(self.old_date)} → "
            f"{format_bs_date(self.new_date)}"
        )


# ============================================================
# VACCINATION RECORD
# ============================================================

class VaccinationRecord(models.Model):

    STATUS_CHOICES = [
        ("Completed", "Completed"),
        ("Missed", "Missed"),
        ("Deferred", "Deferred"),
        ("Cancelled", "Cancelled"),
    ]

    patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        related_name="vaccinations",
    )

    vaccination_session = models.ForeignKey(
        VaccinationSession,
        on_delete=models.CASCADE,
        related_name="records",
    )

    vaccination_date = models.DateField(
        default=timezone.localdate,
        db_index=True,
    )

    # --------------------------------------------------------
    # Exact age permanently stored at time of vaccination
    # --------------------------------------------------------

    age_at_vaccination_years = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
    )

    age_at_vaccination_months = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
    )

    age_at_vaccination_days = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
    )

    age_at_vaccination_str = models.CharField(
        max_length=100,
        blank=True,
    )

    age_group = models.CharField(
        max_length=50,
        default="0–6 months",
    )

    # --------------------------------------------------------
    # Clinical measurements
    # --------------------------------------------------------

    height_cm = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        validators=[MinValueValidator(0.1)],
        verbose_name="Height (cm)",
    )

    weight_kg = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0.01)],
        verbose_name="Weight (kg)",
    )

    bp_systolic = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        verbose_name="Systolic BP (mmHg)",
    )

    bp_diastolic = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        verbose_name="Diastolic BP (mmHg)",
    )

    temperature_c = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        validators=[MinValueValidator(0.1)],
        verbose_name="Temperature (°C)",
    )

    # --------------------------------------------------------
    # Record status
    # --------------------------------------------------------

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="Completed",
        db_index=True,
    )

    next_vaccination_session = models.ForeignKey(
        VaccinationSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="next_appointments",
    )

    operator = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vaccination_records_operated",
    )

    notes = models.TextField(
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["-vaccination_date", "-created_at"]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "patient",
                    "vaccination_session",
                ],
                name="unique_patient_vaccination_session",
            ),
        ]

        indexes = [
            models.Index(
                fields=["patient", "vaccination_date"],
                name="vacc_patient_date_idx",
            ),
            models.Index(
                fields=["vaccination_session", "status"],
                name="vacc_session_status_idx",
            ),
            models.Index(
                fields=["vaccination_date", "status"],
                name="vacc_date_status_idx",
            ),
        ]

    def clean(self):
        errors = {}

        if self.patient and self.vaccination_date:

            if self.vaccination_date < self.patient.date_of_birth:
                errors["vaccination_date"] = (
                    "Vaccination date cannot be earlier "
                    "than the patient's date of birth."
                )

        if self.vaccination_session and self.vaccination_date:

            # We do not force vaccination_date to equal the
            # session date because the system supports historical
            # and exceptional records.

            pass

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        """
        Calculate and permanently store the exact age at the
        time of vaccination.

        This ensures historical vaccination records do not change
        when the patient's current age changes.
        """

        if self.patient and self.vaccination_date:

            age_info = calculate_exact_age(
                self.patient.date_of_birth,
                self.vaccination_date,
            )

            self.age_at_vaccination_years = age_info["years"]
            self.age_at_vaccination_months = age_info["months"]
            self.age_at_vaccination_days = age_info["days"]
            self.age_at_vaccination_str = age_info["formatted"]
            self.age_group = age_info["age_group"]

        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.patient.patient_id} - "
            f"{self.vaccination_session.program_name}"
        )

    @property
    def vaccination_date_bs(self):
        return format_bs_date(self.vaccination_date)


# ============================================================
# AUDIT LOG
# ============================================================

class AuditLog(models.Model):

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )

    timestamp = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    action = models.CharField(
        max_length=100,
        db_index=True,
    )

    object_type = models.CharField(
        max_length=100,
        db_index=True,
    )

    object_id = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
    )

    description = models.TextField()

    class Meta:
        ordering = ["-timestamp"]

        indexes = [
            models.Index(
                fields=["user", "timestamp"],
                name="audit_user_time_idx",
            ),
            models.Index(
                fields=["object_type", "object_id"],
                name="audit_object_idx",
            ),
            models.Index(
                fields=["action", "timestamp"],
                name="audit_action_time_idx",
            ),
        ]

    def __str__(self):
        username = (
            self.user.username
            if self.user
            else "System"
        )

        timestamp = timezone.localtime(
            self.timestamp
        ).strftime("%Y-%m-%d %H:%M")

        return (
            f"[{timestamp}] "
            f"{self.action} by {username}"
        )


# ============================================================
# BACKUP RECORD
# ============================================================

class BackupRecord(models.Model):

    STATUS_CHOICES = [
        ("Created", "Created"),
        ("Verified", "Verified"),
        ("Failed", "Failed"),
        ("Restored", "Restored"),
    ]

    filename = models.CharField(
        max_length=255,
    )

    timestamp = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    file_size_bytes = models.BigIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
    )

    status = models.CharField(
        max_length=50,
        choices=STATUS_CHOICES,
        default="Created",
        db_index=True,
    )

    notes = models.TextField(
        blank=True,
    )

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return (
            f"{self.filename} "
            f"({self.status})"
        )

