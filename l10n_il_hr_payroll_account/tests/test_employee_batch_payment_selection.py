from datetime import date

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import new_test_user, tagged

from . import test_payment_reconciliation as payment_fixtures
from .common import HebrewTransactionCase


@tagged('post_install', '-at_install', 'il_employee_batch_payment_selection')
class TestEmployeeBatchPaymentSelection(HebrewTransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.env['hr.payroll.structure']._il_ensure_payroll_accounting_configuration(overwrite=True)
        cls.bank_journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id), ('type', '=', 'bank')], limit=1)
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Existing Batch Payment Employee', 'company_id': cls.company.id,
            'contract_date_start': date(2026, 1, 1), 'date_version': date(2026, 1, 1),
            'mdl_wage_type': 'mdl_monthly', 'schedule_pay': 'monthly',
            'structure_type_id': cls.env.ref(
                'l10n_il_hr_payroll_account.hr_payroll_structure_type_il').id,
            'il_salary_structure_id': cls.env.ref(
                'l10n_il_hr_payroll_account.hr_payroll_structure_il').id,
        })
        cls.cycle_type = cls.env['il.payment.cycle.type'].create({
            'name': 'Existing Batch Payment Weekly', 'recurrence': 'week'})

    _payment = payment_fixtures.TestEmployeePaymentReconciliation._payment

    def _batch(self, payments=None):
        payments = payments if payments is not None else self.env['account.payment']
        return self.env['account.batch.payment'].create({
            'name': 'Existing payment selection', 'date': date(2026, 8, 1),
            'journal_id': self.bank_journal.id, 'batch_type': 'outbound',
            'il_payment_cycle_type_ids': [Command.link(self.cycle_type.id)],
            'payment_ids': [Command.set(payments.ids)],
        })

    def _select(self, batch, payments):
        return payments.with_context(il_batch_payment_id=batch.id).action_il_add_selected_to_employee_batch()

    def _financial_values(self, payments):
        return [(payment.id, payment.amount, payment.date, payment.state, payment.is_sent,
                 payment.currency_id.id, payment.journal_id.id, payment.payment_method_id.id,
                 payment.move_id.id, payment.move_id.state,
                 tuple((line.id, line.account_id.id, line.balance, line.amount_residual,
                        tuple(line.matched_debit_ids.ids), tuple(line.matched_credit_ids.ids))
                       for line in payment.move_id.line_ids.sorted('id')),
                 tuple((split.id, split.amount, split.reconcile_id.id)
                       for split in payment.il_split_line_ids.sorted('id')))
                for payment in payments.sorted('id')]

    def test_add_popup_shows_native_eligible_payments_with_details(self):
        current = self._payment(100.0)
        batch = self._batch(current)
        eligible = self._payment(250.0)
        draft = self._payment(350.0, post=False)
        sent = self._payment(450.0)
        sent.mark_as_sent()
        elsewhere = self._payment(550.0)
        self._batch(elsewhere)
        action = batch.action_il_add_existing_payments()
        self.assertEqual((action['res_model'], action['target']), ('account.payment', 'new'))
        self.assertEqual(action['context']['il_batch_payment_id'], batch.id)
        available = self.env['account.payment'].search(action['domain'])
        self.assertIn(eligible, available)
        self.assertFalse((current | draft | sent | elsewhere) & available)
        self.assertIn(('state', 'in', batch._valid_payment_states()), action['domain'])
        view = self.env.ref(
            'l10n_il_hr_payroll_account.view_account_payment_list_employee_batch_candidates')
        arch = view._get_combined_arch()
        self.assertEqual(arch.xpath('./header/button/@name'), ['action_il_add_selected_to_employee_batch'])
        self.assertFalse(arch.xpath('./header/button/@display'))
        self.assertFalse(arch.xpath('./button'))
        for name in ('date', 'name', 'partner_id', 'memo', 'amount', 'currency_id'):
            self.assertTrue(arch.xpath("./field[@name='%s']" % name))
        self.assertFalse(arch.xpath("./field[@name='amount']/@sum"))
        self.assertEqual(arch.xpath("./field[@name='currency_id']/@column_invisible"), ['False'])
        toolbar = self.env['account.payment'].with_context(lang='he_IL').get_views(
            [(view.id, 'list')], {'toolbar': True})['views']['list']['toolbar']
        self.assertFalse(toolbar.get('action'))
        prefix = 'l10n_il_hr_payroll_account.'
        ordinary = self.env.ref(prefix + 'view_account_payment_list_employee')._get_combined_arch()
        self.assertEqual(ordinary.xpath(
            "./header/button[@name='action_il_add_existing_batch_payments']/@invisible"),
            ["not context.get('il_batch_allow_add_payments')"])
        for xmlid in ('view_account_payment_list_payslip_links', 'view_account_payment_list_payslip_candidates'):
            special = self.env.ref(prefix + xmlid)._get_combined_arch()
            self.assertFalse(special.xpath("./header/button[@name='action_il_add_existing_batch_payments']"))

    def test_selected_add_preserves_documents_and_updates_batch_and_smart_button(self):
        current = self._payment(100.0)
        batch = self._batch(current)
        first, second = self._payment(200.0), self._payment(300.0)
        all_payments = current | first | second
        before = self._financial_values(all_payments)
        # Selection order is independent of the native payment list's sort.
        result = self._select(batch, second | first)
        self.assertEqual((result['res_model'], result['res_id'], result['target']),
                         ('account.batch.payment', batch.id, 'current'))
        self.assertEqual(set(batch.payment_ids.ids), set(all_payments.ids))
        self.assertEqual(batch.il_payment_count, 3)
        self.assertEqual(sum(batch.payment_ids.mapped('amount')), 600.0)
        self.assertEqual(batch.state, 'draft')
        self.assertEqual(self._financial_values(all_payments), before)
        contents = batch.action_il_open_grouped_payments()
        native = self.env['ir.actions.actions']._for_xml_id(
            'l10n_il_hr_payroll_account.il_action_employee_payments')
        self.assertEqual(contents['views'], native['views'])
        self.assertEqual(contents['domain'], [('batch_payment_id', '=', batch.id)])
        self.assertEqual(contents['context']['group_by'], ['il_employee_id'])
        self.assertEqual(contents['context']['il_batch_payment_id'], batch.id)
        self.assertTrue(contents['context']['il_batch_allow_add_payments'])
        self.assertEqual(set(self.env['account.payment'].search(contents['domain']).ids), set(all_payments.ids))
        reopened = self.env['account.payment'].with_context(
            contents['context']).action_il_add_existing_batch_payments()
        self.assertEqual(reopened['target'], 'new')
        self.assertFalse(all_payments & self.env['account.payment'].search(reopened['domain']))

    def test_empty_cycle_batch_can_add_without_creating_new_payment(self):
        batch = self._batch()
        payment = self._payment(425.0)
        before_count = self.env['account.payment'].search_count([])
        self.assertEqual(batch.state, 'draft')
        self.assertTrue(batch.il_is_employee_batch)
        self.assertIn(payment, self.env['account.payment'].search(
            batch.action_il_add_existing_payments()['domain']))
        self._select(batch, payment)
        self.assertEqual(batch.payment_ids, payment)
        self.assertEqual(self.env['account.payment'].search_count([]), before_count)

    def test_employee_batch_allows_payments_with_and_without_entries(self):
        posted = self._payment(100.0)
        without_entry = self._payment(200.0, post=False)
        batch = self._batch(posted | without_entry)
        additional = self._payment(300.0)

        self._select(batch, additional)

        self.assertEqual(
            set(batch.payment_ids.ids),
            set((posted | without_entry | additional).ids),
        )
        self.assertEqual(len(batch.payment_ids.filtered('move_id')), 2)
        self.assertEqual(len(batch.payment_ids.filtered(lambda payment: not payment.move_id)), 1)

    def test_standard_batch_still_rejects_mixed_entry_states(self):
        vendor = self.env['res.partner'].create({
            'name': 'Standard Batch Vendor',
            'supplier_rank': 1,
        })
        payment_values = {
            'partner_id': vendor.id,
            'company_id': self.company.id,
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'journal_id': self.bank_journal.id,
            'date': date(2026, 8, 1),
        }
        posted = self.env['account.payment'].create({
            **payment_values,
            'amount': 100.0,
        })
        payment_move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.bank_journal.id,
            'date': date(2026, 8, 1),
            'line_ids': [
                Command.create({
                    'name': 'Standard batch test debit',
                    'account_id': self.company.il_employee_payment_debit_account_id.id,
                    'debit': 100.0,
                }),
                Command.create({
                    'name': 'Standard batch test credit',
                    'account_id': self.company.il_employee_payment_credit_account_id.id,
                    'credit': 100.0,
                }),
            ],
        })
        posted.move_id = payment_move
        without_entry = self.env['account.payment'].create({
            **payment_values,
            'amount': 200.0,
        })

        self.assertTrue(posted.move_id)
        self.assertFalse(without_entry.move_id)
        self.assertFalse(any((posted | without_entry).mapped('il_is_employee_payment')))

        with self.assertRaisesRegex(ValidationError, 'entry or not at all'):
            self.env['account.batch.payment'].create({
                'name': 'Standard mixed batch',
                'date': date(2026, 8, 1),
                'journal_id': self.bank_journal.id,
                'batch_type': 'outbound',
                'payment_ids': [Command.set((posted | without_entry).ids)],
            })

    def test_stale_assignment_rejects_entire_selection_and_duplicate_replay(self):
        current = self._payment(100.0)
        batch = self._batch(current)
        first, second = self._payment(200.0), self._payment(300.0)
        popup = batch.action_il_add_existing_payments()
        self.assertIn(second, self.env['account.payment'].search(popup['domain']))
        other = self._batch(second)
        with self.assertRaises(UserError):
            self._select(batch, first | second)
        self.assertEqual(batch.payment_ids, current)
        self.assertEqual(other.payment_ids, second)
        self.assertFalse(first.batch_payment_id)
        self._select(batch, first)
        with self.assertRaises(UserError):
            self._select(batch, first)
        self.assertEqual(set(batch.payment_ids.ids), {current.id, first.id})
        self.assertEqual(other.payment_ids, second)

    def test_sent_batch_and_foreign_journal_cannot_be_changed_by_stale_popup(self):
        current = self._payment(100.0)
        batch = self._batch(current)
        available = self._payment(200.0)
        batch.action_il_add_existing_payments()
        current.mark_as_sent()
        self.assertNotEqual(batch.state, 'draft')
        with self.assertRaises(UserError):
            self._select(batch, available)
        self.assertFalse(available.batch_payment_id)
        self.assertEqual(batch.payment_ids, current)
        self.assertFalse(batch.action_il_open_grouped_payments()['context']['il_batch_allow_add_payments'])

        other_journal = self.env['account.journal'].create({
            'name': 'Existing Batch Other Bank', 'code': 'IBS', 'type': 'bank',
            'company_id': self.company.id,
        })
        different = self._payment(300.0, post=False)
        different.journal_id = other_journal
        different.action_post()
        draft_batch = self._batch()
        with self.assertRaises(UserError):
            self._select(draft_batch, available | different)
        self.assertFalse((available | different).batch_payment_id)
        self.assertFalse(draft_batch.payment_ids)

    def test_add_requires_employee_batch_context_and_payroll_access(self):
        payment = self._payment(100.0)
        batch = self._batch()
        with self.assertRaises(ValidationError):
            payment.action_il_add_selected_to_employee_batch()
        with self.assertRaises(ValidationError):
            self._select(batch, self.env['account.payment'])
        user = new_test_user(
            self.env(context=dict(self.env.context, no_reset_password=True)),
            login='employee_batch_accounting_only',
            groups='base.group_user,account.group_account_manager',
            company_id=self.company.id, company_ids=[Command.set(self.company.ids)],
        )
        self.assertFalse(user.has_group('hr_payroll.group_hr_payroll_user'))
        with self.assertRaises(AccessError):
            self._select(batch, payment.with_user(user))
        self.assertFalse(payment.batch_payment_id)
        self.assertFalse(batch.payment_ids)
