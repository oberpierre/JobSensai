"""Unit tests for the mapping engine, against synthetic documents.

The engine is a pure function of document and mapping, so every case here is
invented rather than drawn from a real platform's response, per the engine's own
proof requirement.
"""

import unittest

import jmespath.exceptions

from adapters.adapters._markdown import html_to_markdown
from adapters.adapters.base import PostingRef
from adapters.adapters.mapping import (
    MappedDetail,
    MappedIndex,
    MappingError,
    load_mapping,
)

_DETAIL_DOCUMENT = {
    "version": 1,
    "domains": ["boards-api.example.com"],
    "jmespath": {
        "title": "title",
        "company_name": "'Acme'",
        "employment_type": "employment_type",
        "locations": "offices[].name",
        "description": "markdown(unescape(content))",
        "metadata": "{pay: pay_input_ranges}",
    },
}

_INDEX_DOCUMENT = {
    "version": 1,
    "domains": ["boards-api.example.com", "boards-api.example.org"],
    "jmespath": {
        "postings": "jobs[]",
        "job_url": "absolute_url",
    },
}


class MappedDetailTest(unittest.TestCase):
    def setUp(self):
        self.mapping = MappedDetail(_DETAIL_DOCUMENT)

    def test_domains_come_from_the_document(self):
        self.assertEqual(self.mapping.domains, ["boards-api.example.com"])

    def test_plain_path_and_string_literal_constant(self):
        silver = self.mapping.to_silver({"title": "Engineer"})
        self.assertEqual(silver["title"], "Engineer")
        self.assertEqual(silver["company_name"], "Acme")

    def test_projection_over_a_list(self):
        posting = {"offices": [{"name": "Berlin"}, {"name": "Remote"}]}
        silver = self.mapping.to_silver(posting)
        self.assertEqual(silver["locations"], ["Berlin", "Remote"])

    def test_projection_over_an_empty_list_is_an_empty_list(self):
        silver = self.mapping.to_silver({"offices": []})
        self.assertEqual(silver["locations"], [])

    def test_multiselect_hash_into_metadata(self):
        posting = {"pay_input_ranges": {"min": 1, "max": 2}}
        silver = self.mapping.to_silver(posting)
        self.assertEqual(silver["metadata"], {"pay": {"min": 1, "max": 2}})

    def test_both_custom_functions_chained(self):
        posting = {"content": "&lt;p&gt;Hello&lt;/p&gt;"}
        silver = self.mapping.to_silver(posting)
        self.assertEqual(silver["description"], html_to_markdown("<p>Hello</p>"))

    def test_a_key_the_platform_omits_evaluates_to_none(self):
        silver = self.mapping.to_silver({"title": "Engineer"})
        self.assertIsNone(silver["employment_type"])
        # The custom functions pass an absent source through quietly too, rather
        # than treating None as the wrong type.
        self.assertIsNone(silver["description"])

    def test_markdown_over_a_list_raises_at_map_time_not_construction(self):
        # Construction alone can't catch this: the type only exists once a real
        # document is mapped.
        posting = {"content": ["not", "a", "string"]}
        with self.assertRaises(jmespath.exceptions.JMESPathTypeError):
            self.mapping.to_silver(posting)


class MappedIndexTest(unittest.TestCase):
    def setUp(self):
        self.mapping = MappedIndex(_INDEX_DOCUMENT)

    def test_domains_come_from_the_document(self):
        self.assertEqual(
            self.mapping.domains,
            ["boards-api.example.com", "boards-api.example.org"],
        )

    def test_references_pairs_each_posting_with_its_job_url(self):
        document = {
            "jobs": [
                {"absolute_url": "https://x.example/1"},
                {"absolute_url": "https://x.example/2"},
            ]
        }
        refs = self.mapping.references(document, "https://boards-api.example.com/jobs")
        self.assertEqual(
            refs,
            [
                PostingRef(
                    url="https://x.example/1",
                    document={"absolute_url": "https://x.example/1"},
                ),
                PostingRef(
                    url="https://x.example/2",
                    document={"absolute_url": "https://x.example/2"},
                ),
            ],
        )

    def test_references_on_an_empty_response_is_an_empty_list(self):
        refs = self.mapping.references(
            {"jobs": []}, "https://boards-api.example.com/jobs"
        )
        self.assertEqual(refs, [])

    def test_fetch_url_strips_filter_prefixed_params_only(self):
        start_url = (
            "https://boards-api.example.com/jobs"
            "?filter.offices%5B%5D.name=Berlin&content=true"
        )
        fetched = self.mapping.fetch_url(start_url)
        self.assertEqual(fetched, "https://boards-api.example.com/jobs?content=true")


class ConstructionRejectionTest(unittest.TestCase):
    """Each rejection is a distinct construction-time gate, proven separately."""

    def test_syntax_error_is_refused_by_jmespath_compile_itself(self):
        document = {"version": 1, "domains": ["x"], "jmespath": {"title": "a["}}
        with self.assertRaises(jmespath.exceptions.JMESPathError):
            MappedDetail(document)

    def test_unknown_function_name_is_refused_at_construction(self):
        document = {
            "version": 1,
            "domains": ["x"],
            "jmespath": {"title": "no_such_function(title)"},
        }
        # jmespath.compile alone accepts this because the function name only
        # resolves during evaluation, so this proves the engine's own walk catches it.
        jmespath.compile("no_such_function(title)")
        with self.assertRaises(MappingError):
            MappedDetail(document)

    def test_unknown_top_level_key_is_refused(self):
        document = {
            "version": 1,
            "domains": ["x"],
            "jmespath": {"title": "title"},
            "extra": True,
        }
        with self.assertRaises(MappingError):
            MappedDetail(document)

    def test_unknown_jmespath_key_is_refused_for_a_detail_document(self):
        document = {
            "version": 1,
            "domains": ["x"],
            "jmespath": {"not_a_silver_field": "title"},
        }
        with self.assertRaises(MappingError):
            MappedDetail(document)

    def test_unknown_jmespath_key_is_refused_for_an_index_document(self):
        document = {
            "version": 1,
            "domains": ["x"],
            "jmespath": {"title": "title"},
        }
        with self.assertRaises(MappingError):
            MappedIndex(document)


class LoadMappingTest(unittest.TestCase):
    def test_classifies_a_detail_document(self):
        self.assertIsInstance(load_mapping(_DETAIL_DOCUMENT), MappedDetail)

    def test_classifies_an_index_document(self):
        self.assertIsInstance(load_mapping(_INDEX_DOCUMENT), MappedIndex)


if __name__ == "__main__":
    unittest.main()
