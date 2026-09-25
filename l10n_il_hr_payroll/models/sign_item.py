from odoo import fields, models


class SignItem(models.Model):
    _inherit = 'sign.item'

    # Public Sign pages receive this flag through the inherited QWeb input.
    # It lets the frontend fix optional radio behaviour only for Form 101,
    # without changing radio buttons in unrelated Sign templates.
    l10n_il_form_101_radio = fields.Boolean(
        string='Form 101 radio option',
        default=False,
        copy=True,
    )
