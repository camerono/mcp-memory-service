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
Tests for keeping the API key out of the HTTP access log.

The dashboard puts the key in the SSE query string because EventSource cannot
send headers, and uvicorn logs the full request line -- so without redaction
every SSE connection writes the key in cleartext to a file that outlives the
session. See issue #282.
"""

import logging

import pytest

from mcp_memory_service.web import log_redaction


def _access_record(path):
    """A record shaped like the ones uvicorn's access logger emits."""
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:57919", "GET", path, "1.1", 200),
        exc_info=None,
    )


class TestRedactQueryString:

    def test_redacts_api_key(self):
        out = log_redaction.redact_query_string("/api/events?api_key=SUPERSECRET")
        assert "SUPERSECRET" not in out
        assert out == "/api/events?api_key=REDACTED"

    def test_keeps_other_parameters_intact(self):
        out = log_redaction.redact_query_string(
            "/api/memories?page=2&api_key=SUPERSECRET&page_size=100"
        )
        assert "SUPERSECRET" not in out
        assert "page=2" in out
        assert "page_size=100" in out

    @pytest.mark.parametrize("name", ["api_key", "API_KEY", "ApiKey", "token", "access_token"])
    def test_matches_sensitive_names_case_insensitively(self, name):
        out = log_redaction.redact_query_string(f"/x?{name}=SUPERSECRET")
        assert "SUPERSECRET" not in out

    def test_leaves_urls_without_a_query_alone(self):
        assert log_redaction.redact_query_string("/api/health") == "/api/health"

    def test_leaves_untargeted_queries_byte_identical(self):
        """No rewrite at all when nothing sensitive is present, so ordinary log
        lines are not reformatted by urlencode as a side effect."""
        url = "/api/memories?page=2&tag=a+b&empty="
        assert log_redaction.redact_query_string(url) == url

    def test_redacts_every_occurrence(self):
        out = log_redaction.redact_query_string("/x?api_key=ONE&api_key=TWO")
        assert "ONE" not in out and "TWO" not in out


class TestFilter:

    def test_rewrites_the_formatted_message(self):
        record = _access_record("/api/events?api_key=SUPERSECRET")
        assert log_redaction.RedactQueryStringFilter().filter(record) is True
        assert "SUPERSECRET" not in record.getMessage()
        assert "REDACTED" in record.getMessage()

    def test_never_drops_a_record(self):
        record = _access_record("/api/health")
        assert log_redaction.RedactQueryStringFilter().filter(record) is True

    def test_tolerates_records_that_are_not_access_logs(self):
        """Other loggers reach this filter too if it is ever attached wider;
        an unexpected args shape must not raise inside logging."""
        record = logging.LogRecord(
            name="uvicorn.error", level=logging.INFO, pathname=__file__,
            lineno=1, msg="plain message", args=None, exc_info=None,
        )
        assert log_redaction.RedactQueryStringFilter().filter(record) is True
        assert record.getMessage() == "plain message"


class TestInstall:

    @pytest.fixture
    def clean_logger(self):
        logger = logging.getLogger("test.access.redaction")
        logger.filters = []
        yield logger
        logger.filters = []

    def test_adds_the_filter(self, clean_logger):
        assert log_redaction.install(clean_logger.name) is True
        assert any(
            isinstance(f, log_redaction.RedactQueryStringFilter)
            for f in clean_logger.filters
        )

    def test_is_idempotent(self, clean_logger):
        """Reimport or a second call must not stack duplicate filters."""
        log_redaction.install(clean_logger.name)
        assert log_redaction.install(clean_logger.name) is False
        assert len(clean_logger.filters) == 1

    def test_importing_the_web_package_installs_it(self):
        """web/__init__.py wires this up, so it is active however the server
        is started -- that is the property that makes app.py untouched."""
        import mcp_memory_service.web  # inline import: the import IS what this test exercises  # noqa: F401

        assert any(
            isinstance(f, log_redaction.RedactQueryStringFilter)
            for f in logging.getLogger("uvicorn.access").filters
        )
