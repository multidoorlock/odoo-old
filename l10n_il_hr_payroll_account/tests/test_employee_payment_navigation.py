from datetime import date

from odoo import Command
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'l10n_il_employee_payment_navigation')
class TestEmployeePaymentNavigation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.env['hr.payroll.structure']._il_ensure_payroll_accounting_configuration(
            overwrite=True)
        cls.payable = cls.company.il_employee_payment_debit_account_id
        cls.journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id), ('type', '=', 'bank'),
        ], limit=1)
        cls.general_journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id), ('type', '=', 'general'),
        ], limit=1)
        cls.expense = cls.env['account.account'].search([
            ('company_ids', 'in', cls.company.id), ('account_type', '=', 'expense'),
        ], limit=1)
        cls.employees = cls.env['hr.employee'].create([
            {'name': 'Navigation Employee A', 'company_id': cls.company.id},
            {'name': 'Navigation Employee B', 'company_id': cls.company.id},
        ])
        cls.employee = cls.employees[0]
        cls.other = cls.employees[1]

    def _payment(self, employee, amount):
        return self.env['account.payment'].with_context(il_employee_payment=True).create({
            'partner_id': employee.work_contact_id.id,
            'company_id': self.company.id,
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'journal_id': self.journal.id,
            'date': date(2026, 9, 1),
            'amount': amount,
            'memo': 'Employee payment report test',
        })

    def _net_move(self, employee, amount, posted=True, account=None):
        move = self.env['account.move'].create({
            'journal_id': self.general_journal.id,
            'date': date(2026, 9, 1),
            'line_ids': [
                Command.create({'account_id': self.expense.id, 'debit': amount}),
                Command.create({
                    'account_id': (account or self.payable).id,
                    'partner_id': employee.work_contact_id.id,
                    'credit': amount,
                    'name': 'NET',
                }),
            ],
        })
        if posted:
            move.action_post()
        return move

    def test_balance_uses_payroll_account_and_opens_all_its_entries(self):
        salary = self._net_move(self.employee, 1200)
        draft = self._net_move(self.employee, 100, posted=False)
        self._net_move(self.other, 999)
        supplier = self.employee.work_contact_id.property_account_payable_id
        self.assertNotEqual(supplier, self.payable)
        self._net_move(self.employee, 300, account=supplier)
        payment = self._payment(self.employee, 500)
        payment.action_post()
        self.employee.invalidate_recordset(['il_payroll_balance'])
        self.assertEqual(self.employee.il_payroll_balance, 700)

        action = self.employee.action_il_open_payroll_ledger()
        lines = self.env[action['res_model']].search(action['domain'])
        self.assertEqual(lines.account_id, self.payable)
        self.assertEqual(lines.partner_id, self.employee.work_contact_id)
        self.assertEqual(lines.move_id, salary | draft | payment.move_id)
        self.assertEqual(action['context'], {'search_default_posted': 1})

        advance = self._payment(self.employee, 800)
        advance.action_post()
        self.employee.invalidate_recordset(['il_payroll_balance'])
        self.assertEqual(self.employee.il_payroll_balance, -100)

    def test_employee_payment_and_contact_actions_are_scoped(self):
        first = self._payment(self.employee, 100)
        second = self._payment(self.other, 200)
        action = self.employee.action_il_open_payments()
        self.assertEqual(self.env[action['res_model']].search(action['domain']), first)
        self.assertNotIn(second, self.env[action['res_model']].search(action['domain']))
        self.assertEqual(self.employee.il_payment_count, 1)
        self.assertEqual(
            self.employee.action_il_open_work_contact()['res_id'],
            self.employee.work_contact_id.id)
        # Reuse the native payslip button/action rather than add a duplicate.
        self.assertEqual(
            self.employee.action_open_payslips()['domain'],
            [('employee_id', '=', self.employee.id)])

    def test_batch_native_grouping_and_export_totals_include_every_payment(self):
        first = self._payment(self.employee, 100)
        second = self._payment(self.employee, 500)
        canceled = self._payment(self.other, 900)
        canceled.action_cancel()
        batch = self.env['account.batch.payment'].create({
            'name': 'Employee report test',
            'date': date(2026, 9, 1),
            'journal_id': self.journal.id,
            'batch_type': 'outbound',
            'payment_method_id': first.payment_method_id.id,
            'payment_ids': [Command.set((first | second | canceled).ids)],
        })
        data = batch._il_employee_payment_report_data()
        self.assertEqual(data['payment_count'], 3)
        self.assertEqual([group['amount'] for group in data['groups']], [600, 900])
        self.assertEqual(data['totals'][0]['amount'], 1500)
        action = batch.action_il_open_grouped_payments()
        self.assertEqual(action['context']['group_by'], ['il_employee_id'])
        self.assertEqual(
            set(self.env['account.payment'].search(action['domain']).ids),
            set(batch.payment_ids.ids))
        self.assertIn('pivot', action['view_mode'])

        form = self.env.ref('account_batch_payment.view_batch_payment_form')._get_combined_arch()
        self.assertEqual(form.xpath("//field[@name='payment_ids']")[0].get('widget'), 'many2many')
        list_arch = self.env.ref(
            'l10n_il_hr_payroll_account.view_account_payment_il_batch_grouped_list'
        )._get_combined_arch()
        self.assertFalse(list_arch.xpath("//field[@name='il_batch_group']"))
        self.assertEqual(list_arch.get('default_group_by'), 'il_employee_id')

        html, _ = self.env['ir.actions.report']._render_qweb_html(
            'l10n_il_hr_payroll_account.action_report_batch_employee_payments',
            res_ids=batch.ids)
        self.assertIn(self.employee.name.encode(), html)
        self.assertIn(self.other.name.encode(), html)
        self.assertIn(b'Employee payment report test', html)
