from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .catalog_utils import (
    DEFAULT_VARIANT_DISPLAY_FORMAT,
    VARIANT_DISPLAY_FORMAT_PARAM,
    extract_tokens,
    ltr_isolate,
    normalize_token,
    render_format,
)


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    mdl_variant_display_format = fields.Char(
        string="Product Display Format",
        config_parameter=VARIANT_DISPLAY_FORMAT_PARAM,
        default=DEFAULT_VARIANT_DISPLAY_FORMAT,
        help=(
            "A single format for variants in search results and documents. "
            "Use [SKU] and [Product Name]; the existing Hebrew tokens remain "
            "supported for backward compatibility."
        ),
    )
    mdl_variant_display_example = fields.Char(
        string="Display Example",
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
                    "SKU": ltr_isolate("[1001110020]"),
                    "שם הפריט": _("Institutional blast door left 100/20 L"),
                    "Product Name": _("Institutional blast door left 100/20 L"),
                },
            )
            settings.mdl_variant_display_example = example

    @api.constrains("mdl_variant_display_format")
    def _check_mdl_variant_display_format(self):
        allowed_tokens = {
            normalize_token("מק״ט"),
            normalize_token("SKU"),
            normalize_token("שם הפריט"),
            normalize_token("Product Name"),
        }
        for settings in self:
            tokens = {
                normalize_token(token)
                for token in extract_tokens(settings.mdl_variant_display_format)
            }
            if tokens - allowed_tokens:
                raise ValidationError(
                    _(
                        "The display format may only use [SKU], [Product Name], "
                        "[מק״ט], and [שם הפריט]."
                    )
                )
            name_tokens = {
                normalize_token("שם הפריט"),
                normalize_token("Product Name"),
            }
            if not tokens.intersection(name_tokens):
                raise ValidationError(
                    _("The display format must include [Product Name] or [שם הפריט].")
                )

