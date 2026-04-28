from __future__ import annotations

import unittest

from omx_wake_gate.telemetry import _uma_memory_from_meminfo


class UmaTelemetryTests(unittest.TestCase):
    def test_mem_available_plus_swap_free_estimates_allocatable_memory(self) -> None:
        sample = _uma_memory_from_meminfo(
            {
                "MemTotal": 128_000 * 1024,
                "MemAvailable": 100_000 * 1024,
                "SwapTotal": 64_000 * 1024,
                "SwapFree": 60_000 * 1024,
                "HugePages_Total": 0,
            }
        )

        self.assertEqual(sample["memory_source"], "uma_meminfo")
        self.assertEqual(sample["memory_total_mib"], 128_000)
        self.assertEqual(sample["memory_available_mib"], 100_000)
        self.assertEqual(sample["swap_free_mib"], 60_000)
        self.assertEqual(sample["uma_allocatable_mib"], 160_000)
        self.assertEqual(sample["uma_pressure_mib"], 32_000)

    def test_hugetlb_pages_are_not_swappable(self) -> None:
        sample = _uma_memory_from_meminfo(
            {
                "MemTotal": 128_000 * 1024,
                "MemAvailable": 100_000 * 1024,
                "SwapTotal": 64_000 * 1024,
                "SwapFree": 60_000 * 1024,
                "HugePages_Total": 10,
                "HugePages_Free": 4,
                "Hugepagesize": 2_048,
            }
        )

        self.assertEqual(sample["swap_free_mib"], 0)
        self.assertEqual(sample["uma_allocatable_mib"], 8)
        self.assertEqual(sample["uma_pressure_mib"], 12)

    def test_swapless_gb10_uses_memavailable_without_penalty(self) -> None:
        sample = _uma_memory_from_meminfo(
            {
                "MemTotal": 127_535_908,
                "MemAvailable": 123_690_352,
                "SwapTotal": 0,
                "SwapFree": 0,
                "HugePages_Total": 0,
            }
        )

        self.assertEqual(sample["swap_free_mib"], 0)
        self.assertGreater(sample["memory_available_mib"], 120_000)
        self.assertEqual(sample["uma_allocatable_mib"], sample["memory_available_mib"])



if __name__ == "__main__":
    unittest.main()
