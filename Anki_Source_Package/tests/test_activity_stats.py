# -*- coding: utf-8 -*-
import unittest
from services.activity_stats import get_daily_activity_stats, calculate_study_rank


class TestActivityStats(unittest.TestCase):
    def setUp(self):
        self.mock_data = {
            "decks": [
                {
                    "name": "Festivals of India",
                    "cards": [
                        {"reviewed_at": "2026-08-22 10:00:00", "last_quality": 4},
                        {"reviewed_at": "2026-08-22 10:05:00", "last_quality": 4},
                        {"reviewed_at": "2026-08-21 12:00:00", "last_quality": 3},  # different day
                    ],
                    "children": []
                },
                {
                    "name": "Math",
                    "cards": [],
                    "children": [
                        {
                            "name": "Number System",
                            "cards": [],
                            "children": [
                                {
                                    "name": "Number System Type- 06",
                                    "cards": [
                                        {"reviewed_at": "2026-08-22 11:00:00", "last_quality": 4},
                                        {"reviewed_at": "2026-08-22 11:02:00", "last_quality": 3},
                                        {"reviewed_at": "2026-08-22 11:05:00", "last_quality": 5},
                                    ]
                                },
                                {
                                    "name": "Number System Type-1 (Divisibility)",
                                    "cards": [
                                        {"reviewed_at": "2026-08-22 11:10:00", "last_quality": 4}
                                    ]
                                }
                            ]
                        },
                        {
                            "name": "Probability",
                            "cards": [
                                {
                                    "boxes": [
                                        {"reviewed_at": "2026-08-22 11:20:00", "last_quality": 4}
                                    ]
                                }
                            ]
                        }
                    ]
                }
            ]
        }

    def test_daily_activity_aggregation(self):
        stats = get_daily_activity_stats("2026-08-22", self.mock_data)
        
        # 2 from Festivals + 3 from Type-06 + 1 from Type-1 + 1 from Probability = 7
        self.assertEqual(stats["total"], 7)
        self.assertEqual(stats["good"], 5)   # 2 + 1 + 1 + 1
        self.assertEqual(stats["hard"], 1)   # 1 in Type-06
        self.assertEqual(stats["easy"], 1)   # 1 in Type-06
        self.assertEqual(stats["again"], 0)
        self.assertEqual(stats["perfect"], 0)
        
        # Tree hierarchy check
        self.assertEqual(len(stats["tree"]), 2)
        festivals_node = next(n for n in stats["tree"] if n["name"] == "Festivals of India")
        math_node = next(n for n in stats["tree"] if n["name"] == "Math")
        
        self.assertEqual(festivals_node["total_reviews"], 2)
        self.assertEqual(len(festivals_node["children"]), 0)
        
        # Math root node should aggregate all its children (3 + 1 + 1 = 5)
        self.assertEqual(math_node["total_reviews"], 5)
        self.assertEqual(len(math_node["children"]), 2)  # Number System & Probability
        
        ns_node = next(n for n in math_node["children"] if n["name"] == "Number System")
        self.assertEqual(ns_node["total_reviews"], 4)  # 3 + 1
        self.assertEqual(len(ns_node["children"]), 2)  # Type-06 and Type-1
        
        prob_node = next(n for n in math_node["children"] if n["name"] == "Probability")
        self.assertEqual(prob_node["total_reviews"], 1)

    def test_format_activity_duration(self):
        from services.activity_stats import format_activity_duration
        self.assertEqual(format_activity_duration(0), "0s")
        self.assertEqual(format_activity_duration(45), "45s")
        self.assertEqual(format_activity_duration(120), "2m")
        self.assertEqual(format_activity_duration(195), "3m 15s")
        self.assertEqual(format_activity_duration(3600), "1h")
        self.assertEqual(format_activity_duration(5222), "1h 27m")

    def test_deck_focus_time_with_explicit_seconds(self):
        from unittest.mock import patch
        # 1000s on Festivals, 2000s on Math / Number System / Type-06
        mock_deck_secs = {
            "Festivals of India": 1000,
            "Number System Type- 06": 2000,
        }
        with patch("services.activity_stats.get_daily_deck_seconds", return_value=mock_deck_secs), \
             patch("services.activity_stats.get_daily_focus_seconds", return_value=3000):
            stats = get_daily_activity_stats("2026-08-22", self.mock_data)

            festivals_node = next(n for n in stats["tree"] if n["name"] == "Festivals of India")
            math_node = next(n for n in stats["tree"] if n["name"] == "Math")

            self.assertEqual(festivals_node["total_seconds"], 1000)
            self.assertEqual(festivals_node["time_str"], "16m")

            # Math node aggregates Type-06 (2000s)
            self.assertEqual(math_node["total_seconds"], 2000)
            self.assertEqual(math_node["time_str"], "33m")

    def test_deck_focus_time_proportional_fallback(self):
        from unittest.mock import patch
        # No explicit deck seconds recorded, but 7000s focus time for 7 reviews (1000s per review)
        with patch("services.activity_stats.get_daily_deck_seconds", return_value={}), \
             patch("services.activity_stats.get_daily_focus_seconds", return_value=7000):
            stats = get_daily_activity_stats("2026-08-22", self.mock_data)

            festivals_node = next(n for n in stats["tree"] if n["name"] == "Festivals of India")
            math_node = next(n for n in stats["tree"] if n["name"] == "Math")

            # Festivals has 2 reviews out of 7 -> 2000s
            self.assertEqual(festivals_node["total_seconds"], 2000)
            self.assertEqual(festivals_node["time_str"], "33m")

            # Math has 5 reviews out of 7 -> 5000s = 1h 23m
            self.assertEqual(math_node["total_seconds"], 5000)
            self.assertEqual(math_node["time_str"], "1h 23m")


if __name__ == "__main__":
    unittest.main()
