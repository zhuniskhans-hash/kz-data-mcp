#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Validation of Kazakhstan national identifiers: ИИН (individual) and БИН (legal entity).

Both are 12 digits and share the same check-digit scheme, so a checksum pass
alone does not tell you which kind you are holding.

Check digit
-----------
Weighted sum of the first 11 digits modulo 11:

    d12 = (Σ digit[i] * w1[i]) mod 11,   w1 = 1..11

If that yields 10, the number is recomputed with a second weight sequence:

    d12 = (Σ digit[i] * w2[i]) mod 11,   w2 = 3,4,5,6,7,8,9,10,11,1,2

If the second pass also yields 10, no valid check digit exists and such a
number is never issued.

**What this check digit does not catch.** It is a typo guard, not a proof of
authenticity, and it has two structural blind spots:

  * The **11th digit is unprotected**. Its weight is 11, and 11 ≡ 0 (mod 11),
    so it contributes nothing to the sum — any change to it passes. The second
    sequence has the same blind spot on the 9th digit.
  * A corruption that pushes the first sum to exactly 10 is judged by the
    *second* weight sequence, which can coincidentally reproduce the original
    check digit.

Empirically, about 9% of single-digit corruptions survive. Treat a pass as
"plausibly well-formed", never as "verified".

ИИН structure
-------------
    positions 1-6   YYMMDD, date of birth
    position  7     century and sex:
                        1 male / 2 female   — born 1800-1899
                        3 male / 4 female   — born 1900-1999
                        5 male / 6 female   — born 2000-2099
    positions 8-11  registry sequence
    position  12    check digit

БИН structure is deliberately **not** decoded here. Its digits do encode
registration data, but this module only reports what it can verify, and a
plausible-looking guess about a company's type is worse than no answer.

A passing checksum means the number is well-formed, not that it exists in the
state registry. Only the tax authority can confirm that.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

FIRST_WEIGHTS = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11)
SECOND_WEIGHTS = (3, 4, 5, 6, 7, 8, 9, 10, 11, 1, 2)

#: 7th digit -> (sex, century of birth)
CENTURY_SEX = {
    1: ("male", 1800),
    2: ("female", 1800),
    3: ("male", 1900),
    4: ("female", 1900),
    5: ("male", 2000),
    6: ("female", 2000),
}


@dataclass
class IdInfo:
    value: str
    valid: bool
    reason: str = ""
    kind: str = "unknown"          # "iin" | "bin" | "unknown"
    birth_date: date | None = None
    sex: str | None = None

    def as_dict(self) -> dict:
        return {
            "value": self.value,
            "valid": self.valid,
            "reason": self.reason,
            "kind": self.kind,
            "birth_date": self.birth_date.isoformat() if self.birth_date else None,
            "sex": self.sex,
        }


def check_digit(digits: str) -> int | None:
    """
    Compute the check digit for the first 11 digits.

    Returns None when both weight sequences yield 10, which means no valid
    check digit exists for this prefix.
    """
    values = [int(ch) for ch in digits[:11]]

    result = sum(v * w for v, w in zip(values, FIRST_WEIGHTS)) % 11
    if result != 10:
        return result

    result = sum(v * w for v, w in zip(values, SECOND_WEIGHTS)) % 11
    return None if result == 10 else result


def _parse_birth(digits: str) -> tuple[date | None, str | None]:
    """Decode date of birth and sex from an ИИН. Returns (None, None) if implausible."""
    marker = int(digits[6])
    if marker not in CENTURY_SEX:
        return None, None

    sex, century = CENTURY_SEX[marker]
    year = century + int(digits[0:2])
    month = int(digits[2:4])
    day = int(digits[4:6])
    try:
        return date(year, month, day), sex
    except ValueError:
        # An impossible calendar date (month 13, 31 February). The checksum
        # can still pass, so this is reported rather than silently ignored.
        return None, sex


def validate(value: str) -> IdInfo:
    """Validate an ИИН or БИН and decode what can be decoded."""
    digits = "".join(ch for ch in str(value) if ch.isdigit())

    if len(digits) != 12:
        return IdInfo(value=str(value), valid=False,
                      reason=f"expected 12 digits, got {len(digits)}")

    expected = check_digit(digits)
    if expected is None:
        return IdInfo(value=digits, valid=False,
                      reason="no valid check digit exists for this prefix "
                             "(both weight sequences yield 10)")

    if expected != int(digits[11]):
        return IdInfo(value=digits, valid=False,
                      reason=f"check digit mismatch: expected {expected}, "
                             f"got {digits[11]}")

    # Checksum passes. The 7th digit tells us whether it can be an ИИН.
    marker = int(digits[6])
    if marker in CENTURY_SEX:
        birth, sex = _parse_birth(digits)
        if birth is None:
            return IdInfo(value=digits, valid=False, kind="iin", sex=sex,
                          reason="checksum is valid but positions 1-6 are not "
                                 "a real calendar date")
        return IdInfo(value=digits, valid=True, kind="iin",
                      birth_date=birth, sex=sex,
                      reason="checksum valid; well-formed, existence in the "
                             "state registry not checked")

    return IdInfo(value=digits, valid=True, kind="bin",
                  reason="checksum valid; identified as БИН because the 7th "
                         "digit is not an ИИН century/sex marker. Structure "
                         "not decoded; existence not checked")
