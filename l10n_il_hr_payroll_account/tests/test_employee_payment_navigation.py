from datetime import date
from copy import deepcopy
from types import SimpleNamespace
from lxml import etree

from odoo import Command
from odoo.tests.common import TransactionCase, new_test_user, tagged
from odoo.tools.safe_eval import safe_eval


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
        monthly_type = cls.env.ref(
            'l10n_il_hr_payroll_account.hr_payroll_structure_type_il')
        monthly_structure = cls.env.ref(
            'l10n_il_hr_payroll_account.hr_payroll_structure_il')
        cls.employees = cls.env['hr.employee'].create([
            {
                'name': name,
                'company_id': cls.company.id,
                'contract_date_start': date(2026, 1, 1),
                'date_version': date(2026, 1, 1),
                'mdl_wage_type': 'mdl_monthly',
                'structure_type_id': monthly_type.id,
                'il_salary_structure_id': monthly_structure.id,
                'schedule_pay': 'monthly',
            }
            for name in ('Navigation Employee A', 'Navigation Employee B')
        ])
        cls.employee = cls.employees[0]
        cls.other = cls.employees[1]

    def _payment(self, employee, amount, currency=None):
        return self.env['account.payment'].with_context(il_employee_payment=True).create({
            'partner_id': employee.work_contact_id.id,
            'company_id': self.company.id,
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'journal_id': self.journal.id,
            'date': date(2026, 9, 1),
            'amount': amount,
            'currency_id': (currency or self.company.currency_id).id,
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
        self.assertEqual(action['context'], {
            'search_default_posted': 1, 'search_default_unreconciled': 1})
        ledger_view = self.env['ir.ui.view'].browse(action['views'][0][0])
        self.assertEqual(ledger_view.inherit_id, self.env.ref('account.view_move_line_tree'))
        residual_column = ledger_view._get_combined_arch().xpath(
            "//field[@name='amount_residual']")[0]
        self.assertEqual(residual_column.get('optional'), 'show')

        (salary | payment.move_id).line_ids.filtered(
            lambda line: line.account_id == self.payable).reconcile()
        search = self.env.ref('account.view_account_move_line_filter')._get_combined_arch()
        remaining_filter = search.xpath("//filter[@name='unreconciled']")[0]
        open_lines = self.env['account.move.line'].search(
            action['domain'] + [('parent_state', '=', 'posted')]
            + safe_eval(remaining_filter.get('domain')))
        self.assertEqual(open_lines.move_id, salary)
        all_lines = self.env['account.move.line'].search(action['domain'])
        self.assertIn(payment.move_id, all_lines.move_id)
        self.assertIn(draft, all_lines.move_id)

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

    def test_employee_smartbutton_order_keeps_native_actions_and_groups(self):
        base = self.env.ref('hr.view_employee_form')
        new_payslip = str(self.env.ref('hr_payroll.action_hr_payslip_new').id)
        priorities = {
            'action_il_open_work_contact': 10,
            'action_open_versions': 20,
            'action_open_attendance_device_cards': 30,
            'action_open_payslips': 40,
            new_payslip: 40,
            'action_il_open_payments': 50,
            'action_il_open_payroll_ledger': 60,
            'action_open_documents': 70,
            'action_open_work_entries': 90,
            'action_open_last_month_attendances': 100,
        }
        for lang in ('he_IL', 'en_US'):
            employee = self.env['hr.employee'].with_context(lang=lang)
            original = base.with_context(lang=lang)._get_combined_arch()
            before = list(original.xpath("//div[@name='button_box']/button"))
            arch, _ = employee._get_view(base.id, 'form')
            after = arch.xpath("//div[@name='button_box']/button")
            self.assertEqual(len(before), len(after))
            self.assertEqual(after[0].get('name'), 'action_il_open_work_contact')
            self.assertEqual(after[1].get('name'), 'action_open_versions')
            ranks = [80 if node.xpath("./field[@name='equipment_count']")
                     else priorities.get(node.get('name'), 85) for node in after]
            self.assertEqual(ranks, sorted(ranks))
            # No new actions or permission changes; the native variants remain.
            for button in before:
                matches = [node for node in after if all(
                    node.get(key) == button.get(key)
                    for key in ('name', 'type', 'groups', 'context'))]
                self.assertEqual(len(matches), 1)
            self.assertEqual(
                etree.tostring(original),
                etree.tostring(base.with_context(lang=lang)._get_combined_arch()))
            for count in ('document_count', 'equipment_count'):
                nodes = arch.xpath("//div[@name='button_box']/button[field[@name='%s']]" % count)
                for button in nodes:
                    self.assertTrue(safe_eval(button.get('invisible'), {count: 0}))
                    self.assertFalse(safe_eval(button.get('invisible'), {count: 1}))

        # Optional Documents and Maintenance actions retain native group access.
        hr_user = new_test_user(self.env(context=dict(self.env.context, no_reset_password=True)),
                                login='il_employee_navigation_hr_user',
                                groups='hr.group_hr_user')
        view = self.env['hr.employee'].with_user(hr_user).get_view(base.id, 'form')
        visible = etree.fromstring(view['arch'].encode())
        for count, group in (('document_count', 'documents.group_documents_user'),
                             ('equipment_count', 'maintenance.group_equipment_manager')):
            if count in self.env['hr.employee']._fields:
                self.assertEqual(bool(visible.xpath("//button[field[@name='%s']]" % count)),
                                 hr_user.has_group(group))

    def test_employee_smartbutton_order_tolerates_missing_optional_addons(self):
        arch = etree.fromstring('''<form><div name="button_box">
            <button name="other_native_action" groups="hr.group_hr_user"/>
            <button name="action_open_work_entries"/>
            <field name="work_contact_id" invisible="1"/>
            <button name="action_open_versions"/>
            <button name="action_il_open_work_contact"/>
        </div></form>''')
        result = self.env['hr.employee']._il_order_employee_smartbuttons(arch)
        self.assertEqual([node.get('name') for node in result.xpath('//button')], [
            'action_il_open_work_contact', 'action_open_versions',
            'other_native_action', 'action_open_work_entries'])
        self.assertEqual(result.xpath('//div/field')[0].get('name'), 'work_contact_id')

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
        general = self.env['ir.actions.actions']._for_xml_id(
            'l10n_il_hr_payroll_account.il_action_employee_payments')
        self.assertEqual(action['id'], general['id'])
        self.assertEqual(action['views'], general['views'])
        self.assertEqual(action['view_mode'], general['view_mode'])
        self.assertNotIn('search_default_il_filter_employee', action['context'])

        form = self.env.ref('account_batch_payment.view_batch_payment_form')._get_combined_arch()
        self.assertEqual(form.xpath("//field[@name='payment_ids']")[0].get('widget'), 'many2many')
        retired_list = self.env.ref(
            'l10n_il_hr_payroll_account.view_account_payment_il_batch_grouped_list'
        )
        self.assertFalse(retired_list.active)

        html, _ = self.env['ir.actions.report']._render_qweb_html(
            'l10n_il_hr_payroll_account.action_report_batch_employee_payments',
            batch.ids)
        self.assertIn(self.employee.name.encode(), html)
        self.assertIn(self.other.name.encode(), html)
        self.assertNotIn(b'Employee payment report test', html)
        table = etree.HTML(html).xpath(
            "//table[contains(@class, 'il_batch_employee_summary')]")[0]
        self.assertEqual(len(table.xpath('./thead/tr/th')), 2)
        self.assertEqual(len(table.xpath('./tbody/tr')), 2)
        self.assertTrue(all(len(row.xpath('./td')) == 2 for row in table.xpath('./tbody/tr')))
        self.assertEqual(len(table.xpath('./tfoot/tr')), 1)
        count = etree.HTML(html).xpath("//span[@class='il_employee_count']")[0]
        self.assertEqual(count.text, '2')

    def test_report_keeps_multiple_currencies_in_one_employee_row(self):
        other_currency = self.env.ref('base.USD')
        if other_currency == self.company.currency_id:
            other_currency = self.env.ref('base.EUR')
        other_currency.active = True
        first = self._payment(self.employee, 100)
        second = self._payment(self.employee, 50, currency=other_currency)
        # Exercise the report aggregator independently of a bank's currency
        # restrictions: never collapse unlike currencies into one number.
        batch = self.env['account.batch.payment'].new({
            'payment_ids': [Command.set((first | second).ids)],
        })
        data = batch._il_employee_payment_report_data()
        self.assertEqual(len(data['employees']), 1)
        self.assertEqual(len(data['employees'][0]['amounts']), 2)
        self.assertEqual({item['currency'].id: item['amount']
                          for item in data['employees'][0]['amounts']}, {
            self.company.currency_id.id: 100,
            other_currency.id: 50,
        })

    def test_batch_vat_fallback_is_translated_without_changing_other_reports(self):
        layout = self.env.ref('web.external_layout_standard')._get_combined_arch()
        # Render the actual inherited VAT block, including the condition and
        # unchanged native fallback, without changing company/country records.
        block = layout.xpath("//t[@t-if='company.vat']")[0]
        company = SimpleNamespace(vat='123456789', country_id=SimpleNamespace(vat_label=False))
        for lang, translated in (('en_US', 'Tax ID'), ('he_IL', 'ח.פ / ע.מ')):
            qweb = self.env['ir.qweb'].with_context(lang=lang)
            for model, flag, expected in (
                    ('account.batch.payment', True, translated),
                    ('account.batch.payment', False, 'Tax ID'),
                    ('account.move', True, 'Tax ID'),
                    ('account.move', None, 'Tax ID')):
                values = {'company': company, 'o': SimpleNamespace(_name=model)}
                if flag is not None:
                    values['il_batch_employee_report'] = flag
                rendered = str(qweb._render(deepcopy(block), values))
                self.assertIn(expected, rendered)
            company.country_id.vat_label = 'Configured tax label'
            rendered = str(qweb._render(deepcopy(block), {
                'company': company, 'o': SimpleNamespace(_name='account.batch.payment'),
                'il_batch_employee_report': True}))
            self.assertIn('Configured tax label', rendered)
            company.country_id.vat_label = False
