"""Unit checks for frost event thresholds and complete 3-hour day coverage."""
import unittest

import numpy as np

from build_ecmwf_frost import MEMBERS, daily_minima, frost_fields


class FrostProbabilityTests(unittest.TestCase):
    def test_different_thresholds_and_negative_tmin(self):
        a = np.array([[-7.0], [-4.0], [-3.0], [-1.0], [0.0], [1.0], [2.0], [4.0]])
        result = frost_fields(a)
        self.assertAlmostEqual(result["frost0"][0], 62.5)
        self.assertAlmostEqual(result["frost2"][0], 37.5)
        self.assertAlmostEqual(result["frost5"][0], 12.5)
        self.assertAlmostEqual(result["frost10"][0], 0.0)
        self.assertAlmostEqual(result["frost_mean_c"][0], -1.0)

    def test_every_six_hour_period_is_required(self):
        values = {}
        for member in MEMBERS:
            for hour in (3, 6, 9, 12, 15, 18, 21, 24):
                values[(hour, member)] = np.array([1.0 if hour != 18 else -4.0])
        a = daily_minima(values, 0, 1)
        self.assertEqual(a.shape, (8, 1))
        self.assertTrue(np.all(a == -4))
        del values[(18, MEMBERS[0])]
        a = daily_minima(values, 0, 1)
        self.assertTrue(np.isnan(a[0, 0]))
        self.assertTrue(np.isfinite(a[1, 0]))

    def test_second_utc_day_uses_its_own_periods(self):
        values = {}
        for member in MEMBERS:
            for hour in (3, 6, 9, 12, 15, 18, 21, 24):
                values[(hour, member)] = np.array([-8.0])
            for hour in (27, 30, 33, 36, 39, 42, 45, 48):
                values[(hour, member)] = np.array([2.0])
        self.assertEqual(float(daily_minima(values, 0, 1)[0, 0]), -8.0)
        self.assertEqual(float(daily_minima(values, 1, 1)[0, 0]), 2.0)

    def test_missing_majority_rejected(self):
        a = np.array([[np.nan], [np.nan], [np.nan], [np.nan],
                      [-2.0], [-3.0], [-4.0], [-5.0]])
        with self.assertRaisesRegex(RuntimeError, "Fewer than five"):
            frost_fields(a)

    def test_no_imaginary_temperatures(self):
        a = np.full((8, 2), 2.5)
        a[:6, 0] = -2.5
        p = frost_fields(a)
        self.assertEqual(p["frost2"][0], 75.0)
        self.assertEqual(p["frost2"][1], 0.0)


if __name__ == "__main__":
    unittest.main()
