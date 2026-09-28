import ast
from datetime import date
from unittest import SkipTest
from lxml import etree

from odoo import Command
from odoo.tests.common import new_test_user, tagged
from odoo.tools.safe_eval import safe_eval

from .common import HebrewTransactionCase


@tagged('post_install', '-at_install', 'il_payroll_navigation_rpc_simulation')
class TestHRNavigationUIUX(HebrewTransactionCase):
    """Simulate native web-client RPC/view contracts on rollback-only fixtures.

    These are server-side navigation simulations, not browser rendering tests.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env['res.company'].browse(2).exists()
        if not company:
            raise SkipTest('This STAGING UI simulation requires configured company 2.')
        cls.env = cls.env(context=dict(
            cls.env.context, allowed_company_ids=company.ids, tracking_disable=True,
            no_reset_password=True, mail_create_nolog=True))
        cls.company = cls.env['res.company'].browse(company.id)
        cls.payable = cls.company.il_employee_payment_debit_account_id
        if not cls.payable:
            raise SkipTest('This STAGING UI simulation requires a configured payroll account.')
        cls.journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id), ('type', '=', 'bank')], limit=1)
        cls.general_journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id), ('type', '=', 'general')], limit=1)
        cls.expense = cls.env['account.account'].search([
            ('company_ids', 'in', cls.company.id), ('account_type', '=', 'expense')], limit=1)
        cls.employees = cls.env['hr.employee'].create([{
            'name': name, 'company_id': cls.company.id,
            'contract_date_start': date(2026, 1, 1), 'date_version': date(2026, 1, 1),
            'mdl_wage_type': 'mdl_monthly', 'schedule_pay': 'monthly',
            'structure_type_id': cls.env.ref(
                'l10n_il_hr_payroll_account.hr_payroll_structure_type_il').id,
            'il_salary_structure_id': cls.env.ref(
                'l10n_il_hr_payroll_account.hr_payroll_structure_il').id,
        } for name in ('UI Navigation Employee A', 'UI Navigation Employee B')])
        cls.employee, cls.other = cls.employees
        groups = [
            'base.group_user', 'base.group_allow_export',
            'hr_payroll.group_hr_payroll_manager', 'account.group_account_manager',
        ]
        for optional in ('documents.group_documents_user',
                         'maintenance.group_equipment_manager',
                         'hr_attendance.group_hr_attendance_manager'):
            if cls.env.ref(optional, raise_if_not_found=False):
                groups.append(optional)
        cls.browser_user = new_test_user(
            cls.env, login='il_hr_navigation_ui_simulation', name='HR Navigation UI Simulation',
            groups=','.join(groups), company_id=cls.company.id,
            company_ids=[Command.set(cls.company.ids)], lang='he_IL')

    def _payment(self, employee, amount, memo):
        return self.env['account.payment'].with_context(il_employee_payment=True).create({
            'partner_id': employee.work_contact_id.id, 'company_id': self.company.id,
            'payment_type': 'outbound', 'partner_type': 'supplier',
            'journal_id': self.journal.id, 'date': date(2026, 9, 1),
            'currency_id': self.company.currency_id.id, 'amount': amount, 'memo': memo,
        })

    def _net_move(self, employee, amount, name, posted=True):
        move = self.env['account.move'].create({
            'journal_id': self.general_journal.id, 'date': date(2026, 9, 1),
            'line_ids': [
                Command.create({'account_id': self.expense.id, 'debit': amount, 'name': name}),
                Command.create({'account_id': self.payable.id,
                                'partner_id': employee.work_contact_id.id,
                                'credit': amount, 'name': name}),
            ],
        })
        if posted:
            move.action_post()
        return move

    def test_batch_flat_tab_grouped_native_rpc_search_and_export(self):
        first = self._payment(self.employee, 100, 'UI-NAV-ALPHA')
        second = self._payment(self.employee, 500, 'UI-NAV-BETA')
        third = self._payment(self.other, 900, 'UI-NAV-GAMMA')
        # Same employee and date outside this batch detects a lost batch domain.
        outsider = self._payment(self.employee, 777, 'UI-NAV-OUTSIDE')
        payments = first | second | third
        batch = self.env['account.batch.payment'].create({
            'name': 'UI Navigation Batch', 'date': date(2026, 9, 1),
            'journal_id': self.journal.id, 'batch_type': 'outbound',
            'payment_method_id': first.payment_method_id.id,
            'payment_ids': [Command.set(payments.ids)],
        })
        fields = ['amount', 'state', 'memo', 'batch_payment_id', 'move_id']
        before = (payments | outsider).read(fields)
        batch = batch.with_user(self.browser_user).with_context(lang='he_IL')
        form_result = batch.get_views([
            (self.env.ref('account_batch_payment.view_batch_payment_form').id, 'form')],
            {'toolbar': True})
        form = etree.fromstring(form_result['views']['form']['arch'].encode())
        tab = form.xpath("//field[@name='payment_ids']")[0]
        self.assertEqual(tab.get('widget'), 'many2many')
        self.assertTrue(tab.xpath('./list'))
        self.assertNotEqual(tab.get('widget'), 'il_grouped_payments')
        self.assertEqual(len(form.xpath("//button[@name='action_il_open_grouped_payments']")), 1)
        specification = {'memo': {}, 'amount': {}, 'il_employee_id': {'fields': {'display_name': {}}}}
        flat = batch.web_read({'payment_ids': {'fields': specification}})[0]['payment_ids']
        self.assertEqual({row['id'] for row in flat}, set(payments.ids))
        self.assertEqual(sum(row['amount'] for row in flat), 1500)

        action = batch.action_il_open_grouped_payments()
        native = self.env['ir.actions.actions']._for_xml_id(
            'l10n_il_hr_payroll_account.il_action_employee_payments')
        self.assertEqual(action['views'], native['views'])
        self.assertEqual(action['id'], native['id'])
        self.assertEqual(action['domain'], [('batch_payment_id', '=', batch.id)])
        self.assertEqual(action['context']['group_by'], ['il_employee_id'])
        Payment = self.env['account.payment'].with_user(self.browser_user).with_context(
            dict(action['context'], lang='he_IL'))
        views = Payment.get_views(action['views'], {'toolbar': True})
        tree = etree.fromstring(views['views']['list']['arch'].encode())
        self.assertTrue(tree.xpath("./field[@name='amount' and @sum]"))
        self.assertTrue(tree.xpath("./field[@name='memo' and @optional='show']"))
        self.assertFalse(tree.xpath("./field[@name='journal_id']"))
        self.assertFalse(tree.xpath("./field[@name='payment_method_line_id']"))
        grouped = Payment.web_read_group(
            action['domain'], action['context']['group_by'], ['amount:sum'],
            auto_unfold=True, unfold_read_specification=specification)
        self.assertEqual(grouped['length'], 2)
        self.assertEqual(len(grouped['groups']), 2)
        self.assertEqual(sorted(group['amount:sum'] for group in grouped['groups']), [600, 900])
        unfolded = [row for group in grouped['groups'] for row in group['__records']]
        self.assertEqual({row['id'] for row in unfolded}, set(payments.ids))
        self.assertNotIn(outsider.id, [row['id'] for row in unfolded])
        filtered = Payment.web_search_read(
            action['domain'] + [('memo', 'ilike', 'UI-NAV-ALPHA')], specification)
        self.assertEqual([row['id'] for row in filtered['records']], first.ids)
        restored = Payment.web_search_read(action['domain'], specification)
        self.assertEqual({row['id'] for row in restored['records']}, set(payments.ids))
        self.assertTrue(self.browser_user.has_group('base.group_allow_export'))
        exported = Payment.browse([row['id'] for row in restored['records']]).export_data(
            ['il_employee_id/name', 'memo', 'amount'])['datas']
        self.assertEqual(len(exported), 3)
        self.assertEqual(sum(row[2] for row in exported), 1500)
        self.assertEqual({row[0] for row in exported}, set(self.employees.mapped('name')))
        self.assertEqual({row[1] for row in exported}, {'UI-NAV-ALPHA', 'UI-NAV-BETA', 'UI-NAV-GAMMA'})
        # Reading/exporting and cancelling by abandoning a proposed search
        # do not write payments, journal entries, or batch membership.
        self.assertEqual((payments | outsider).read(fields), before)
        self.assertEqual(batch.payment_ids, payments)

    def test_employee_buttons_and_removable_native_ledger_filters(self):
        open_move = self._net_move(self.employee, 1200, 'UI-NAV-OPEN')
        paid_move = self._net_move(self.employee, 300, 'UI-NAV-CLOSED')
        draft = self._net_move(self.employee, 50, 'UI-NAV-DRAFT', posted=False)
        outsider = self._net_move(self.other, 999, 'UI-NAV-OTHER-EMPLOYEE')
        payment = self._payment(self.employee, 300, 'UI-NAV-SETTLED')
        payment.action_post()
        (paid_move | payment.move_id).line_ids.filtered(
            lambda line: line.account_id == self.payable).reconcile()
        moves = open_move | paid_move | draft | outsider | payment.move_id
        before = moves.line_ids.sorted('id').read([
            'account_id', 'partner_id', 'debit', 'credit', 'amount_residual', 'parent_state'])
        for count in ('document_count', 'equipment_count'):
            if count in self.employee._fields:
                self.assertEqual(self.employee[count], 0)
        employee = self.employee.with_user(self.browser_user).with_context(lang='he_IL')
        result = employee.get_views([(self.env.ref('hr.view_employee_form').id, 'form')])
        form = etree.fromstring(result['views']['form']['arch'].encode())
        buttons = form.xpath("//div[@name='button_box']/button")
        expressions = [button.get('invisible', 'False') for button in buttons]
        variables = {node.id for expression in expressions for node in ast.walk(ast.parse(expression))
                     if isinstance(node, ast.Name)}
        record_values = employee.web_read({name: {} for name in variables if name in employee._fields})[0]
        record_values.update(
            context=dict(employee.env.context), uid=self.browser_user.id,
            allowed_company_ids=employee.env.companies.ids)
        visible = [button for button in buttons
                   if not safe_eval(button.get('invisible', 'False'), record_values)]
        names = [button.get('name') for button in visible]
        self.assertEqual(names[:2], ['action_il_open_work_contact', 'action_open_versions'])
        priorities = {
            'action_il_open_work_contact': 10, 'action_open_versions': 20,
            'action_open_attendance_device_cards': 30, 'action_open_payslips': 40,
            str(self.env.ref('hr_payroll.action_hr_payslip_new').id): 40,
            'action_il_open_payments': 50, 'action_il_open_payroll_ledger': 60,
            'action_open_documents': 70, 'action_open_work_entries': 90,
            'action_open_last_month_attendances': 100,
        }
        ranks = [priorities.get(name, 85) for name in names]
        self.assertEqual(ranks, sorted(ranks))
        self.assertIn('action_il_open_payments', names)
        self.assertIn('action_il_open_payroll_ledger', names)
        self.assertNotIn('action_open_documents', names)
        self.assertFalse([button for button in visible if button.xpath("./field[@name='equipment_count']")])
        self.assertEqual(names.count('action_open_last_month_attendances'), 1)
        self.assertEqual(names[-1], 'action_open_last_month_attendances')
        # Native Work Entries is intentionally hidden before any entry exists.
        # Prove both states with a real fixture instead of changing its rule.
        self.assertFalse(record_values['has_work_entries'])
        self.assertNotIn('action_open_work_entries', names)
        self.env['hr.work.entry'].create({
            'name': 'UI-NAV-WORK-ENTRY', 'employee_id': employee.id,
            'version_id': employee.version_id.id, 'date': date(2026, 9, 1),
            'duration': 8,
            'work_entry_type_id': self.env.ref('hr_work_entry.work_entry_type_attendance').id,
        })
        self.env.flush_all()
        employee.invalidate_recordset(['has_work_entries'])
        record_values['has_work_entries'] = employee.web_read({'has_work_entries': {}})[0]['has_work_entries']
        self.assertTrue(record_values['has_work_entries'])
        names = [button.get('name') for button in buttons
                 if not safe_eval(button.get('invisible', 'False'), record_values)]
        self.assertLess(names.index('action_open_work_entries'), names.index('action_open_last_month_attendances'))

        action = employee.action_il_open_payroll_ledger()
        self.assertEqual(action['context'], {'search_default_posted': 1, 'search_default_unreconciled': 1})
        Ledger = self.env['account.move.line'].with_user(self.browser_user).with_context(
            dict(action['context'], lang='he_IL'))
        view = Ledger.get_views(action['views'])['views']['list']
        ledger_tree = etree.fromstring(view['arch'].encode())
        self.assertEqual(ledger_tree.xpath("./field[@name='amount_residual']/@optional"), ['show'])
        search = self.env.ref('account.view_account_move_line_filter').with_context(lang='he_IL')._get_combined_arch()
        native_filters = {name: safe_eval(search.xpath("//filter[@name='%s']" % name)[0].get('domain'))
                          for name in ('posted', 'unreconciled')}
        spec = {'name': {}, 'amount_residual': {}, 'parent_state': {}, 'partner_id': {}}
        default = Ledger.web_search_read(action['domain'] + native_filters['posted'] + native_filters['unreconciled'], spec)
        self.assertEqual(len(default['records']), 1)
        self.assertEqual(default['records'][0]['name'], 'UI-NAV-OPEN')
        self.assertEqual(default['records'][0]['amount_residual'], -1200)
        settled = Ledger.web_search_read(action['domain'] + native_filters['posted'], spec)
        self.assertEqual(len(settled['records']), 3)
        all_entries = Ledger.web_search_read(action['domain'], spec)
        self.assertEqual(len(all_entries['records']), 4)
        self.assertIn('UI-NAV-DRAFT', [row['name'] for row in all_entries['records']])
        self.assertEqual({row['partner_id'] for row in all_entries['records']}, {employee.work_contact_id.id})
        contact = employee.action_il_open_work_contact()
        self.assertEqual((contact['res_model'], contact['res_id']), ('res.partner', employee.work_contact_id.id))
        partner_read = self.env[contact['res_model']].with_user(self.browser_user).browse(contact['res_id']).web_read({'name': {}})
        self.assertEqual(partner_read[0]['name'], employee.work_contact_id.name)
        self.assertEqual(moves.line_ids.sorted('id').read([
            'account_id', 'partner_id', 'debit', 'credit', 'amount_residual', 'parent_state']), before)
