
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import (
    Patient,
    VaccinationSession,
    VaccinationRecord,
    HospitalSetting,
)
from .nepali_date import ad_to_bs, parse_bs_string


# =============================================================================
# COMMON HELPERS
# =============================================================================

def parse_bs_date_safely(value):
    """
    Convert a BS date input into a Gregorian date.

    The BS parser is deliberately isolated here so malformed user input
    cannot propagate a ValueError/TypeError into a Django 500 response.

    Returns:
        datetime.date | None
    """
    if value is None:
        return None

    if hasattr(value, "date") and not isinstance(value, str):
        # Handle datetime-like values defensively.
        try:
            value = value.date()
        except (AttributeError, TypeError, ValueError):
            pass

    if not isinstance(value, str):
        return None

    value = value.strip()

    if not value:
        return None

    try:
        parsed = parse_bs_string(value)
    except (ValueError, TypeError, OverflowError):
        return None

    return parsed


def bs_input_initial(ad_date):
    """
    Return a consistent YYYY-MM-DD BS representation for a Gregorian date.
    """
    if not ad_date:
        return ""

    try:
        year, month, day = ad_to_bs(ad_date)
        return f"{year:04d}-{month:02d}-{day:02d}"
    except (ValueError, TypeError, OverflowError):
        return ""


# =============================================================================
# PATIENT FORM
# =============================================================================

class PatientForm(forms.ModelForm):
    dob_bs_input = forms.CharField(
        label="Date of Birth (BS)",
        help_text="Format: YYYY-MM-DD, e.g. 2081-06-19",
        widget=forms.TextInput(
            attrs={
                "placeholder": "e.g. 2081-06-19",
                "class": "form-control",
                "autocomplete": "off",
            }
        ),
    )

    class Meta:
        model = Patient
        fields = [
            "child_name",
            "nepali_name",
            "sex",
            "guardian_name",
            "phone_number",
            "secondary_phone",
            "province",
            "district",
            "municipality",
            "ward",
            "locality",
            "identification_info",
            "notes",
        ]
        widgets = {
            "child_name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "autocomplete": "name",
                }
            ),
            "nepali_name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Optional Nepali Script",
                }
            ),
            "sex": forms.Select(
                attrs={"class": "form-select"}
            ),
            "guardian_name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "autocomplete": "name",
                }
            ),
            "phone_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "autocomplete": "tel",
                }
            ),
            "secondary_phone": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "autocomplete": "tel",
                }
            ),
            "province": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "district": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "municipality": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "ward": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "locality": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "identification_info": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 2,
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 2,
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if (
            self.instance
            and self.instance.pk
            and self.instance.date_of_birth
        ):
            self.fields["dob_bs_input"].initial = bs_input_initial(
                self.instance.date_of_birth
            )

    def clean_dob_bs_input(self):
        value = self.cleaned_data.get("dob_bs_input")
        parsed_ad = parse_bs_date_safely(value)

        if parsed_ad is None:
            raise ValidationError(
                "Invalid Nepali date. Please use YYYY-MM-DD, "
                "for example 2081-06-19."
            )

        today = timezone.localdate()

        if parsed_ad > today:
            raise ValidationError(
                "Date of birth cannot be in the future."
            )

        return parsed_ad

    def save(self, commit=True):
        instance = super().save(commit=False)

        # clean_dob_bs_input() already returns a Gregorian date.
        instance.date_of_birth = self.cleaned_data["dob_bs_input"]

        if commit:
            instance.save()

        return instance


# =============================================================================
# VACCINATION SESSION FORM
# =============================================================================

class VaccinationSessionForm(forms.ModelForm):
    session_date_bs = forms.CharField(
        label="Session Date (BS)",
        widget=forms.TextInput(
            attrs={
                "placeholder": "e.g. 2083-06-19",
                "class": "form-control",
                "autocomplete": "off",
            }
        ),
    )

    class Meta:
        model = VaccinationSession
        fields = [
            "program_name",
            "session_time",
            "status",
            "notes",
        ]
        widgets = {
            "program_name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "autocomplete": "off",
                }
            ),
            "session_time": forms.TimeInput(
                attrs={
                    "type": "time",
                    "class": "form-control",
                }
            ),
            "status": forms.Select(
                attrs={"class": "form-select"}
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if (
            self.instance
            and self.instance.pk
            and self.instance.session_date
        ):
            self.fields["session_date_bs"].initial = bs_input_initial(
                self.instance.session_date
            )

    def clean_session_date_bs(self):
        value = self.cleaned_data.get("session_date_bs")
        parsed_ad = parse_bs_date_safely(value)

        if parsed_ad is None:
            raise ValidationError(
                "Invalid Nepali date. Please use YYYY-MM-DD, "
                "for example 2083-06-19."
            )

        return parsed_ad

    def clean(self):
        cleaned_data = super().clean()

        session_date = cleaned_data.get("session_date_bs")
        status = cleaned_data.get("status")

        if session_date is None:
            return cleaned_data

        today = timezone.localdate()

        # A new scheduled/open session should not normally be created
        # in the past. Existing historical sessions can still be edited
        # when appropriate.
        if (
            not self.instance.pk
            and session_date < today
            and status in {"Scheduled", "Open"}
        ):
            self.add_error(
                "session_date_bs",
                "A scheduled/open vaccination session cannot be "
                "created with a past date.",
            )

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        # clean_session_date_bs() returns Gregorian date.
        instance.session_date = self.cleaned_data["session_date_bs"]

        if commit:
            instance.save()

        return instance


# =============================================================================
# SESSION DATE CHANGE FORM
# =============================================================================

class SessionDateChangeForm(forms.Form):
    new_date_bs = forms.CharField(
        label="New Session Date (BS)",
        widget=forms.TextInput(
            attrs={
                "placeholder": "e.g. 2083-06-20",
                "class": "form-control",
                "autocomplete": "off",
            }
        ),
    )

    reason = forms.CharField(
        label="Official Reason for Date Change / Postponement",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": (
                    "e.g. Hospital public holiday reschedule."
                ),
            }
        ),
    )

    def clean_new_date_bs(self):
        value = self.cleaned_data.get("new_date_bs")
        parsed_ad = parse_bs_date_safely(value)

        if parsed_ad is None:
            raise ValidationError(
                "Invalid Nepali date. Please use YYYY-MM-DD."
            )

        return parsed_ad

    def clean_reason(self):
        reason = (self.cleaned_data.get("reason") or "").strip()

        if len(reason) < 5:
            raise ValidationError(
                "Please provide a meaningful reason for changing "
                "the session date."
            )

        return reason


# =============================================================================
# VACCINATION RECORD FORM
# =============================================================================

class VaccinationRecordForm(forms.ModelForm):

    class Meta:
        model = VaccinationRecord
        fields = [
            "vaccination_session",
            "height_cm",
            "weight_kg",
            "bp_systolic",
            "bp_diastolic",
            "temperature_c",
            "status",
            "next_vaccination_session",
            "notes",
        ]
        widgets = {
            "vaccination_session": forms.Select(
                attrs={"class": "form-select"}
            ),
            "height_cm": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.1",
                    "min": "0.1",
                }
            ),
            "weight_kg": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                    "min": "0.01",
                }
            ),
            "bp_systolic": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": "1",
                    "placeholder": "e.g. 90",
                }
            ),
            "bp_diastolic": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": "1",
                    "placeholder": "e.g. 60",
                }
            ),
            "temperature_c": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.1",
                    "min": "0.1",
                    "value": "36.6",
                }
            ),
            "status": forms.Select(
                attrs={"class": "form-select"}
            ),
            "next_vaccination_session": forms.Select(
                attrs={"class": "form-select"}
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 2,
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        self.patient = kwargs.pop("patient", None)

        super().__init__(*args, **kwargs)

        # Only sessions that are not cancelled and have not already passed
        # are appropriate as a future/next vaccination appointment.
        today = timezone.localdate()

        self.fields[
            "next_vaccination_session"
        ].queryset = (
            VaccinationSession.objects
            .filter(session_date__gte=today)
            .exclude(status="Cancelled")
            .order_by("session_date", "session_time")
        )

        self.fields["next_vaccination_session"].required = False

        # The current vaccination session should also not be cancelled.
        self.fields[
            "vaccination_session"
        ].queryset = (
            VaccinationSession.objects
            .exclude(status="Cancelled")
            .order_by("-session_date", "-session_time")
        )

    def clean(self):
        cleaned_data = super().clean()

        session = cleaned_data.get("vaccination_session")
        next_session = cleaned_data.get("next_vaccination_session")

        # ---------------------------------------------------------------------
        # Session validation
        # ---------------------------------------------------------------------

        if session:
            if session.status == "Cancelled":
                self.add_error(
                    "vaccination_session",
                    "A vaccination record cannot be recorded "
                    "against a cancelled session.",
                )

        # ---------------------------------------------------------------------
        # Prevent duplicate vaccination records
        # ---------------------------------------------------------------------

        if self.patient and session:
            existing = VaccinationRecord.objects.filter(
                patient=self.patient,
                vaccination_session=session,
            )

            if self.instance and self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)

            if existing.exists():
                raise ValidationError(
                    "DUPLICATE VACCINATION PREVENTED: "
                    f"Patient {self.patient.patient_id} has already "
                    "been registered/vaccinated for this session."
                )

        # ---------------------------------------------------------------------
        # Next-session validation
        # ---------------------------------------------------------------------

        if next_session:
            if next_session.status == "Cancelled":
                self.add_error(
                    "next_vaccination_session",
                    "The next vaccination session cannot be cancelled.",
                )

            if next_session.session_date < timezone.localdate():
                self.add_error(
                    "next_vaccination_session",
                    "The next vaccination session cannot be in the past.",
                )

            if session and next_session.id == session.id:
                self.add_error(
                    "next_vaccination_session",
                    "The next vaccination session must be different "
                    "from the current session.",
                )

        # ---------------------------------------------------------------------
        # Clinical measurements
        # ---------------------------------------------------------------------

        height = cleaned_data.get("height_cm")
        weight = cleaned_data.get("weight_kg")
        systolic = cleaned_data.get("bp_systolic")
        diastolic = cleaned_data.get("bp_diastolic")
        temperature = cleaned_data.get("temperature_c")

        if height is not None:
            if height < 20.0 or height > 200.0:
                self.add_error(
                    "height_cm",
                    "Height value is outside the reasonable "
                    "clinical range of 20–200 cm.",
                )

        if weight is not None:
            if weight < 0.5 or weight > 100.0:
                self.add_error(
                    "weight_kg",
                    "Weight value is outside the reasonable "
                    "clinical range of 0.5–100 kg.",
                )

        if systolic is not None:
            if systolic < 40 or systolic > 250:
                self.add_error(
                    "bp_systolic",
                    "Systolic blood pressure is outside the "
                    "reasonable range of 40–250 mmHg.",
                )

        if diastolic is not None:
            if diastolic < 20 or diastolic > 150:
                self.add_error(
                    "bp_diastolic",
                    "Diastolic blood pressure is outside the "
                    "reasonable range of 20–150 mmHg.",
                )

        if (
            systolic is not None
            and diastolic is not None
            and diastolic >= systolic
        ):
            self.add_error(
                "bp_diastolic",
                "Diastolic blood pressure should be lower "
                "than systolic blood pressure.",
            )

        if temperature is not None:
            if temperature < 30.0 or temperature > 45.0:
                self.add_error(
                    "temperature_c",
                    "Body temperature is outside the "
                    "clinical limits of 30–45 °C.",
                )

        return cleaned_data


# =============================================================================
# HOSPITAL SETTINGS FORM
# =============================================================================

class HospitalSettingForm(forms.ModelForm):

    class Meta:
        model = HospitalSetting
        fields = [
            "hospital_name",
            "nepali_hospital_name",
            "address",
            "district",
            "municipality",
            "ward",
            "province",
            "phone",
            "email",
            "report_header",
            "report_footer",
        ]
        widgets = {
            "hospital_name": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "nepali_hospital_name": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "address": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "district": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "municipality": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "ward": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "province": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "phone": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "autocomplete": "tel",
                }
            ),
            "email": forms.EmailInput(
                attrs={
                    "class": "form-control",
                    "autocomplete": "email",
                }
            ),
            "report_header": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                }
            ),
            "report_footer": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                }
            ),
        }

    def clean_hospital_name(self):
        value = (self.cleaned_data.get("hospital_name") or "").strip()

        if not value:
            raise ValidationError(
                "Hospital name cannot be empty."
            )

        return value

    def clean_nepali_hospital_name(self):
        value = (
            self.cleaned_data.get("nepali_hospital_name") or ""
        ).strip()

        if not value:
            raise ValidationError(
                "Nepali hospital name cannot be empty."
            )

        return value

    def clean_email(self):
        value = (self.cleaned_data.get("email") or "").strip()
        return value

    def clean_report_footer(self):
        value = (
            self.cleaned_data.get("report_footer") or ""
        ).strip()

        return value

