# Copyright 2024 Heinrich Krupp
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""A comma-separated tag string must not become one entity per character (Issue #253).

Older HTTP clients wrote `metadata["tags"]` as `"seo,ciod,error"` rather than a
list. Batch entity extraction guarded the `Memory.tags` attribute against that
but unpacked `metadata["tags"]` directly, so `[*"seo,ciod"]` produced the
characters. A real database ended up with `e` (1840 links), `o`, `i` and `,` as
entities — roughly half of 73,786 links were garbage.
"""

import pytest

from mcp_memory_service.server.handlers.quality import _as_tag_list


def test_comma_separated_string_splits_on_the_comma():
    assert _as_tag_list("seo,ciod,error") == ["seo", "ciod", "error"]


def test_single_token_string_is_not_exploded_into_characters():
    assert _as_tag_list("alpha") == ["alpha"]


def test_surrounding_whitespace_is_stripped_and_empties_dropped():
    assert _as_tag_list(" seo , , ciod ") == ["seo", "ciod"]


def test_a_list_passes_through_unchanged():
    assert _as_tag_list(["seo", "ciod"]) == ["seo", "ciod"]


@pytest.mark.parametrize("value", [None, "", [], {}])
def test_empty_values_yield_an_empty_list(value):
    assert _as_tag_list(value) == []


def test_case_is_preserved():
    """Entity names are not lowercased elsewhere in this path, so nor here."""
    assert _as_tag_list("SEO,CiOD") == ["SEO", "CiOD"]


def test_merging_both_sources_never_yields_single_character_entities():
    """The shape of the real bug: metadata string plus attribute list.

    Reproduces the merge the batch extractor performs. Every result must be a
    real tag; a single-character entry means a string was unpacked.
    """
    metadata_tags = "seo,ciod,error"
    attribute_tags = ["deployment"]

    merged = list(dict.fromkeys([
        *_as_tag_list(metadata_tags),
        *_as_tag_list(attribute_tags),
    ]))

    assert merged == ["seo", "ciod", "error", "deployment"]
    assert not [t for t in merged if len(t) == 1], (
        f"single-character entities present: {merged}"
    )
    assert "," not in merged
