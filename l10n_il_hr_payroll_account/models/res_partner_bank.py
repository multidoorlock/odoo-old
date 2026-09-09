from odoo import api, fields, models


class ResPartnerBank(models.Model):
    _inherit = 'res.partner.bank'

    il_masav_clearing_number = fields.Char(
        string='מספר מסלקה למס״ב',
        compute='_compute_il_masav_clearing_number',
        help='חמש ספרות: שתי ספרות קוד בנק ושלוש ספרות מספר סניף.',
    )

    @api.depends('clearing_number', 'sanitized_acc_number')
    def _compute_il_masav_clearing_number(self):
        for bank in self:
            digits = ''.join(
                character for character in (bank.clearing_number or '')
                if character.isdigit()
            )
            sanitized = (bank.sanitized_acc_number or '').upper()
            if len(digits) != 5 and sanitized.startswith('IL') and len(sanitized) == 23:
                iban_bank = sanitized[4:7]
                iban_branch = sanitized[7:10]
                if iban_bank.isdigit() and iban_branch.isdigit():
                    digits = iban_bank[-2:] + iban_branch
            bank.il_masav_clearing_number = digits if len(digits) == 5 else False
