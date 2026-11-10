"""Regression tests for experimental /proba thunderstorm sensitivity."""
import math
import unittest
from scripts.build_ecmwf_snow_storm import convective_tier


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

if __name__ == "__main__":
    unittest.main()
