# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _il_check_reconciliation_editable(self):
        """Payroll matching does not require resetting a posted document.

        Posting and securing a journal entry are separate from matching its
        outstanding items. Native fiscal and hard lock dates still apply.
        """
        self._check_fiscal_lock_dates()
        return True


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    # This identifies the payslip-owned payable item. It is not a direct link
    # from an employee payment to a payslip: allocation exists exclusively as
    # native account.partial.reconcile records.
    il_payslip_id = fields.Many2one(
        'hr.payslip', string='Payslip', copy=False, check_company=True,
        index='btree_not_null', ondelete='set null')


class AccountPartialReconcile(models.Model):
    _inherit = 'account.partial.reconcile'

    il_payroll_finalized = fields.Boolean(
        string='התאמה סופית', default=False, copy=False, readonly=True,
        help='Final approval locks this payment-to-payslip allocation only. '
             'Other installments remain available for later payslips.')

    il_payment_id = fields.Many2one(
        related='debit_move_id.payment_id', string='Employee Payment',
        readonly=True)
    il_payment_move_id = fields.Many2one(
        related='debit_move_id.move_id', string='Payment Journal Entry',
        readonly=True)
    il_payslip_move_id = fields.Many2one(
        related='credit_move_id.move_id', string='Payslip Journal Entry',
        readonly=True)

    def _il_payslips_to_sync(self):
        return (
            self.debit_move_id.il_payslip_id
            | self.credit_move_id.il_payslip_id
        )

    @api.model
    def _il_allocation_moves(self, debit_line, credit_line):
        lines = debit_line | credit_line
        if lines.filtered('il_payslip_id') and lines.filtered('payment_id'):
            return lines.move_id
        return self.env['account.move']

    def _il_check_allocation_editable(self):
        self._il_lock_allocation_partials()
        for partial in self:
            if partial.il_payroll_finalized:
                raise UserError(_(
                    'התאמה זו אושרה סופית ולא ניתן להסיר אותה או לשנות את סכומה.'))
            self._il_allocation_moves(
                partial.debit_move_id, partial.credit_move_id,
            )._il_check_reconciliation_editable()

    def _il_lock_allocation_partials(self):
        """Serialize final approval with native edits and deletions as well."""
        allocations = self.filtered(lambda partial:
            partial.il_payroll_finalized or self._il_allocation_moves(
                partial.debit_move_id, partial.credit_move_id))
        if not allocations:
            return
        # Match the editor's payment -> payslip -> journal-item -> partial
        # order, including native unlink/finalize entry points.
        items = allocations.debit_move_id | allocations.credit_move_id
        for table, records in [
            ('account_payment', items.payment_id),
            ('hr_payslip', items.il_payslip_id),
        ]:
            if records:
                self.env.cr.execute(
                    'SELECT id FROM ' + table + ' WHERE id IN %s ORDER BY id FOR UPDATE',
                    [tuple(records.ids)],
                )
        self.env.cr.execute(
            'SELECT id FROM account_move_line WHERE id IN %s ORDER BY id FOR UPDATE',
            [tuple(items.ids)],
        )
        self.env.cr.execute(
            'SELECT id FROM account_partial_reconcile WHERE id IN %s ORDER BY id FOR UPDATE',
            [tuple(allocations.ids)],
        )
        allocations.invalidate_recordset([
            'il_payroll_finalized', 'debit_move_id', 'credit_move_id',
        ])

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            moves = self._il_allocation_moves(
                self.env['account.move.line'].browse(vals.get('debit_move_id')),
                self.env['account.move.line'].browse(vals.get('credit_move_id')),
            )
            if vals.get('il_payroll_finalized') and not moves:
                raise UserError(_('אישור זה מיועד להתאמה בין תשלום עובד לתלוש.'))
            moves._il_check_reconciliation_editable()
        partials = super().create(vals_list)
        partials._il_payslips_to_sync().sudo()._il_sync_paid_state_from_balance()
        return partials

    def write(self, vals):
        if 'il_payroll_finalized' in vals:
            self._il_lock_allocation_partials()
            if not vals['il_payroll_finalized'] and self.filtered('il_payroll_finalized'):
                raise UserError(_('לא ניתן לבטל אישור סופי של התאמה.'))
            if vals['il_payroll_finalized']:
                for partial in self:
                    moves = self._il_allocation_moves(
                        partial.debit_move_id, partial.credit_move_id)
                    if not moves:
                        raise UserError(_('אישור זה מיועד להתאמה בין תשלום עובד לתלוש.'))
                    moves._il_check_reconciliation_editable()
        if {'amount', 'debit_amount_currency', 'credit_amount_currency',
                'debit_move_id', 'credit_move_id'} & vals.keys():
            self._il_check_allocation_editable()
            for partial in self:
                self._il_allocation_moves(
                    self.env['account.move.line'].browse(
                        vals.get('debit_move_id', partial.debit_move_id.id)),
                    self.env['account.move.line'].browse(
                        vals.get('credit_move_id', partial.credit_move_id.id)),
                )._il_check_reconciliation_editable()
        payslips = self._il_payslips_to_sync()
        result = super().write(vals)
        (payslips | self._il_payslips_to_sync()).sudo().exists(
        )._il_sync_paid_state_from_balance()
        return result

    def unlink(self):
        self._il_check_allocation_editable()
        payslips = self._il_payslips_to_sync()
        # Reconciliation is a general Accounting operation. Looking up our
        # optional payroll metadata must never require the accounting user to
        # also belong to a Payroll group. Use sudo only for this internal link
        # synchronization; the native reconciliation unlink itself keeps the
        # caller's original access checks.
        split_lines = self.env['account.payment.split.line'].sudo().search([
            ('reconcile_id', 'in', self.ids),
        ])
        if split_lines:
            if not self.env.context.get('il_discard_reconciliation_target'):
                for split_line in split_lines.filtered(
                        lambda line: line.payment_id.state == 'draft'):
                    target_line = (
                        split_line.reconcile_id.debit_move_id
                        | split_line.reconcile_id.credit_move_id
                    ).filtered('il_payslip_id')[:1]
                    if target_line:
                        split_line.with_context(
                            il_reconciliation_sync=True,
                            il_skip_draft_reconciliation_check=True,
                        ).il_pending_payslip_move_line_id = target_line
            split_lines.with_context(
                il_reconciliation_sync=True,
                il_skip_draft_reconciliation_check=True,
            ).write({'reconcile_id': False})
        result = super().unlink()
        payslips.sudo().exists()._il_sync_paid_state_from_balance()
        return result
