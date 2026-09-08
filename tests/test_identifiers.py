#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for ИИН / БИН validation. No network needed."""
import unittest
from datetime import date

from kz_data_mcp import identifiers


def make_iin(prefix11: str) -> str:
    """Append the correct check digit to an 11-digit prefix."""
    digit = identifiers.check_digit(prefix11)
    assert digit is not None, "prefix has no valid check digit"
    return prefix11 + str(digit)


class CheckDigitTests(unittest.TestCase):
    def test_accepts_number_with_correct_check_digit(self):
        iin = make_iin("90010130012")
        result = identifiers.validate(iin)
        self.assertTrue(result.valid, result.reason)

    def test_undetected_single_digit_errors_have_exactly_two_causes(self):
        """
        The check digit does **not** catch every single-digit error, and the
        exceptions are structural properties of the scheme rather than bugs
        in this implementation. There are exactly two of them:

        1. **The 11th digit is unprotected.** Its weight is 11, and
           11 ≡ 0 (mod 11), so it contributes nothing to the sum. Any change
           to it is invisible to the first weight sequence. (The second
           sequence has the same blind spot on the 9th digit.)

        2. **The fallback.** When the first sequence yields 10, the number is
           re-scored with a different weight sequence, which can coincidentally
           reproduce the original check digit.

        This test asserts that every corruption slipping through is explained
        by one of those two. A leak from any other cause is a real defect.
        """
        iin = make_iin("90010130012")
        unexplained = []

        for position in range(12):
            for replacement in "0123456789":
                if replacement == iin[position]:
                    continue
                corrupted = iin[:position] + replacement + iin[position + 1:]
                if not identifiers.validate(corrupted).valid:
                    continue

                # Cause 1: the digit carries a weight divisible by 11.
                if position < 11 and identifiers.FIRST_WEIGHTS[position] % 11 == 0:
                    continue

                # Cause 2: the corruption pushed the first sum to 10.
                values = [int(c) for c in corrupted[:11]]
                first = sum(v * w for v, w in
                            zip(values, identifiers.FIRST_WEIGHTS)) % 11
                if first == 10:
                    continue

                unexplained.append((position, corrupted))

        self.assertEqual(unexplained, [],
                         "corruptions passed for neither known reason")

    def test_eleventh_digit_is_structurally_unprotected(self):
        """Pin the blind spot explicitly, so a future change cannot hide it."""
        self.assertEqual(identifiers.FIRST_WEIGHTS[10] % 11, 0)

        iin = make_iin("90010130012")
        accepted = 0
        for replacement in "0123456789":
            if replacement == iin[10]:
                continue
            if identifiers.validate(iin[:10] + replacement + iin[11]).valid:
                accepted += 1
        # Every alternative digit in that position passes: it is not covered.
        self.assertEqual(accepted, 9)

    def test_rejects_wrong_length(self):
        for value in ("", "1", "12345678901", "1234567890123"):
            self.assertFalse(identifiers.validate(value).valid)

    def test_ignores_formatting(self):
        iin = make_iin("90010130012")
        spaced = f"{iin[:6]} {iin[6:]}"
        dashed = f"{iin[:6]}-{iin[6:]}"
        self.assertTrue(identifiers.validate(spaced).valid)
        self.assertTrue(identifiers.validate(dashed).valid)

    def test_second_weight_sequence_is_used(self):
        """
        A prefix whose first-sequence result is 10 must fall through to the
        second sequence rather than being rejected outright.
        """
        found = False
        for tail in range(10000):
            prefix = f"9001013{tail:04d}"
            values = [int(c) for c in prefix]
            first = sum(v * w for v, w in
                        zip(values, identifiers.FIRST_WEIGHTS)) % 11
            if first != 10:
                continue
            found = True
            digit = identifiers.check_digit(prefix)
            if digit is not None:
                self.assertTrue(identifiers.validate(prefix + str(digit)).valid)
            break
        self.assertTrue(found, "no prefix exercising the second sequence found")


class IinDecodingTests(unittest.TestCase):
    def test_decodes_birth_date_and_sex(self):
        # 900101 + 3 -> male, born in the 1900s, 1 January 1990
        result = identifiers.validate(make_iin("90010130012"))
        self.assertEqual(result.kind, "iin")
        self.assertEqual(result.birth_date, date(1990, 1, 1))
        self.assertEqual(result.sex, "male")

    def test_female_and_21st_century_markers(self):
        result = identifiers.validate(make_iin("05031560007"))
        self.assertEqual(result.sex, "female")
        self.assertEqual(result.birth_date, date(2005, 3, 15))

    def test_impossible_calendar_date_is_rejected(self):
        """Checksum can pass while the date part is nonsense — say so."""
        iin = make_iin("99133130012")     # month 13
        result = identifiers.validate(iin)
        self.assertFalse(result.valid)
        self.assertIn("calendar date", result.reason)

    def test_non_iin_marker_is_reported_as_bin(self):
        # 7th digit 9 is not an ИИН century/sex marker
        result = identifiers.validate(make_iin("15044090001"))
        self.assertTrue(result.valid)
        self.assertEqual(result.kind, "bin")
        self.assertIsNone(result.birth_date)

    def test_validity_claim_is_qualified(self):
        """A valid result must not claim the number exists in the registry."""
        result = identifiers.validate(make_iin("90010130012"))
        self.assertIn("not checked", result.reason)


if __name__ == "__main__":
    unittest.main()
