from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare


class HrAttendanceOvertimeRule(models.Model):
    _inherit = 'hr.attendance.overtime.rule'

    mdl_pay_method = fields.Selection([
        ('percentage', 'אחוזים'),
        ('fixed', 'סכום קבוע לשעה'),
    ], string='שיטת תשלום', default='percentage', required=True)
    mdl_fixed_hourly_amount = fields.Monetary(
        string='סכום קבוע לשעה',
        currency_field='mdl_currency_id',
    )
    mdl_currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', readonly=True,
    )

    @api.constrains('paid', 'mdl_pay_method', 'mdl_fixed_hourly_amount')
    def _check_mdl_fixed_hourly_amount(self):
        for rule in self:
            if (rule.paid and rule.mdl_pay_method == 'fixed'
                    and float_compare(rule.mdl_fixed_hourly_amount, 0.0, precision_digits=2) <= 0):
                raise ValidationError('בכלל שעות נוספות בסכום קבוע חובה להזין סכום גדול מאפס.')

    def _extra_overtime_vals(self):
        vals = super()._extra_overtime_vals()
        fixed_rules = self.filtered(
            lambda rule: rule.paid and rule.mdl_pay_method == 'fixed')
        percentage_rules = self.filtered(
            lambda rule: rule.paid and rule.mdl_pay_method == 'percentage')

        if percentage_rules:
            mode = self.ruleset_id.rate_combination_mode
            if mode == 'max':
                vals['amount_rate'] = max(percentage_rules.mapped('amount_rate'))
            else:
                vals['amount_rate'] = sum(
                    (rule.amount_rate - 1.0 for rule in percentage_rules), start=1.0)
        else:
            vals['amount_rate'] = 0.0

        if fixed_rules:
            fixed_amounts = fixed_rules.mapped('mdl_fixed_hourly_amount')
            vals['mdl_fixed_hourly_amount'] = (
                max(fixed_amounts)
                if self.ruleset_id.rate_combination_mode == 'max'
                else sum(fixed_amounts)
            )
        else:
            vals['mdl_fixed_hourly_amount'] = 0.0
        return vals


class HrAttendanceOvertimeLine(models.Model):
    _inherit = 'hr.attendance.overtime.line'

    mdl_fixed_hourly_amount = fields.Monetary(
        string='סכום קבוע לשעה',
        currency_field='currency_id',
        readonly=True,
    )
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', readonly=True,
    )
