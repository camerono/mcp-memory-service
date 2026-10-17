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

"""
Escaping for Milvus filter expressions.

Milvus takes filters as expression strings, so every caller-supplied value ends
up interpolated into a double-quoted literal. Both Milvus modules build those
strings, hence the shared helper rather than a copy in each (issue #244).
"""


def escape_expr_value(value: str) -> str:
    """Escape a value for interpolation into a Milvus expression string literal.

    The backslash is escaped first: doing the quote first would then escape the
    backslash that step just introduced. Escaping only the quote - the previous
    behaviour - left a trailing backslash to consume the closing quote, which
    made the whole expression unparseable and the query fail on input as
    ordinary as a Windows path.

    Args:
        value: Raw value destined for a ``"..."`` literal in a filter expression.

    Returns:
        The value with backslashes and double quotes escaped.
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')
