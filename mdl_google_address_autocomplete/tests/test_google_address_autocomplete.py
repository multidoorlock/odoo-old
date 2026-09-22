from unittest.mock import patch, sentinel

from odoo.tests.common import BaseCase

from ..controllers.google_address_autocomplete import (
    AutoCompleteController,
    HebrewAutoCompleteController,
)


class TestHebrewAddressAutocomplete(BaseCase):
    def setUp(self):
        super().setUp()
        self.controller = HebrewAutoCompleteController()

    def test_suggestions_request_hebrew_and_preserve_other_arguments(self):
        for language_code in (None, "", "en", "he_IL", "ar", "iw"):
            with self.subTest(language_code=language_code), patch.object(
                AutoCompleteController,
                "_perform_place_search",
                autospec=True,
                return_value=sentinel.result,
            ) as search:
                result = self.controller._perform_place_search(
                    "נחל חלמיש 21, כפר יונה",
                    api_key="test-key",
                    session_id="test-session",
                    language_code=language_code,
                    country_code="il",
                )
                self.assertIs(result, sentinel.result)
                search.assert_called_once_with(
                    self.controller,
                    "נחל חלמיש 21, כפר יונה",
                    api_key="test-key",
                    session_id="test-session",
                    language_code="iw",
                    country_code="il",
                )

    def test_details_request_hebrew_and_preserve_other_arguments(self):
        for language_code in (None, "", "en", "he_IL", "ar", "iw"):
            with self.subTest(language_code=language_code), patch.object(
                AutoCompleteController,
                "_perform_complete_place_search",
                autospec=True,
                return_value=sentinel.result,
            ) as search:
                result = self.controller._perform_complete_place_search(
                    "נחל חלמיש 21, כפר יונה",
                    api_key="test-key",
                    google_place_id="test-place",
                    language_code=language_code,
                    session_id="test-session",
                )
                self.assertIs(result, sentinel.result)
                search.assert_called_once_with(
                    self.controller,
                    "נחל חלמיש 21, כפר יונה",
                    api_key="test-key",
                    google_place_id="test-place",
                    language_code="iw",
                    session_id="test-session",
                )

    def test_suggestions_preserve_defaults(self):
        with patch.object(
            AutoCompleteController, "_perform_place_search", autospec=True
        ) as search:
            self.controller._perform_place_search("כפר יונה")
            search.assert_called_once_with(
                self.controller,
                "כפר יונה",
                api_key=None,
                session_id=None,
                language_code="iw",
                country_code=None,
            )

    def test_details_preserve_defaults(self):
        with patch.object(
            AutoCompleteController, "_perform_complete_place_search", autospec=True
        ) as search:
            self.controller._perform_complete_place_search("כפר יונה")
            search.assert_called_once_with(
                self.controller,
                "כפר יונה",
                api_key=None,
                google_place_id=None,
                language_code="iw",
                session_id=None,
            )

    def test_suggestions_do_not_hide_upstream_errors(self):
        with patch.object(
            AutoCompleteController,
            "_perform_place_search",
            side_effect=RuntimeError("upstream error"),
        ), self.assertRaisesRegex(RuntimeError, "upstream error"):
            self.controller._perform_place_search("כפר יונה")

    def test_details_do_not_hide_upstream_errors(self):
        with patch.object(
            AutoCompleteController,
            "_perform_complete_place_search",
            side_effect=RuntimeError("upstream error"),
        ), self.assertRaisesRegex(RuntimeError, "upstream error"):
            self.controller._perform_complete_place_search("כפר יונה")
