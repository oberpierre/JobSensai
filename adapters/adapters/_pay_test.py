import unittest

from adapters.adapters._pay import pay_period, pay_violation
from adapters.adapters.mapping import MappedDetail, evaluate_expression

_VALID = {"min": 155000, "max": 205000, "currency": "EUR", "period": "year"}

_POSTING = {
    "pay_input_ranges": [
        {
            "min_cents": 15500000,
            "max_cents": 20500000,
            "currency_type": "EUR",
            "title": "Annual Salary:",
        }
    ]
}

_PAY_EXPRESSION = (
    "pay_input_ranges[0].{min: hundredths(min_cents), max: hundredths(max_cents),"
    " currency: currency_type, period: pay_period(title)}"
)

_EXPECTED_PAY = {"min": 155000.0, "max": 205000.0, "currency": "EUR", "period": "year"}


class TestPayPeriod(unittest.TestCase):
    def test_annual_salary_colon_is_year(self):
        self.assertEqual(pay_period("Annual Salary:"), "year")

    def test_hyphenated_per_year_is_year(self):
        self.assertEqual(pay_period("per-year-salary"), "year")

    def test_uppercase_one_year_is_year(self):
        self.assertEqual(pay_period("1 YEAR"), "year")

    def test_per_hour_wage_is_hour(self):
        self.assertEqual(pay_period("per-hour-wage"), "hour")

    def test_daily_rate_is_day(self):
        self.assertEqual(pay_period("Daily rate"), "day")

    def test_per_week_is_week(self):
        self.assertEqual(pay_period("per week"), "week")

    def test_monthly_is_month(self):
        self.assertEqual(pay_period("Monthly"), "month")

    def test_no_period_word_is_none(self):
        self.assertIsNone(pay_period("Commission"))

    def test_several_periods_is_none(self):
        self.assertIsNone(pay_period("Annual Salary (40 hours per week)"))

    def test_day_inside_a_word_is_none(self):
        self.assertIsNone(pay_period("Monday shift"))


class TestPayViolation(unittest.TestCase):
    def test_none_is_valid(self):
        self.assertIsNone(pay_violation(None))

    def test_valid_pay(self):
        self.assertIsNone(pay_violation(_VALID))

    def test_fractional_single_amount_is_valid(self):
        self.assertIsNone(pay_violation({**_VALID, "min": 25.5, "max": 25.5}))

    def test_floor_only_is_valid(self):
        self.assertIsNone(pay_violation({**_VALID, "max": None}))

    def test_cap_only_is_valid(self):
        self.assertIsNone(pay_violation({**_VALID, "min": None}))

    def test_neither_bound(self):
        self.assertEqual(
            pay_violation({**_VALID, "min": None, "max": None}),
            "pay states neither min nor max",
        )

    def test_not_an_object(self):
        self.assertEqual(pay_violation([_VALID]), "pay is not an object")

    def test_extra_key(self):
        self.assertEqual(
            pay_violation({**_VALID, "blurb": "x"}),
            "pay keys are not exactly min, max, currency and period",
        )

    def test_bool_min(self):
        self.assertEqual(
            pay_violation({**_VALID, "min": True}),
            "pay min is not a positive number or null",
        )

    def test_zero_max(self):
        self.assertEqual(
            pay_violation({**_VALID, "max": 0}),
            "pay max is not a positive number or null",
        )

    def test_infinite_max(self):
        self.assertEqual(
            pay_violation({**_VALID, "max": float("inf")}),
            "pay max is not a positive number or null",
        )

    def test_min_above_max(self):
        self.assertEqual(
            pay_violation({**_VALID, "min": 205001}), "pay min exceeds max"
        )

    def test_max_above_column_limit(self):
        self.assertEqual(
            pay_violation({**_VALID, "max": 10_000_000_000}),
            "pay max exceeds 9999999999.99",
        )

    def test_lone_min_above_column_limit(self):
        self.assertEqual(
            pay_violation({**_VALID, "min": 10_000_000_000, "max": None}),
            "pay min exceeds 9999999999.99",
        )

    def test_amount_rounding_to_zero(self):
        self.assertEqual(
            pay_violation({**_VALID, "min": 0.004}),
            "pay min rounds to zero at two decimals",
        )

    def test_smallest_amount_stored_above_zero_is_valid(self):
        self.assertIsNone(pay_violation({**_VALID, "min": 0.005}))

    def test_amount_with_more_than_two_decimals_is_valid(self):
        self.assertIsNone(pay_violation({**_VALID, "min": 4166.667, "max": 4166.667}))

    def test_lowercase_currency(self):
        self.assertEqual(
            pay_violation({**_VALID, "currency": "eur"}),
            "pay currency is not a three-letter ISO 4217 code",
        )

    def test_unknown_period(self):
        self.assertEqual(
            pay_violation({**_VALID, "period": "annual"}),
            "pay period is not one of year, month, week, day, hour",
        )


class TestPayThroughTheEngine(unittest.TestCase):
    def test_hundredths_converts(self):
        self.assertEqual(evaluate_expression("hundredths(n)", {"n": 12345}), 123.45)

    def test_hundredths_of_absent_is_none(self):
        self.assertIsNone(evaluate_expression("hundredths(n)", {}))

    def test_pay_period_reads_text(self):
        self.assertEqual(
            evaluate_expression("pay_period(t)", {"t": "per-hour-wage"}), "hour"
        )

    def test_hundredths_of_a_string_is_none(self):
        self.assertIsNone(evaluate_expression("hundredths(t)", {"t": "x"}))

    def test_hundredths_of_a_bool_is_none(self):
        self.assertIsNone(evaluate_expression("hundredths(t)", {"t": True}))

    def test_pay_period_of_a_number_is_none(self):
        self.assertIsNone(evaluate_expression("pay_period(t)", {"t": 7}))

    def test_pay_expression_against_a_posting(self):
        self.assertEqual(evaluate_expression(_PAY_EXPRESSION, _POSTING), _EXPECTED_PAY)

    def test_pay_expression_against_no_ranges_is_none(self):
        self.assertIsNone(
            evaluate_expression(_PAY_EXPRESSION, {"pay_input_ranges": []})
        )

    def test_pay_expression_with_a_floor_only(self):
        posting = {
            "pay_input_ranges": [
                {
                    "min_cents": 5000000,
                    "currency_type": "EUR",
                    "title": "Annual Salary:",
                }
            ]
        }
        self.assertEqual(
            evaluate_expression(_PAY_EXPRESSION, posting),
            {"min": 50000.0, "max": None, "currency": "EUR", "period": "year"},
        )

    def test_detail_mapping_emits_pay(self):
        mapping = MappedDetail(
            {
                "version": 1,
                "type": "detail",
                "domains": ["example.com"],
                "jmespath": {
                    "title": "t",
                    "company_name": "c",
                    "description": "d",
                    "pay": _PAY_EXPRESSION,
                },
            }
        )
        self.assertEqual(mapping.to_silver(_POSTING)["pay"], _EXPECTED_PAY)


if __name__ == "__main__":
    unittest.main()
