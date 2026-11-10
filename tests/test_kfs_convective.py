"""Regression tests for experimental /proba thunderstorm sensitivity."""
import math
import unittest
import numpy as np
from scripts.build_ecmwf_snow_storm import (
    convective_tier, shear_850_500_ms, organization_and_ascent,
    optional_ensemble_stat, max_available,
)


class ConvectivePotentialTests(unittest.TestCase):
    def test_precursor_from_humidity_without_modelled_rain(self):
        self.assertEqual(convective_tier(550, 0.0, 20, 12), 2)

    def test_cape_alone_does_not_trigger(self):
        self.assertEqual(convective_tier(2200, 0, 80, math.nan), 0)

    def test_moisture_missing_does_not_get_invented(self):
        self.assertEqual(convective_tier(550, 0, 20, math.nan), 0)

    def test_winter_low_top_convection(self):
        self.assertEqual(convective_tier(180, 0.15, 10, 4), 1)

    def test_light_convection_without_gust_field(self):
        self.assertEqual(convective_tier(350, 0.3, math.nan, math.nan), 2)

    def test_modest_trigger_with_moisture(self):
        self.assertEqual(convective_tier(750, 0.8, 20, 12), 3)

    def test_severe_requires_gust(self):
        self.assertEqual(convective_tier(1800, 3, math.nan, 12), 3)

    def test_strong_and_extreme(self):
        self.assertEqual(convective_tier(1700, 2.6, 65, 13), 4)
        self.assertEqual(convective_tier(3200, 5.5, 92, 16), 5)

    def test_unknown_cape_or_rain_stays_unknown(self):
        self.assertIsNone(convective_tier(math.nan, 1, 50, 12))
        self.assertIsNone(convective_tier(1000, math.nan, 50, 12))



class FreshSnowfallAccumulationTests(unittest.TestCase):
    def test_water_equivalent_accumulations_are_not_snow_depth(self):
        import numpy as np
        from scripts.build_ecmwf_snow_storm import daily_rain_mm
        # Direct SF accumulation from 24h to 48h, stored as metres.
        vals={("sf",48,3):np.array([.004,.0004])}
        starts={(48,3):24}
        result=daily_rain_mm(vals,starts,3,24,2,param="sf")
        self.assertTrue(np.allclose(result,[4.0,0.4]))

    def test_missing_snowfall_cannot_be_replaced_by_zero(self):
        from scripts.build_ecmwf_snow_storm import daily_rain_mm
        self.assertIsNone(daily_rain_mm({}, {},3,24,2,param="sf"))

class OrganizationAndLiftTests(unittest.TestCase):
    def test_850_500_bulk_vector_shear_is_not_scalar_difference(self):
        self.assertAlmostEqual(float(shear_850_500_ms(5, 0, 5, 20)), 20.0)
        self.assertAlmostEqual(float(shear_850_500_ms(5, 5, 8, 9)), 5.0)

    def test_organized_environment_requires_storm_signal_and_shear(self):
        org, lift = organization_and_ascent(
            np.array([2, 1, 3, 0]), np.array([18, 22, 9, 28]),
            np.array([-0.08, -0.08, -0.08, -0.08]))
        np.testing.assert_array_equal(org, [1, 0, 0, 0])
        np.testing.assert_array_equal(lift, [1, 1, 1, 0])

    def test_no_synthetic_zero_for_missing_wind_or_omega(self):
        org, lift = organization_and_ascent(
            [2, 2, 2], [math.nan, 18, 18], [math.nan, math.nan, -0.09])
        self.assertTrue(math.isnan(org[0]))
        self.assertTrue(math.isnan(lift[0]))
        self.assertTrue(math.isnan(lift[1]))
        self.assertEqual(float(org[1]), 1)
        self.assertEqual(float(lift[2]), 1)

    def test_missing_members_are_not_counted_as_no_storm(self):
        self.assertIsNone(optional_ensemble_stat(
            np.array([[1], [0], [1], [1], [math.nan], [math.nan],
                      [math.nan], [math.nan]]), probability=True))
        counts = optional_ensemble_stat(
            np.array([[1], [0], [1], [1], [1], [math.nan],
                      [math.nan], [math.nan]]), probability=True)
        self.assertAlmostEqual(float(counts[0]), 80.0)

    def test_max_available_retains_missing(self):
        values = max_available([
            np.array([math.nan, 0, 1]), np.array([math.nan, 1, 0])])
        self.assertTrue(math.isnan(values[0]))
        np.testing.assert_array_equal(values[1:], [1, 1])



class LiquidPrecipitationTests(unittest.TestCase):
    def test_rain_is_total_minus_snowfall_water_equivalent(self):
        import numpy as np
        from scripts.build_ecmwf_snow_storm import liquid_precip_mm
        liquid=liquid_precip_mm(np.array([12.5,2.0,0.0]),np.array([2.5,2.0,0.0]))
        self.assertTrue(np.allclose(liquid,[10.0,0.0,0.0]))

    def test_missing_sf_is_not_treated_as_zero(self):
        from scripts.build_ecmwf_snow_storm import liquid_precip_mm
        self.assertIsNone(liquid_precip_mm([5,6],[float("nan"),2]))

    def test_unphysical_sf_greater_than_total_is_rejected(self):
        from scripts.build_ecmwf_snow_storm import liquid_precip_mm
        self.assertIsNone(liquid_precip_mm([2],[4]))

if __name__ == "__main__":
    unittest.main()
