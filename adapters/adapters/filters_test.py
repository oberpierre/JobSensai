"""Unit tests for the `filter.` convention: both halves in their own home.

The engine is a pure function of a URL, so every case here is invented rather
than drawn from a real platform.
"""

import unittest

from adapters.adapters.filters import parse_filter_params, strip_filter_params


class StripFilterParamsTest(unittest.TestCase):
    """The operator's URL is the one thing only a human can supply, so stripping
    may remove a `filter.` pair and must not re-encode anything else in it."""

    def test_comma_separated_value_is_left_unencoded(self):
        url = "https://boards-api.example.com/jobs?fields=a,b&filter.x=1"
        self.assertEqual(
            strip_filter_params(url),
            "https://boards-api.example.com/jobs?fields=a,b",
        )

    def test_bracket_key_is_untouched_when_no_filter_param_is_present(self):
        url = "https://boards-api.example.com/jobs?arr[]=1&content=true"
        self.assertEqual(strip_filter_params(url), url)

    def test_valueless_flag_is_not_rewritten_with_a_trailing_equals(self):
        url = "https://boards-api.example.com/jobs?flag&content=true"
        self.assertEqual(strip_filter_params(url), url)

    def test_url_with_no_filter_param_is_returned_identically(self):
        url = "https://boards-api.example.com/jobs?content=true&fields=a,b"
        self.assertEqual(strip_filter_params(url), url)


class ParseFilterParamsTest(unittest.TestCase):
    def test_each_key_is_returned_with_the_prefix_removed(self):
        url = "https://api.example.com/jobs?filter.offices[].name=Berlin"
        self.assertEqual(parse_filter_params(url), {"offices[].name": ["Berlin"]})

    def test_two_values_on_one_key_are_preserved_in_order(self):
        url = (
            "https://api.example.com/jobs"
            "?filter.offices[].name=Berlin&filter.offices[].name=Zurich"
        )
        self.assertEqual(
            parse_filter_params(url), {"offices[].name": ["Berlin", "Zurich"]}
        )

    def test_a_blank_value_is_kept_rather_than_dropped(self):
        url = "https://api.example.com/jobs?filter.remote="
        self.assertEqual(parse_filter_params(url), {"remote": [""]})


class StrippingRemovesExactlyWhatParsingReadsTest(unittest.TestCase):
    """The property the module exists to hold: an encoded prefix is a filter to
    both halves, or to neither. Fails against the pre-move code, where stripping
    tested the raw query text and parsing tested the parse_qsl-decoded key."""

    def test_an_encoded_filter_prefix_is_read_and_stripped_alike(self):
        url = "https://api.example.com/jobs?content=true&%66ilter.remote=true"

        self.assertEqual(parse_filter_params(url), {"remote": ["true"]})
        self.assertEqual(
            strip_filter_params(url), "https://api.example.com/jobs?content=true"
        )


if __name__ == "__main__":
    unittest.main()
