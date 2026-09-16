from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from .engine import compute_nssf, compute_paye, reverse_gross_from_net
from .models import PayeTable


class PayeEngineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_reference")
        cls.on = date(2026, 1, 31)

    def paye(self, gross):
        return compute_paye(Decimal(gross), self.on).amount

    def test_below_threshold_is_zero(self):
        self.assertEqual(self.paye(200_000), Decimal("0.00"))
        self.assertEqual(self.paye(235_000), Decimal("0.00"))

    def test_first_band_10pc(self):
        # (300,000 - 235,000) * 10% = 6,500
        self.assertEqual(self.paye(300_000), Decimal("6500.00"))

    def test_second_band_20pc(self):
        # 10,000 + (400,000 - 335,000) * 20% = 23,000
        self.assertEqual(self.paye(400_000), Decimal("23000.00"))

    def test_third_band_30pc(self):
        # 25,000 + (2,850,000 - 410,000) * 30% = 757,000
        self.assertEqual(self.paye(2_850_000), Decimal("757000.00"))

    def test_top_rate_surcharge_40pc(self):
        # 2,902,000 + (12,000,000 - 10,000,000) * 40% = 3,702,000
        self.assertEqual(self.paye(12_000_000), Decimal("3702000.00"))

    def test_band_boundary_at_10m(self):
        self.assertEqual(self.paye(10_000_000), Decimal("2902000.00"))

    def test_versioning_picks_current_not_future_draft(self):
        # The 2026/27 proposed table is inactive, so a mid-2026 date still
        # resolves to the current table.
        result = compute_paye(Decimal("500000"), date(2026, 8, 31))
        self.assertIn("current", result.table_name)


class NssfEngineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_reference")

    def test_split_5_and_10(self):
        res = compute_nssf(Decimal("2000000"), date(2026, 1, 31))
        self.assertEqual(res.employee, Decimal("100000.00"))
        self.assertEqual(res.employer, Decimal("200000.00"))


class ReverseGrossFromNetTests(TestCase):
    """Item 3: HR enters a target Net Pay, the engine works back to Gross."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_reference")
        cls.on = date(2026, 6, 27)

    def round_trips(self, net_target, fixed_deductions=Decimal("0")):
        result = reverse_gross_from_net(Decimal(net_target), self.on, fixed_deductions=Decimal(fixed_deductions))
        paye = compute_paye(result.gross, self.on)
        nssf = compute_nssf(result.gross, self.on)
        recomputed_net = result.gross - paye.amount - nssf.employee - Decimal(fixed_deductions)
        self.assertEqual(recomputed_net, Decimal(net_target))
        self.assertEqual(result.paye, paye.amount)
        self.assertEqual(result.nssf_employee, nssf.employee)
        return result

    def test_round_trips_in_the_zero_rate_band(self):
        self.round_trips("150000")

    def test_round_trips_in_the_10pc_band(self):
        self.round_trips("300000")

    def test_round_trips_in_the_30pc_band(self):
        self.round_trips("500000")

    def test_round_trips_in_the_top_surcharge_band(self):
        self.round_trips("9000000")

    def test_round_trips_with_fixed_deductions(self):
        self.round_trips("400000", fixed_deductions="50000")

    def test_gross_first_and_net_first_agree(self):
        # Forward: pick a gross, compute its net. Reverse: feed that net back
        # in and expect the same gross out (Item 3's "additive, not a
        # replacement" requirement - both paths must describe the same world).
        gross = Decimal("3000000")
        paye = compute_paye(gross, self.on)
        nssf = compute_nssf(gross, self.on)
        net = gross - paye.amount - nssf.employee
        result = reverse_gross_from_net(net, self.on)
        self.assertEqual(result.gross, gross)

    def test_unreachable_net_raises(self):
        with self.assertRaises(ValueError):
            reverse_gross_from_net(Decimal("0"), self.on)
