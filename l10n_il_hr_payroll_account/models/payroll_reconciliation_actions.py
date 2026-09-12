import hashlib
import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    il_payslip_linked_amount = fields.Monetary(
        string='סכום להכרה', compute='_compute_il_payslip_link_values',
        inverse='_inverse_il_payslip_linked_amount', currency_field='currency_id')
    il_recognition_available_amount = fields.Monetary(
        string='יתרה להכרה', compute='_compute_il_recognition_available_amount',
        currency_field='currency_id')
    il_payslip_link_snapshot = fields.Char(
        compute='_compute_il_payslip_link_values')
    il_payslip_link_write_token = fields.Char(
        compute='_compute_il_payslip_write_token', readonly=False)

    @api.depends_context('il_payslip_id')
    def _compute_il_payslip_write_token(self):
        for payment in self:
            payment.il_payslip_link_write_token = False

    @api.model
    def _il_context_payslip(self):
        payslip_id = self.env.context.get('il_payslip_id')
        if (not isinstance(payslip_id, int) or isinstance(payslip_id, bool)
                or payslip_id <= 0):
            raise ValidationError(_('יש לפתוח את רשימת התשלומים מתוך תלוש.'))
        slip = self.env['hr.payslip'].browse(payslip_id).exists()
        if not slip:
            raise ValidationError(_('התלוש אינו קיים עוד.'))
        slip.check_access('read')
        if slip.company_id not in self.env.companies:
            raise ValidationError(_('חברת התלוש אינה בין החברות הפעילות שלך.'))
        return slip

    def _il_payslip_link_partials(self):
        self.ensure_one()
        return self.move_id.line_ids.matched_credit_ids.filtered(
            lambda partial: partial.credit_move_id.il_payslip_id)

    def _il_recognition_items(self):
        self.ensure_one()
        return self.move_id.line_ids.filtered(lambda line:
            line.parent_state == 'posted'
            and line.account_id == self.company_id.il_employee_payment_debit_account_id
            and line.partner_id == self.partner_id
            and line.currency_id == self.currency_id and line.balance > 0)

    @api.depends('move_id.line_ids.amount_residual_currency', 'move_id.state',
                 'company_id.il_employee_payment_debit_account_id', 'partner_id', 'currency_id')
    def _compute_il_recognition_available_amount(self):
        for payment in self:
            payment.il_recognition_available_amount = max(payment.currency_id.round(
                sum(payment._il_recognition_items().mapped('amount_residual_currency'))), 0.0)

    def _il_payslip_link_token(self, slip):
        """Fingerprint this payment's allocation pool, independent of other rows.

        Editing a different payment in the same list must not stale this row.
        The full editor checks the current payslip capacity under locks as well.
        """
        self.ensure_one()
        values = {
            'payment': (self.id, self.amount, self.company_id.id,
                        self.partner_id.id, self.currency_id.id, self.move_id.id,
                        str(self.date), self.il_spread_type),
            'payslip': (slip.id, slip.employee_id.id, slip.company_id.id,
                        slip.currency_id.id, slip.move_id.id),
            'partials': [(part.id, part.amount, part.debit_amount_currency,
                          part.credit_amount_currency, part.debit_move_id.id,
                          part.credit_move_id.id)
                         for part in self._il_payslip_link_partials().sorted('id')],
            'splits': [(line.id, line.sequence, line.amount, line.reconcile_id.id,
                        line.il_pending_payslip_move_line_id.id)
                       for line in self.il_split_line_ids.sorted('id')],
            'items': [(line.id, line.account_id.id, line.partner_id.id,
                       line.currency_id.id, line.balance, line.amount_currency,
                       line.amount_residual, line.amount_residual_currency)
                      for line in self._il_recognition_items().sorted('id')],
        }
        return hashlib.sha256(json.dumps(
            values, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    @api.depends_context('il_payslip_id')
    @api.depends(
        'amount', 'move_id', 'il_split_line_ids.amount',
        'il_split_line_ids.reconcile_id',
        'move_id.line_ids.matched_credit_ids.amount',
        'move_id.line_ids.matched_credit_ids.debit_amount_currency',
    )
    def _compute_il_payslip_link_values(self):
        slip = self._il_context_payslip() if self.env.context.get('il_payslip_id') else False
        for payment in self:
            payment.il_payslip_linked_amount = 0.0
            payment.il_payslip_link_snapshot = False
            original = payment._origin
            if (not slip or not original
                    or original.company_id != slip.company_id
                    or original._il_employee() != slip.employee_id
                    or original.currency_id != slip.currency_id):
                continue
            partials = original._il_payslip_link_partials().filtered(
                lambda partial: partial.credit_move_id.il_payslip_id == slip)
            payment.il_payslip_linked_amount = sum(partials.mapped('debit_amount_currency'))
            payment.il_payslip_link_snapshot = original._il_payslip_link_token(slip)

    def write(self, vals):
        if 'il_payslip_linked_amount' in vals:
            self.ensure_one()
            if set(vals) - {'il_payslip_linked_amount', 'il_payslip_link_write_token'}:
                raise ValidationError(_(
                    'ברשימת התלוש ניתן לשנות רק את הסכום המשויך לתלוש.'))
            token = vals.get('il_payslip_link_write_token')
            if not token:
                raise UserError(_('יש לרענן את רשימת התשלומים לפני שינוי הסכום בתלוש.'))
            clean = dict(vals)
            clean.pop('il_payslip_link_write_token', None)
            result = super(AccountPayment, self.with_context(
                il_payslip_link_expected=token)).write(clean)
            self.invalidate_recordset([
                'il_payslip_linked_amount', 'il_payslip_link_snapshot',
                'il_payslip_link_write_token',
            ], flush=False)
            return result
        if 'il_payslip_link_write_token' in vals:
            vals = {key: value for key, value in vals.items()
                    if key != 'il_payslip_link_write_token'}
            if not vals:
                return True
        return super().write(vals)

    def _inverse_il_payslip_linked_amount(self):
        # Keep the proposed value before the editor invalidates ORM caches.
        for payment, amount in [(payment, payment.il_payslip_linked_amount)
                                for payment in self]:
            if payment.currency_id.compare_amounts(amount, 0.0) <= 0:
                raise ValidationError(_(
                    'הסכום להכרה חייב להיות חיובי. להסרה בחר הסרת קישור מהתלוש בתפריט פעולות.'))
            payment._il_update_payslip_link(
                amount, self.env.context.get('il_payslip_link_expected'))

    def _il_update_payslip_link(self, amount, expected_token):
        self.ensure_one()
        self.check_access('write')
        slip = self._il_context_payslip()
        Wizard = self.env['il.payroll.reconciliation.wizard']
        with self.env.cr.savepoint():
            wizard = Wizard.create({'source_payslip_id': slip.id})
            partials = wizard._scope_partials()
            wizard._lock_records(partials.debit_move_id.payment_id | self,
                                 partials.credit_move_id.il_payslip_id | slip)
            wizard._check_pair(self, slip)
            if not expected_token or expected_token != self._il_payslip_link_token(slip):
                raise UserError(_(
                    'פרטי התשלום או הסכום בתלוש השתנו מאז הצגתם. '
                    'רענן את הרשימה ונסה שוב.'))
            row = wizard.line_ids.filtered(lambda line: line.payment_id == self)
            if len(row) != 1:
                raise ValidationError(_(
                    'התשלום אינו משויך לתלוש. להוספה השתמש בכפתור הוסף תשלום.'))
            if self.currency_id.is_zero(amount):
                row.unlink()
            else:
                row.amount = amount
            wizard.action_apply()

    def action_il_remove_from_payslip(self):
        self.ensure_one()
        self._il_update_payslip_link(
            0.0, self.env.context.get('il_payslip_link_expected'))
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_il_add_payslip_payment(self):
        slip = self._il_context_payslip()
        # Native payment records remain searchable, sortable and exportable.
        # Eligibility is checked again under accounting locks when applied.
        candidates = self.env['il.payroll.reconciliation.wizard']._eligible_payments(slip)
        return {
            'type': 'ir.actions.act_window', 'name': _('תשלומים זמינים לקישור לתלוש'),
            'res_model': 'account.payment', 'view_mode': 'list', 'target': 'current',
            'views': [(self.env.ref(
                'l10n_il_hr_payroll_account.view_account_payment_list_payslip_candidates'
            ).id, 'list')],
            'search_view_id': (self.env.ref(
                'l10n_il_hr_payroll_account.view_account_payment_search_employee').id, ''),
            'domain': [('id', 'in', candidates.ids)],
            'context': {
                'allowed_company_ids': self.env.companies.ids,
                'il_employee_payment': True, 'il_payslip_id': slip.id,
                'il_payslip_candidate_list': True, 'create': False,
                'edit': False, 'delete': False,
            },
            'help': _('<p class="o_view_nocontent_smiling_face">אין תשלומים זמינים לקישור</p>'
                      '<p>מוצגים תשלומים של העובד עם יתרה להכרה, שאינם מקושרים כבר לתלוש זה.</p>'),
        }

    def action_il_select_payslip_payments(self):
        return self.env['il.payslip.payment.selection.wizard']._action_open(self, 'add')

    def action_il_change_recognized_amount(self):
        return self.env['il.payslip.payment.selection.wizard']._action_open(self, 'edit')

    def action_il_remove_payslip_links(self):
        return self.env['il.payslip.payment.selection.wizard']._action_open(self, 'remove')


class IrActionsActions(models.Model):
    _inherit = 'ir.actions.actions'

    @api.model
    def get_bindings(self, model_name):
        result = super().get_bindings(model_name)
        if model_name != 'account.payment':
            return result
        payroll_actions = {
            record.id for xmlid in (
                'l10n_il_hr_payroll_account.action_payslip_change_recognized_amount',
                'l10n_il_hr_payroll_account.action_payslip_remove_payment_links',
            ) if (record := self.env.ref(xmlid, raise_if_not_found=False))
        }
        linked = self.env.context.get('il_payslip_link_list') and self.env.context.get('il_payslip_id')
        candidates = self.env.context.get('il_payslip_candidate_list') and self.env.context.get('il_payslip_id')
        # get_bindings returns fresh dictionaries; never modify its cached
        # _get_bindings data. Accounting entry points retain native actions.
        result = dict(result)
        result['action'] = [action for action in result.get('action', [])
                            if (action['id'] in payroll_actions if linked and not candidates
                                else not candidates and action['id'] not in payroll_actions)]
        return result


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def action_il_manage_reconciliation(self):
        return self.action_il_open_payments()
