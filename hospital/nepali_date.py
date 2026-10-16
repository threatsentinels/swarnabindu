
from datetime import date, datetime

from django.utils import timezone
from nepali_datetime import date as nepali_date


# =============================================================================
# NEPALI MONTH NAMES
# =============================================================================

BS_MONTH_NAMES_EN = [
    "Baishakh",
    "Jestha",
    "Ashar",
    "Shrawan",
    "Bhadra",
    "Ashoj",
    "Kartik",
    "Mangsir",
    "Poush",
    "Magh",
    "Falgun",
    "Chaitra",
]

BS_MONTH_NAMES_NP = [
    "बैशाख",
    "जेठ",
    "असार",
    "साउन",
    "भदौ",
    "असोज",
    "कार्तिक",
    "मंसिर",
    "पुस",
    "माघ",
    "फागुन",
    "चैत",
]


# =============================================================================
# DATE CONVERSION
# =============================================================================

def to_bs(value):
    """
    Convert a Python/Django Gregorian date or datetime
    into a nepali_datetime.date object.

    Database dates should remain Gregorian. BS conversion is
    performed only at the application/display boundary.
    """

    if value is None:
        return None

    if isinstance(value, datetime):
        # If timezone-aware, use the configured local timezone before
        # extracting the date. This matters for Asia/Kathmandu.
        if timezone.is_aware(value):
            value = timezone.localtime(value)

        value = value.date()

    if not isinstance(value, date):
        raise TypeError(
            f"Expected date or datetime, got {type(value).__name__}"
        )

    return nepali_date.from_datetime_date(value)


def ad_to_bs(value):
    """
    Convert Gregorian date to:

        (BS year, BS month, BS day)

    Example:
        date(...) -> (2083, 6, 19)
    """

    bs = to_bs(value)

    if bs is None:
        return None

    return bs.year, bs.month, bs.day


def bs_to_ad(year, month, day):
    """
    Convert a Nepali BS date to Python datetime.date.

    Raises:
        ValueError / TypeError
        when the supplied BS date is invalid.
    """

    try:
        year = int(year)
        month = int(month)
        day = int(day)
    except (TypeError, ValueError):
        raise ValueError("BS year, month and day must be integers.")

    if year < 1:
        raise ValueError("Invalid BS year.")

    if month < 1 or month > 12:
        raise ValueError("BS month must be between 1 and 12.")

    if day < 1 or day > 32:
        raise ValueError("Invalid BS day.")

    try:
        bs = nepali_date(year, month, day)
        return bs.to_datetime_date()
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(
            f"Invalid Nepali date: {year:04d}-{month:02d}-{day:02d}"
        ) from exc


# =============================================================================
# FORMATTING
# =============================================================================

def format_bs_date(value, format_type="full"):
    """
    Format a Gregorian date as a Nepali BS date.

    Supported formats:

        full:
            19 Ashoj 2083 BS

        short:
            2083-06-19 BS

        np:
            १९ असोज २०८३

    Returns:
        "N/A" for None.
    """

    bs = to_bs(value)

    if bs is None:
        return "N/A"

    if not 1 <= bs.month <= 12:
        raise ValueError(
            f"Invalid BS month returned by converter: {bs.month}"
        )

    if format_type == "short":
        return (
            f"{bs.year:04d}-"
            f"{bs.month:02d}-"
            f"{bs.day:02d} BS"
        )

    if format_type == "np":
        return (
            f"{bs.day} "
            f"{BS_MONTH_NAMES_NP[bs.month - 1]} "
            f"{bs.year}"
        )

    return (
        f"{bs.day} "
        f"{BS_MONTH_NAMES_EN[bs.month - 1]} "
        f"{bs.year} BS"
    )


# =============================================================================
# BS STRING PARSING
# =============================================================================

def parse_bs_string(value):
    """
    Safely parse a BS date string in YYYY-MM-DD format.

    Examples:

        "2083-06-19" -> datetime.date(...)

        "nisan"       -> None
        "hello"       -> None
        ""            -> None
        None          -> None

    This function intentionally does NOT raise for ordinary invalid
    user/search input because it is also used by patient searching.
    """

    if value is None:
        return None

    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)

        return value.date()

    if isinstance(value, date):
        return value

    if not isinstance(value, str):
        return None

    value = value.strip()

    if not value:
        return None

    # Current application input format is strictly YYYY-MM-DD.
    parts = value.split("-")

    if len(parts) != 3:
        return None

    # Do not accept things such as:
    # 2083-6-19
    # 2083-06-1
    # 83-06-19
    #
    # Requiring exact four/two/two digit structure keeps the input
    # predictable.
    if (
        len(parts[0]) != 4
        or len(parts[1]) != 2
        or len(parts[2]) != 2
    ):
        return None

    if not all(part.isdigit() for part in parts):
        return None

    try:
        year, month, day = map(int, parts)
    except (TypeError, ValueError):
        return None

    try:
        return bs_to_ad(year, month, day)
    except (ValueError, TypeError, OverflowError):
        return None


# =============================================================================
# AGE CALCULATION
# =============================================================================

def calculate_exact_age(dob, ref_date):
    """
    Calculate exact Gregorian age between two dates.

    Returns a dictionary containing:

        years
        months
        days
        total_months
        formatted
        age_group

    This function is intended for clinical/display purposes.
    """

    if isinstance(dob, datetime):
        if timezone.is_aware(dob):
            dob = timezone.localtime(dob)

        dob = dob.date()

    if isinstance(ref_date, datetime):
        if timezone.is_aware(ref_date):
            ref_date = timezone.localtime(ref_date)

        ref_date = ref_date.date()

    if not isinstance(dob, date):
        raise TypeError(
            "dob must be a date or datetime"
        )

    if not isinstance(ref_date, date):
        raise TypeError(
            "ref_date must be a date or datetime"
        )

    if ref_date < dob:
        raise ValueError(
            "Reference date cannot be earlier than date of birth."
        )

    # -------------------------------------------------------------------------
    # Calculate calendar age without external dependencies.
    # -------------------------------------------------------------------------

    years = ref_date.year - dob.year
    months = ref_date.month - dob.month
    days = ref_date.day - dob.day

    if days < 0:
        months -= 1

        if ref_date.month == 1:
            previous_month = 12
            previous_year = ref_date.year - 1
        else:
            previous_month = ref_date.month - 1
            previous_year = ref_date.year

        if previous_month in (1, 3, 5, 7, 8, 10, 12):
            days_in_previous_month = 31
        elif previous_month in (4, 6, 9, 11):
            days_in_previous_month = 30
        else:
            # February
            if (
                previous_year % 400 == 0
                or (
                    previous_year % 4 == 0
                    and previous_year % 100 != 0
                )
            ):
                days_in_previous_month = 29
            else:
                days_in_previous_month = 28

        days += days_in_previous_month

    if months < 0:
        years -= 1
        months += 12

    total_months = (years * 12) + months

    # -------------------------------------------------------------------------
    # Age groups
    # -------------------------------------------------------------------------

    if total_months < 6:
        age_group = "0–6 months"
    elif total_months < 12:
        age_group = "6–12 months"
    elif years < 2:
        age_group = "1–2 years"
    elif years < 3:
        age_group = "2–3 years"
    elif years < 4:
        age_group = "3–4 years"
    elif years < 5:
        age_group = "4–5 years"
    else:
        age_group = "5+ years"

    # -------------------------------------------------------------------------
    # Human-readable representation
    # -------------------------------------------------------------------------

    if years > 0:
        formatted = (
            f"{years} years "
            f"{months} months "
            f"{days} days"
        )
    else:
        formatted = (
            f"{months} months "
            f"{days} days"
        )

    return {
        "years": years,
        "months": months,
        "days": days,
        "total_months": total_months,
        "formatted": formatted,
        "age_group": age_group,
    }

