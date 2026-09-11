import hashlib
import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    il_payslip_linked_amount = fields.Monetary(
        string='סכום בתלוש', compute='_compute_il_payslip_link_values',
        inverse='_inverse_il_payslip_linked_amount', currency_field='currency_id')
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
                    'הסכום בתלוש חייב להיות חיובי. להסרה השתמש בכפתור הסרה מהתלוש.'))
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
        return self.env['il.payroll.reconciliation.wizard']._action_open(
            payslip=slip, add_only=True)


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def action_il_manage_reconciliation(self):
        return self.action_il_open_payments()
