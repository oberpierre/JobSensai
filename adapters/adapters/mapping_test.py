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
    evaluate_expression,
    load_mapping,
)

_DETAIL_DOCUMENT = {
    "version": 1,
    "type": "detail",
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
    "type": "index",
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
        document = {
            "version": 1,
            "type": "detail",
            "domains": ["x"],
            "jmespath": {"title": "a["},
        }
        with self.assertRaises(MappingError) as ctx:
            MappedDetail(document)
        self.assertIsInstance(ctx.exception.__cause__, jmespath.exceptions.ParseError)

    def test_non_string_expression_is_refused_and_wrapped_as_a_mapping_error(self):
        # jmespath.compile(["x"]) raises a bare TypeError ("unhashable type: 'list'"),
        # which the same gate wraps.
        document = {
            "version": 1,
            "type": "detail",
            "domains": ["x"],
            "jmespath": {"title": ["x"]},
        }
        with self.assertRaises(MappingError) as ctx:
            MappedDetail(document)
        self.assertIsInstance(ctx.exception.__cause__, TypeError)

    def test_unknown_function_name_is_refused_at_construction(self):
        document = {
            "version": 1,
            "type": "detail",
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
            "type": "detail",
            "domains": ["x"],
            "jmespath": {"title": "title"},
            "extra": True,
        }
        with self.assertRaises(MappingError):
            MappedDetail(document)

    def test_detail_document_declaring_postings_is_refused_naming_it(self):
        # postings is an index key, so this proves the vocabularies are checked
        # rather than a detail document with it being reclassified as an index one.
        document = {
            "version": 1,
            "type": "detail",
            "domains": ["x"],
            "jmespath": {"postings": "jobs[]"},
        }
        with self.assertRaises(MappingError) as ctx:
            MappedDetail(document)
        self.assertIn("postings", str(ctx.exception))

    def test_index_document_declaring_title_is_refused_naming_it(self):
        document = {
            "version": 1,
            "type": "index",
            "domains": ["x"],
            "jmespath": {"title": "title"},
        }
        with self.assertRaises(MappingError) as ctx:
            MappedIndex(document)
        self.assertIn("title", str(ctx.exception))


class LoadMappingTest(unittest.TestCase):
    def test_classifies_a_detail_document(self):
        self.assertIsInstance(load_mapping(_DETAIL_DOCUMENT), MappedDetail)

    def test_classifies_an_index_document(self):
        self.assertIsInstance(load_mapping(_INDEX_DOCUMENT), MappedIndex)

    def test_missing_type_is_refused(self):
        document = {
            "version": 1,
            "domains": ["x"],
            "jmespath": {"title": "title"},
        }
        with self.assertRaises(MappingError):
            load_mapping(document)

    def test_unknown_type_is_refused_naming_it(self):
        with self.assertRaises(MappingError) as ctx:
            load_mapping({"type": "listing"})
        self.assertIn("listing", str(ctx.exception))

    def test_mapped_detail_checks_its_own_declared_kind(self):
        # The jmespath block holds only a Silver key, which _compile_jmespath_block
        # would accept on its own, so only the type check can refuse this: a false
        # pass here would mean the guard, not the key vocabulary, is untested.
        document = {
            "version": 1,
            "type": "index",
            "domains": ["x.example.com"],
            "jmespath": {"title": "title"},
        }
        with self.assertRaises(MappingError) as ctx:
            MappedDetail(document)
        message = str(ctx.exception)
        self.assertIn("detail", message)
        self.assertIn("index", message)

    def test_mapped_index_checks_its_own_declared_kind(self):
        # Symmetric case: the jmespath block holds only index keys, which
        # _compile_jmespath_block would accept on its own.
        document = {
            "version": 1,
            "type": "detail",
            "domains": ["x.example.com"],
            "jmespath": {"postings": "jobs[]", "job_url": "url"},
        }
        with self.assertRaises(MappingError) as ctx:
            MappedIndex(document)
        message = str(ctx.exception)
        self.assertIn("index", message)
        self.assertIn("detail", message)


class NonListPostingsTest(unittest.TestCase):
    """A postings expression resolving to a string or an object, not a list.

    Uses a plain path (`jobs`, no `[]` projection) so a non-list value passes
    through unchanged rather than a projection turning it into None first.
    """

    def setUp(self):
        document = {
            "version": 1,
            "type": "index",
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
            "type": "detail",
            "domains": "example.com",
            "jmespath": {"title": "title"},
        }
        with self.assertRaises(MappingError):
            MappedDetail(document)

    def test_string_domains_is_refused_for_an_index_document(self):
        document = {
            "version": 1,
            "type": "index",
            "domains": "example.com",
            "jmespath": {"postings": "jobs[]", "job_url": "url"},
        }
        with self.assertRaises(MappingError):
            MappedIndex(document)


class VersionAndCompletenessTest(unittest.TestCase):
    def test_unsupported_version_is_refused(self):
        document = {
            "version": 7,
            "type": "detail",
            "domains": ["x"],
            "jmespath": {"title": "title"},
        }
        with self.assertRaises(MappingError):
            MappedDetail(document)

    def test_missing_domains_is_refused(self):
        document = {"version": 1, "type": "detail", "jmespath": {"title": "title"}}
        with self.assertRaises(MappingError):
            MappedDetail(document)

    def test_index_document_declaring_only_postings_is_refused(self):
        document = {
            "version": 1,
            "type": "index",
            "domains": ["x"],
            "jmespath": {"postings": "jobs[]"},
        }
        with self.assertRaises(MappingError):
            MappedIndex(document)

    def test_empty_jmespath_block_is_refused(self):
        document = {"version": 1, "type": "detail", "domains": ["x"], "jmespath": {}}
        with self.assertRaises(MappingError):
            load_mapping(document)


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


class ReferencesJobUrlGuardTest(unittest.TestCase):
    """The PostingRef.url guard Shared contracts requires of MappedIndex.references."""

    def setUp(self):
        self.mapping = MappedIndex(_INDEX_DOCUMENT)

    def test_relative_job_url_is_resolved_against_the_fetched_url(self):
        document = {"jobs": [{"absolute_url": "/jobs/123"}]}
        refs = self.mapping.references(document, "https://boards-api.example.com/x")
        self.assertEqual(refs[0].url, "https://boards-api.example.com/jobs/123")

    def test_empty_string_job_url_is_dropped_and_logged(self):
        document = {"jobs": [{"absolute_url": ""}]}
        with self.assertLogs("adapters.adapters.mapping", level="ERROR"):
            refs = self.mapping.references(
                document, "https://boards-api.example.com/jobs"
            )
        self.assertEqual(refs, [])

    def test_non_string_job_url_is_dropped_and_logged(self):
        document = {"jobs": [{"absolute_url": 3}]}
        with self.assertLogs("adapters.adapters.mapping", level="ERROR"):
            refs = self.mapping.references(
                document, "https://boards-api.example.com/jobs"
            )
        self.assertEqual(refs, [])

    def test_a_raising_job_url_drops_only_that_posting(self):
        # markdown() is typed to a single string argument, so a posting serving
        # its own url as a list (this board's real defect, per ADR 0024) raises,
        # while a second posting with a genuine string sails through unaffected.
        second_url = "https://x.example/2"
        document = {
            "jobs": [
                {"absolute_url": ["not", "a", "string"]},
                {"absolute_url": second_url},
            ]
        }
        mapping = MappedIndex(
            {
                "version": 1,
                "type": "index",
                "domains": ["boards-api.example.com"],
                "jmespath": {"postings": "jobs[]", "job_url": "markdown(absolute_url)"},
            }
        )
        with self.assertLogs("adapters.adapters.mapping", level="ERROR"):
            refs = mapping.references(document, "https://boards-api.example.com/jobs")
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].url, html_to_markdown(second_url))
        self.assertEqual(refs[0].document, {"absolute_url": second_url})


class EvaluateExpressionTest(unittest.TestCase):
    """P5 is evaluate_expression's first caller: a filter key shares this vocabulary."""

    def test_plain_path(self):
        self.assertEqual(
            evaluate_expression("offices[].name", {"offices": [{"name": "Berlin"}]}),
            ["Berlin"],
        )

    def test_unescape_evaluates_correctly(self):
        result = evaluate_expression("unescape(content)", {"content": "&lt;b&gt;"})
        self.assertEqual(result, "<b>")

    def test_markdown_evaluates_correctly(self):
        result = evaluate_expression("markdown(content)", {"content": "<p>Hi</p>"})
        self.assertEqual(result, html_to_markdown("<p>Hi</p>"))

    def test_absent_path_evaluates_to_none(self):
        self.assertIsNone(evaluate_expression("missing", {}))

    def test_syntax_error_is_a_mapping_error(self):
        with self.assertRaises(MappingError):
            evaluate_expression("a[", {})

    def test_unknown_function_name_is_refused_at_the_same_point_a_document_would_be(
        self,
    ):
        # jmespath.compile alone accepts this, the name only resolving at evaluation,
        # exactly as a mapping document's own construction-time walk catches it.
        jmespath.compile("no_such_function(title)")
        with self.assertRaises(MappingError):
            evaluate_expression("no_such_function(title)", {"title": "x"})

    def test_custom_function_signature_rejecting_its_argument_is_a_mapping_error(self):
        with self.assertRaises(MappingError):
            evaluate_expression(
                "markdown(content)", {"content": ["not", "a", "string"]}
            )

    def test_document_may_be_a_bare_list(self):
        self.assertEqual(evaluate_expression("[0]", [{"a": 1}, {"a": 2}]), {"a": 1})


if __name__ == "__main__":
    unittest.main()
