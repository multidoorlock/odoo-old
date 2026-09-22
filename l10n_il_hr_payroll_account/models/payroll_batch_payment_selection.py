from odoo import Command, api, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.safe_eval import safe_eval


class AccountBatchPayment(models.Model):
    _inherit = 'account.batch.payment'

    @api.constrains('batch_type', 'journal_id', 'payment_ids', 'payment_method_id')
    def _check_payments_constrains(self):
        """Allow mixed accounting-entry states in employee batches only.

        Odoo's native constraint rejects a batch containing both payments
        with a journal entry and payments without one.  Employee payment
        batches are also used as an operational grouping, so that restriction
        is intentionally relaxed while every other native consistency check
        remains enforced.
        """
        standard_batches = self.filtered(lambda batch: not batch.il_is_employee_batch)
        if standard_batches:
            super(AccountBatchPayment, standard_batches)._check_payments_constrains()

        for record in self - standard_batches:
            if record.payment_ids and record.journal_id != record.payment_ids.journal_id:
                raise ValidationError(_(
                    'The journal of the batch payment and of the payments it contains must be the same.'))
            all_types = set(record.payment_ids.mapped('payment_type'))
            if all_types and record.batch_type not in all_types:
                raise ValidationError(_(
                    'The batch must have the same type as the payments it contains.'))
            all_payment_methods = record.payment_ids.payment_method_id
            if len(all_payment_methods) > 1:
                raise ValidationError(_(
                    'All payments in the batch must share the same payment method.'))
            if all_payment_methods and record.payment_method_id not in all_payment_methods:
                raise ValidationError(_(
                    'The batch must have the same payment method as the payments it contains.'))
            if record.payment_ids.filtered(lambda payment: payment.amount == 0):
                raise ValidationError(_(
                    'You cannot add payments with zero amount in a Batch Payment.'))

    def _il_check_can_add_employee_payments(self):
        self.ensure_one()
        if not self.env.user.has_group('hr_payroll.group_hr_payroll_user'):
            raise AccessError(_('נדרשת הרשאת שכר כדי להוסיף תשלומי עובדים לאצווה.'))
        self.check_access('write')
        if self.company_id not in self.env.companies:
            raise AccessError(_('חברת האצווה אינה בין החברות הפעילות שלך.'))
        if self.batch_type != 'outbound' or not self.il_is_employee_batch:
            raise ValidationError(_('יש לפתוח פעולה זו מתוך תשלום אצווה של עובדים.'))
        if self.state != 'draft':
            raise UserError(_('ניתן להוסיף תשלומים רק לאצווה חדשה שטרם נשלחה.'))
        if not self.journal_id or not self.payment_method_id:
            raise ValidationError(_('יש לבחור בנק ואמצעי תשלום באצווה לפני הוספת תשלומים.'))

    def _il_existing_employee_payment_domain(self):
        self.ensure_one()
        # Reuse the native eligibility policy, including its accounting-
        # dependent allowed payment states. Native batches can contain
        # multiple currencies and compute their converted total themselves.
        domain = safe_eval(self.payment_ids_domain or '[]') + [
            ('company_id', '=', self.company_id.id),
            ('il_is_employee_payment', '=', True),
        ]
        return domain

    def action_il_add_existing_payments(self):
        self._il_check_can_add_employee_payments()
        return {
            'type': 'ir.actions.act_window',
            'name': _('הוספת תשלומים קיימים לאצווה'),
            'res_model': 'account.payment', 'view_mode': 'list', 'target': 'new',
            'views': [(self.env.ref(
                'l10n_il_hr_payroll_account.view_account_payment_list_employee_batch_candidates'
            ).id, 'list')],
            'search_view_id': (self.env.ref(
                'l10n_il_hr_payroll_account.view_account_payment_search_employee').id, ''),
            'domain': self._il_existing_employee_payment_domain(),
            'context': {
                'allowed_company_ids': self.env.companies.ids,
                'il_employee_payment': True, 'il_batch_payment_id': self.id,
                'create': False, 'edit': False, 'delete': False, 'dialog_size': 'large',
            },
            'help': _('<p class="o_view_nocontent_smiling_face">אין תשלומים זמינים להוספה</p>'
                      '<p>מוצגים תשלומי עובדים שטרם נשלחו ואינם משויכים לאצווה, '
                      'התואמים לבנק ולאמצעי התשלום של האצווה.</p>'),
        }

    def action_il_open_grouped_payments(self):
        action = super().action_il_open_grouped_payments()
        action['context'] = {
            **action['context'], 'il_batch_payment_id': self.id,
            'il_batch_allow_add_payments': self.state == 'draft' and self.il_is_employee_batch,
        }
        return action


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    @api.model
    def _il_context_employee_batch(self):
        batch_id = self.env.context.get('il_batch_payment_id')
        if not isinstance(batch_id, int) or isinstance(batch_id, bool) or batch_id <= 0:
            raise ValidationError(_('יש לפתוח את רשימת התשלומים מתוך האצווה.'))
        batch = self.env['account.batch.payment'].browse(batch_id).exists()
        if not batch:
            raise UserError(_('האצווה אינה קיימת עוד. יש לרענן את המסך.'))
        return batch

    def action_il_add_existing_batch_payments(self):
        return self._il_context_employee_batch().action_il_add_existing_payments()

    def action_il_add_selected_to_employee_batch(self):
        batch = self._il_context_employee_batch()
        if not self or self.exists() != self:
            raise ValidationError(_('יש לבחור לפחות תשלום קיים אחד להוספה לאצווה.'))
        self.check_access('read')
        self.check_access('write')
        batch._il_check_can_add_employee_payments()
        with self.env.cr.savepoint():
            self.env.flush_all()
            # Lock both the target and the complete selection before checking
            # again. A concurrent batch assignment cannot steal these rows.
            self.env.cr.execute(
                'SELECT id FROM account_batch_payment WHERE id = %s FOR UPDATE', [batch.id])
            self.env.cr.execute(
                'SELECT id FROM account_payment WHERE id IN %s ORDER BY id FOR UPDATE',
                [tuple(self.ids)])
            self.env.invalidate_all()
            batch._il_check_can_add_employee_payments()
            eligible = self.search(batch._il_existing_employee_payment_domain() + [
                ('id', 'in', self.ids)])
            if self - eligible:
                raise UserError(_(
                    'אחד התשלומים שנבחרו אינו זמין עוד לאצווה זו. '
                    'ייתכן שכבר שויך לאצווה, נשלח או שפרטיו השתנו. רענן את הרשימה.'))
            # Use the native relation update and all native batch constraints;
            # never rewrite a payment amount, state, journal or bank matching.
            batch.write({'payment_ids': [Command.link(payment.id) for payment in self]})
        return {
            'type': 'ir.actions.act_window', 'res_model': 'account.batch.payment',
            'res_id': batch.id, 'view_mode': 'form', 'views': [(False, 'form')],
            'target': 'current',
        }

    @api.model
    @api.readonly
    def get_views(self, views, options=None):
        result = super().get_views(views, options=options)
        candidate_view = self.env.ref(
            'l10n_il_hr_payroll_account.view_account_payment_list_employee_batch_candidates',
            raise_if_not_found=False)
        list_view = result.get('views', {}).get('list')
        if (candidate_view and list_view and list_view.get('id') == candidate_view.id
                and 'toolbar' in list_view):
            # Selection is added through the single header button; unrelated
            # native actions must not cancel or mutate candidate payments.
            result = dict(result, views=dict(result['views']))
            result['views']['list'] = dict(list_view, toolbar={
                **list_view['toolbar'], 'action': [],
            })
        return result
