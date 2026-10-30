from django.test import SimpleTestCase

from routing.risk import classify_wind, classify_rain, classify_snow


class WeatherRiskThresholdTests(SimpleTestCase):
    def test_wind_thresholds_and_load_rules(self):
        cases = [
            (24.9, 42000, "Low"),
            (25, 42000, "Moderate"),
            (35, 40000, "High"),
            (35, 40001, "Severe"),
            (45, 30000, "Severe"),
            (45, 30001, "No Travel"),
            (55, 10000, "No Travel"),
        ]
        for wind, load, expected in cases:
            with self.subTest(wind=wind, load=load):
                self.assertEqual(classify_wind(wind, load), expected)

    def test_rain_thresholds(self):
        cases = [
            (0.099, "Low"),
            (0.10, "Moderate"),
            (0.25, "High"),
            (0.50, "Severe"),
            (1.00, "Severe"),
            (1.01, "No Travel"),
        ]
        for rain, expected in cases:
            with self.subTest(rain=rain):
                self.assertEqual(classify_rain(rain), expected)

    def test_snow_thresholds(self):
        cases = [
            (0.49, "Low"),
            (0.50, "Moderate"),
            (1.00, "High"),
            (2.00, "Severe"),
            (3.00, "Severe"),
            (3.01, "No Travel"),
        ]
        for snow, expected in cases:
            with self.subTest(snow=snow):
                self.assertEqual(classify_snow(snow), expected)
