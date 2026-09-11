"""Unit tests for the mapping engine, against synthetic documents.

The engine is a pure function of document and mapping, so every case here is
invented rather than drawn from a real platform's response, per the engine's own
proof requirement.
"""

import unittest

import jmespath.exceptions

from adapters.adapters import mapping as mapping_module
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

    def test_syntax_error_is_refused_and_wrapped_as_a_mapping_error(self):
        # jmespath.compile itself raises ParseError, and the engine's one
        # construction gate wraps it so a caller need only catch MappingError.
        document = {"version": 1, "domains": ["x"], "jmespath": {"title": "a["}}
        with self.assertRaises(MappingError) as ctx:
            MappedDetail(document)
        self.assertIsInstance(ctx.exception.__cause__, jmespath.exceptions.ParseError)

    def test_non_string_expression_is_refused_and_wrapped_as_a_mapping_error(self):
        # jmespath.compile(["x"]) raises a bare TypeError ("unhashable type: 'list'"),
        # which the same gate wraps.
        document = {"version": 1, "domains": ["x"], "jmespath": {"title": ["x"]}}
        with self.assertRaises(MappingError) as ctx:
            MappedDetail(document)
        self.assertIsInstance(ctx.exception.__cause__, TypeError)

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


class NonListPostingsTest(unittest.TestCase):
    """A postings expression resolving to a string or an object, not a list.

    Uses a plain path (`jobs`, no `[]` projection) so a non-list value passes
    through unchanged rather than a projection turning it into None first.
    """

    def setUp(self):
        document = {
            "version": 1,
            "domains": ["boards-api.example.com"],
            "jmespath": {"postings": "jobs", "job_url": "absolute_url"},
        }
        self.mapping = MappedIndex(document)

    def test_string_postings_yields_no_references_and_logs_the_type(self):
        with self.assertLogs("adapters.adapters.mapping", level="ERROR") as logs:
            refs = self.mapping.references(
                {"jobs": "no jobs"}, "https://boards-api.example.com/jobs"
            )
        self.assertEqual(refs, [])
        self.assertIn("str", "\n".join(logs.output))

    def test_object_postings_yields_no_references(self):
        with self.assertLogs("adapters.adapters.mapping", level="ERROR"):
            refs = self.mapping.references(
                {"jobs": {"a": 1}}, "https://boards-api.example.com/jobs"
            )
        self.assertEqual(refs, [])


class NullJobUrlTest(unittest.TestCase):
    def test_a_posting_with_no_resolvable_job_url_is_skipped_and_logged(self):
        mapping = MappedIndex(_INDEX_DOCUMENT)
        surviving = {"absolute_url": "https://x.example/1"}
        document = {"jobs": [surviving, {"title": "no url here"}]}
        with self.assertLogs("adapters.adapters.mapping", level="ERROR"):
            refs = mapping.references(document, "https://boards-api.example.com/jobs")
        self.assertEqual(
            refs, [PostingRef(url="https://x.example/1", document=surviving)]
        )


class NonListDomainsTest(unittest.TestCase):
    def test_string_domains_is_refused_for_a_detail_document(self):
        document = {
            "version": 1,
            "domains": "example.com",
            "jmespath": {"title": "title"},
        }
        with self.assertRaises(MappingError):
            MappedDetail(document)

    def test_string_domains_is_refused_for_an_index_document(self):
        document = {
            "version": 1,
            "domains": "example.com",
            "jmespath": {"postings": "jobs[]", "job_url": "url"},
        }
        with self.assertRaises(MappingError):
            MappedIndex(document)


class VersionAndCompletenessTest(unittest.TestCase):
    def test_unsupported_version_is_refused(self):
        document = {"version": 7, "domains": ["x"], "jmespath": {"title": "title"}}
        with self.assertRaises(MappingError):
            MappedDetail(document)

    def test_missing_domains_is_refused(self):
        document = {"version": 1, "jmespath": {"title": "title"}}
        with self.assertRaises(MappingError):
            MappedDetail(document)

    def test_index_document_declaring_only_postings_is_refused(self):
        document = {"version": 1, "domains": ["x"], "jmespath": {"postings": "jobs[]"}}
        with self.assertRaises(MappingError):
            MappedIndex(document)

    def test_empty_jmespath_block_is_refused_rather_than_classified_as_detail(self):
        document = {"version": 1, "domains": ["x"], "jmespath": {}}
        with self.assertRaises(MappingError):
            load_mapping(document)


class MixedDocumentTest(unittest.TestCase):
    def test_mixed_index_and_detail_keys_names_both_sets(self):
        document = {
            "version": 1,
            "domains": ["x"],
            "jmespath": {"title": "title", "postings": "jobs[]"},
        }
        with self.assertRaises(MappingError) as ctx:
            load_mapping(document)
        message = str(ctx.exception)
        self.assertIn("mixes", message)
        self.assertIn("postings", message)
        self.assertIn("title", message)


class DisjointVocabulariesGuardTest(unittest.TestCase):
    """`load_mapping` classifies a document by which vocabulary its keys fall in,
    which only works while the two vocabularies share no key."""

    def test_guard_raises_on_an_overlapping_pair(self):
        with self.assertRaises(AssertionError):
            mapping_module._assert_disjoint_vocabularies(
                frozenset({"postings"}), frozenset({"postings"})
            )

    def test_guard_passes_for_the_real_vocabularies(self):
        mapping_module._assert_disjoint_vocabularies(
            mapping_module._SILVER_SCHEMA_KEYS, mapping_module._INDEX_JMESPATH_KEYS
        )


class FetchUrlPreservesEveryOtherCharacterTest(unittest.TestCase):
    """The operator's URL is the one thing only a human can supply, so fetch_url may
    remove a `filter.` pair and must not re-encode anything else in it."""

    def setUp(self):
        self.mapping = MappedIndex(_INDEX_DOCUMENT)

    def test_comma_separated_value_is_left_unencoded(self):
        url = "https://boards-api.example.com/jobs?fields=a,b&filter.x=1"
        self.assertEqual(
            self.mapping.fetch_url(url),
            "https://boards-api.example.com/jobs?fields=a,b",
        )

    def test_bracket_key_is_untouched_when_no_filter_param_is_present(self):
        url = "https://boards-api.example.com/jobs?arr[]=1&content=true"
        self.assertEqual(self.mapping.fetch_url(url), url)

    def test_valueless_flag_is_not_rewritten_with_a_trailing_equals(self):
        url = "https://boards-api.example.com/jobs?flag&content=true"
        self.assertEqual(self.mapping.fetch_url(url), url)


if __name__ == "__main__":
    unittest.main()
