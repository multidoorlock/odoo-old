# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    il_payment_count = fields.Integer(
        string='תשלומים', compute='_compute_il_payment_count',
        groups='hr_payroll.group_hr_payroll_user')
    il_payroll_currency_id = fields.Many2one(
        'res.currency', string='Payroll Balance Currency',
        related='company_id.currency_id', readonly=True)
    il_payroll_balance = fields.Monetary(
        string='יתרה לפירעון', currency_field='il_payroll_currency_id',
        compute='_compute_il_payroll_balance',
        groups='account.group_account_readonly',
        help='יתרת שכר פתוחה בפקודות יומן רשומות. יתרה חיובית היא סכום '
             'לתשלום לעובד; יתרה שלילית היא מקדמה לקיזוז מהשכר.')

    def _il_payment_history_domain(self):
        self.ensure_one()
        if not self.work_contact_id:
            return [('id', '=', False)]
        return [
            ('partner_id', '=', self.work_contact_id.id),
            ('company_id', '=', self.company_id.id),
        ]

    @api.depends('work_contact_id', 'company_id')
    def _compute_il_payment_count(self):
        for employee in self:
            employee.il_payment_count = self.env['account.payment'].search_count(
                employee._il_payment_history_domain())

    def _il_payroll_ledger_domain(self):
        self.ensure_one()
        account = self.company_id.il_employee_payment_debit_account_id
        if not self.work_contact_id or not account:
            return [('id', '=', False)]
        return [
            ('partner_id', '=', self.work_contact_id.id),
            ('company_id', '=', self.company_id.id),
            ('account_id', '=', account.id),
            ('display_type', 'not in', ('line_section', 'line_subsection', 'line_note')),
            ('parent_state', '!=', 'cancel'),
        ]

    @api.depends('work_contact_id', 'company_id',
                 'company_id.il_employee_payment_debit_account_id')
    def _compute_il_payroll_balance(self):
        for employee in self:
            totals = self.env['account.move.line']._read_group(
                employee._il_payroll_ledger_domain() + [('parent_state', '=', 'posted')],
                [], ['amount_residual:sum'])
            # NET credits increase the amount owed; advance-payment debits
            # reduce it. Never substitute the partner's supplier account.
            employee.il_payroll_balance = -(totals[0][0] or 0.0)

    def action_il_open_work_contact(self):
        self.ensure_one()
        if not self.work_contact_id:
            raise UserError(_('לעובד לא מוגדר איש קשר.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('איש קשר'),
            'res_model': 'res.partner',
            'res_id': self.work_contact_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_il_open_payments(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id(
            'l10n_il_hr_payroll_account.il_action_employee_payments')
        action.update({
            'name': _('תשלומים — %s', self.name),
            'domain': self._il_payment_history_domain(),
            'context': {
                'default_partner_id': self.work_contact_id.id,
                'default_company_id': self.company_id.id,
                'default_payment_type': 'outbound',
                'default_partner_type': 'supplier',
                'il_employee_payment': True,
            },
        })
        return action

    def action_il_open_payroll_ledger(self):
        self.ensure_one()
        if not self.company_id.il_employee_payment_debit_account_id:
            raise UserError(_('לא מוגדר בחברה חשבון יתרות עובדים.'))
        action = self.env['ir.actions.actions']._for_xml_id(
            'account.action_account_moves_all')
        view = self.env.ref(
            'l10n_il_hr_payroll_account.view_employee_payroll_ledger_list')
        action.update({
            'name': _('יתרה ותנועות שכר — %s', self.name),
            'domain': self._il_payroll_ledger_domain(),
            'view_id': view.id,
            'views': [(view.id, 'list')] + [
                pair for pair in action['views'] if pair[1] != 'list'],
            # Both native filters are removable: clearing Unreconciled shows
            # settled entries too; clearing Posted additionally shows drafts.
            'context': {'search_default_posted': 1, 'search_default_unreconciled': 1},
        })
        return action
