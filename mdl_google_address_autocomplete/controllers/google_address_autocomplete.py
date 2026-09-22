from odoo.addons.google_address_autocomplete.controllers.google_address_autocomplete import (
    AutoCompleteController,
)

# Google Places (Legacy) uses "iw" for Hebrew, not Odoo's "he_IL" locale.
GOOGLE_HEBREW_LANGUAGE_CODE = "iw"


class HebrewAutoCompleteController(AutoCompleteController):
    """Request Hebrew without changing Odoo's routes or access checks."""

    def _perform_place_search(
        self,
        partial_address,
        api_key=None,
        session_id=None,
        language_code=None,
        country_code=None,
    ):
        return super()._perform_place_search(
            partial_address,
            api_key=api_key,
            session_id=session_id,
            language_code=GOOGLE_HEBREW_LANGUAGE_CODE,
            country_code=country_code,
        )

    def _perform_complete_place_search(
        self,
        address,
        api_key=None,
        google_place_id=None,
        language_code=None,
        session_id=None,
    ):
        return super()._perform_complete_place_search(
            address,
            api_key=api_key,
            google_place_id=google_place_id,
            language_code=GOOGLE_HEBREW_LANGUAGE_CODE,
            session_id=session_id,
        )
