from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .catalog_utils import (
    DEFAULT_VARIANT_DISPLAY_FORMAT,
    VARIANT_DISPLAY_FORMAT_PARAM,
    extract_tokens,
    ltr_isolate,
    normalize_token,
    render_format,
    rtl_isolate,
)


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    mdl_variant_display_format = fields.Char(
        string="פורמט תצוגת פריט סופי",
        config_parameter=VARIANT_DISPLAY_FORMAT_PARAM,
        default=DEFAULT_VARIANT_DISPLAY_FORMAT,
        help=(
            "פורמט אחיד להצגת וריאנטים בחיפוש ובמסמכים. "
            "המציינים הזמינים הם [מק״ט] ו-[שם הפריט]."
        ),
    )
    mdl_variant_display_example = fields.Char(
        string="דוגמת תצוגה",
        compute="_compute_mdl_variant_display_example",
    )

    @api.depends("mdl_variant_display_format")
    def _compute_mdl_variant_display_example(self):
        for settings in self:
            example, _missing = render_format(
                settings.mdl_variant_display_format
                or DEFAULT_VARIANT_DISPLAY_FORMAT,
                {
                    "מק״ט": ltr_isolate("[1001110020]"),
                    "שם הפריט": rtl_isolate(
                        "דלת הדף מוסדית שמאל 100/20 L"
                    ),
                },
            )
            settings.mdl_variant_display_example = example

    @api.constrains("mdl_variant_display_format")
    def _check_mdl_variant_display_format(self):
        allowed_tokens = {
            normalize_token("מק״ט"),
            normalize_token("שם הפריט"),
        }
        for settings in self:
            tokens = {
                normalize_token(token)
                for token in extract_tokens(settings.mdl_variant_display_format)
            }
            if tokens - allowed_tokens:
                raise ValidationError(
                    "בפורמט התצוגה ניתן להשתמש רק ב-[מק״ט] וב-[שם הפריט]."
                )
            if normalize_token("שם הפריט") not in tokens:
                raise ValidationError(
                    "פורמט התצוגה חייב לכלול את המציין [שם הפריט]."
                )
