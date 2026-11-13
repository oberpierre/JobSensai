"""Tests for the pay checks of the extraction and detail mapping snapshot bases.

Each case builds its own fixtures and runs one named test method alone, so a result
says which check saw the pay. This module does not import snapshot_test.py or
mapping_snapshot_test.py, because importing a test module would run its cases twice.
"""

import json
import tempfile
import unittest
from pathlib import Path

from adapters.adapters.base import ExtractionAdapter
from adapters.adapters.snapshot import (
    DetailMappingSnapshotTest,
    ExtractionSnapshotTest,
)

_SILVER = {
    "title": "Staff Engineer",
    "company_name": "Acme",
    "description": "We build things.",
}
_DOCUMENT = {"title": "Staff Engineer", "content": "<p>We build things.</p>"}
_SNAPSHOT = {"title": "Staff Engineer", "company_name": "Acme"}
_PAY = {"min": 190000, "max": 230000, "currency": "USD", "period": "year"}

_GREENHOUSE_PAY = (
    "pay_input_ranges[0].{min: hundredths(min_cents), max: hundredths(max_cents), "
    "currency: currency_type, period: pay_period(title)}"
)
_RANGES = [
    {
        "min_cents": 15500000,
        "max_cents": 20500000,
        "currency_type": "EUR",
        "title": "Annual Salary:",
    }
]
_FLOOR_ONLY = [{k: v for k, v in _RANGES[0].items() if k != "max_cents"}]
_EUR_PAY = {"min": 155000, "max": 205000, "currency": "EUR", "period": "year"}


def _extraction_case(root: Path, output: dict, snapshot: dict) -> type:
    """An ExtractionSnapshotTest case whose adapter returns *output* against
    *snapshot*.
    """
    (root / "detail.html").write_text("<html></html>")
    (root / "expected.json").write_text(json.dumps(snapshot))

    class _Adapter(ExtractionAdapter):
        domains = ["example.com"]

        def extract(self, html: str, url: str) -> dict:
            return output

    class _Case(ExtractionSnapshotTest, unittest.TestCase):
        adapter_cls = _Adapter
        fixture_dir = "pay"

        def _fixtures_dir(self_inner) -> Path:
            return root

    return _Case


def _detail_case(
    root: Path, pay_expression: str, document: dict, snapshot: dict
) -> type:
    """A DetailMappingSnapshotTest case for a mapping that adds *pay_expression*."""
    (root / "detail.json").write_text(json.dumps(document))
    (root / "expected.json").write_text(json.dumps(snapshot))
    mapping_path = root / "mapping.json"
    mapping_path.write_text(
        json.dumps(
            {
                "version": 1,
                "type": "detail",
                "domains": ["example.com"],
                "jmespath": {
                    "title": "title",
                    "company_name": "'Acme'",
                    "description": "markdown(content)",
                    "pay": pay_expression,
                },
            }
        )
    )

    class _Case(DetailMappingSnapshotTest, unittest.TestCase):
        basename = "pay"

        def _fixtures_dir(self_inner) -> Path:
            return root

        def _mapping_path(self_inner) -> Path:
            return mapping_path

    return _Case


def _run(case: type, method: str) -> unittest.TestResult:
    suite = unittest.TestSuite([case(method)])
    return suite.run(unittest.TestResult())


def _failure_text(result: unittest.TestResult) -> str:
    return "\n".join(trace for _, trace in result.failures + result.errors)


class TestExtractionPay(unittest.TestCase):
    def _result(self, output: dict, snapshot: dict, method: str):
        with tempfile.TemporaryDirectory() as tmp:
            return _run(_extraction_case(Path(tmp), output, snapshot), method)

    def test_an_integer_snapshot_matches_a_float_output_and_both_conform(self):
        snapshot = {**_SILVER, "pay": {**_PAY, "min": 190000.0, "max": 230000.0}}
        output = {**_SILVER, "pay": _PAY}
        for method in ("test_pay_matches_snapshot", "test_pay_conforms"):
            result = self._result(output, snapshot, method)
            self.assertTrue(result.wasSuccessful(), (method, _failure_text(result)))

    def test_a_pinned_pay_the_output_lacks_fails(self):
        result = self._result(
            _SILVER, {**_SILVER, "pay": _PAY}, "test_pay_matches_snapshot"
        )
        self.assertEqual(len(result.failures), 1, _failure_text(result))

    def test_an_invalid_pay_fails_even_when_the_snapshot_is_silent(self):
        output = {**_SILVER, "pay": {**_PAY, "currency": "usd"}}
        result = self._result(output, _SILVER, "test_pay_conforms")
        self.assertEqual(len(result.failures), 1, _failure_text(result))
        self.assertIn("ISO 4217", _failure_text(result))

    def test_a_cap_only_pay_matches_and_conforms(self):
        pay = {**_SILVER, "pay": {**_PAY, "min": None}}
        for method in ("test_pay_matches_snapshot", "test_pay_conforms"):
            result = self._result(pay, pay, method)
            self.assertTrue(result.wasSuccessful(), (method, _failure_text(result)))


class TestDetailMappingPay(unittest.TestCase):
    def _result(self, expression: str, document: dict, snapshot: dict, method: str):
        with tempfile.TemporaryDirectory() as tmp:
            case = _detail_case(Path(tmp), expression, document, snapshot)
            return _run(case, method)

    def _both_pass(self, document: dict, snapshot: dict) -> None:
        for method in ("test_pay_matches_snapshot", "test_pay_conforms"):
            result = self._result(_GREENHOUSE_PAY, document, snapshot, method)
            self.assertTrue(result.wasSuccessful(), (method, _failure_text(result)))

    def test_cents_converted_to_the_major_unit_match_and_conform(self):
        self._both_pass(
            {**_DOCUMENT, "pay_input_ranges": _RANGES}, {**_SNAPSHOT, "pay": _EUR_PAY}
        )

    def test_a_snapshot_that_copied_the_cents_fails(self):
        snapshot = {**_SNAPSHOT, "pay": {**_EUR_PAY, "min": 15500000}}
        result = self._result(
            _GREENHOUSE_PAY,
            {**_DOCUMENT, "pay_input_ranges": _RANGES},
            snapshot,
            "test_pay_matches_snapshot",
        )
        self.assertEqual(len(result.failures), 1, _failure_text(result))

    def test_a_posting_without_pay_matches_a_null_snapshot(self):
        result = self._result(
            _GREENHOUSE_PAY,
            {**_DOCUMENT, "pay_input_ranges": []},
            {**_SNAPSHOT, "pay": None},
            "test_pay_matches_snapshot",
        )
        self.assertTrue(result.wasSuccessful(), _failure_text(result))

    def test_an_unrecognised_period_fails_conformance(self):
        expression = (
            "pay_input_ranges[0].{min: min_cents, max: max_cents, "
            "currency: currency_type, period: title}"
        )
        result = self._result(
            expression,
            {**_DOCUMENT, "pay_input_ranges": _RANGES},
            _SNAPSHOT,
            "test_pay_conforms",
        )
        self.assertEqual(len(result.failures), 1, _failure_text(result))
        self.assertIn("pay period is not one of", _failure_text(result))

    def test_a_floor_only_pay_matches_and_conforms(self):
        self._both_pass(
            {**_DOCUMENT, "pay_input_ranges": _FLOOR_ONLY},
            {**_SNAPSHOT, "pay": {**_EUR_PAY, "max": None}},
        )

    def test_a_snapshot_that_copied_the_floor_into_the_cap_fails(self):
        result = self._result(
            _GREENHOUSE_PAY,
            {**_DOCUMENT, "pay_input_ranges": _FLOOR_ONLY},
            {**_SNAPSHOT, "pay": {**_EUR_PAY, "max": 155000}},
            "test_pay_matches_snapshot",
        )
        self.assertEqual(len(result.failures), 1, _failure_text(result))


if __name__ == "__main__":
    unittest.main()
