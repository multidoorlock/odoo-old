from datetime import date
from unittest import SkipTest

from lxml import etree

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import new_test_user, tagged

from . import test_payment_reconciliation as payment_fixtures
from . import test_reconciliation_editor as reconciliation_fixtures
from .common import HebrewTransactionCase


@tagged('post_install', '-at_install', 'il_payroll_frontend_simulation', 'il_payroll_ui_simulation')
class TestPayslipPaymentUI(HebrewTransactionCase):
    """Code simulation of native web-client RPC contracts and workflows.

    Calls the same web_read, onchange, web_save, list and export methods used
    by the client on fresh rollback fixtures. Does not claim DOM/browser
    coverage and does not launch Chromium or Edge.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].browse(2).exists()
        if not cls.company:
            raise SkipTest('This STAGING UI simulation requires configured company 2.')
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=[cls.company.id],
                                       tracking_disable=True, no_reset_password=True,
                                       mail_create_nolog=True))
        cls.company = cls.env['res.company'].browse(cls.company.id)
        cls.payable = cls.company.il_employee_payment_debit_account_id
        cls.outstanding = cls.company.il_employee_payment_credit_account_id
        if not cls.payable or not cls.outstanding:
            raise SkipTest('This STAGING UI simulation requires configured payment accounts.')
        cls.expense = cls.env['account.account'].search([
            ('company_ids', 'in', cls.company.id), ('account_type', '=', 'expense')], limit=1)
        cls.bank_journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id), ('type', '=', 'bank')], limit=1)
        cls.general_journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id), ('type', '=', 'general')], limit=1)
        cls.monthly_type = cls.env.ref('l10n_il_hr_payroll_account.hr_payroll_structure_type_il')
        cls.monthly_structure = cls.env.ref('l10n_il_hr_payroll_account.hr_payroll_structure_il')
        cls.employee = cls.env['hr.employee'].create({
            'name': 'UI Simulation Employee', 'company_id': cls.company.id,
            'contract_date_start': date(2026, 1, 1), 'date_version': date(2026, 1, 1),
            'mdl_wage_type': 'mdl_monthly', 'schedule_pay': 'monthly',
            'structure_type_id': cls.monthly_type.id,
            'il_salary_structure_id': cls.monthly_structure.id,
        })
        cls.browser_user = new_test_user(
            cls.env, login='il_payroll_ui_simulation', name='Payroll UI Simulation',
            groups='base.group_user,base.group_allow_export,hr_payroll.group_hr_payroll_manager,account.group_account_manager',
            company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)],
            lang='he_IL')

    _payment = payment_fixtures.TestEmployeePaymentReconciliation._payment
    _payslip_with_posted_net = payment_fixtures.TestEmployeePaymentReconciliation._payslip_with_posted_net
    _settle = reconciliation_fixtures.TestPayrollReconciliationEditor._settle

    def _fixture(self):
        self.slip = self._payslip_with_posted_net(2000.0)
        self.other_slip = self._payslip_with_posted_net(1000.0)
        self.alpha = self._payment(3000.0)
        self.beta = self._payment(500.0)
        self.gamma = self._payment(700.0)
        self.delta = self._payment(1000.0)
        self.exhausted = self._payment(250.0)
        self.payments = self.alpha | self.beta | self.gamma | self.delta | self.exhausted
        for payment, memo in zip(self.payments, (
                'UI-ALPHA', 'UI-BETA', 'UI-GAMMA', 'UI-DELTA', 'UI-EXHAUSTED')):
            # Memos are fixture data, written before the browser begins.
            payment.memo = memo
        Split = self.env['account.payment.split.line']
        for payment, slip, amount in (
                (self.alpha, self.slip, 1000.0), (self.beta, self.slip, 200.0),
                (self.delta, self.other_slip, 400.0), (self.exhausted, self.other_slip, 250.0)):
            Split._il_take_open_amount(payment, amount)._il_reconcile_with_payslip(slip)
        self.bank_partials = self._settle(self.alpha)
        self.assertEqual(self.alpha.state, 'paid')
        self.baseline = self._financial_values()
        action = self.slip.action_il_open_payments()
        self.ui_action = self.env['ir.actions.act_window'].create({
            'name': 'תשלומים מקושרים — בדיקת ממשק', 'res_model': 'account.payment',
            'view_mode': 'list,form', 'domain': repr(action['domain']),
            'context': repr(dict(action['context'], allowed_company_ids=self.company.ids)),
            'search_view_id': self.env.ref('account.view_account_payment_search').id,
            'view_ids': [Command.create({'sequence': index + 1, 'view_mode': mode,
                                        'view_id': view_id})
                         for index, (view_id, mode) in enumerate(action['views'])],
        })
        self.env.flush_all()

    def _financial_values(self):
        return {
            'payments': self.payments.sorted('id').read([
                'amount', 'date', 'partner_id', 'currency_id', 'move_id', 'state']),
            'items': (self.payments.move_id.line_ids | self.slip.move_id.line_ids
                      | self.other_slip.move_id.line_ids).sorted('id').read([
                          'account_id', 'partner_id', 'debit', 'credit', 'currency_id', 'amount_currency']),
            'salary': (self.slip | self.other_slip).line_ids.sorted('id').read(['code', 'amount', 'total']),
            'bank': self.bank_partials.sorted('id').read(['amount', 'debit_move_id', 'credit_move_id']),
            'other_slip': self.other_slip._il_reconciliations().sorted('id').read([
                'amount', 'debit_move_id', 'credit_move_id']),
        }

    _list_spec = {
        'id': {}, 'name': {}, 'date': {}, 'memo': {}, 'partner_id': {},
        'amount': {}, 'il_payslip_linked_amount': {}, 'il_recognition_available_amount': {},
        'il_payslip_link_snapshot': {}, 'il_payslip_link_write_token': {},
        'il_payslip_candidate_amount': {},
    }
    _dialog_spec = {
        'id': {}, 'operation': {}, 'source_payslip_id': {}, 'payslip_remaining': {},
        'total_amount': {}, 'line_ids': {'fields': {
            'id': {}, 'payment_id': {}, 'payment_date': {}, 'memo': {},
            'payment_amount': {}, 'available_amount': {}, 'current_amount': {}, 'amount': {},
        }},
    }

    def _start_client(self):
        self._fixture()
        self.client = self.env(user=self.browser_user.id, context={
            'allowed_company_ids': self.company.ids, 'lang': 'he_IL',
            'no_reset_password': True, 'tracking_disable': True,
        })
        self.linked_action = self.slip.with_env(self.client).action_il_open_payments()
        self.Payment = self.client['account.payment'].with_context(**self.linked_action['context'])

    def _web_list(self, action=None, extra_domain=None, **kwargs):
        action = action or self.linked_action
        return self.client['account.payment'].with_context(**action['context']).web_search_read(
            action['domain'] + (extra_domain or []), self._list_spec, order='id', **kwargs)

    def _open_dialog(self, operation, payments):
        action = self.client['il.payslip.payment.selection.wizard']._action_open(
            self.Payment.browse(payments.ids), operation)
        self.assertEqual(action['target'], 'new')
        wizard = self.client[action['res_model']].browse(action['res_id']).with_context(**action['context'])
        view = wizard.with_context({'lang': 'he_IL'}).get_views(action['views'])['views']['form']
        arch = etree.fromstring(view['arch'])
        rows = arch.xpath("//field[@name='line_ids']/list")[0]
        self.assertEqual(rows.get('create'), '0')
        self.assertEqual(rows.get('delete'), '0')
        self.assertTrue(arch.xpath("//button[@special='cancel']"))
        data = wizard.web_read(self._dialog_spec)[0]
        self.assertEqual(data['source_payslip_id'], self.slip.id)
        self.assertEqual({line['payment_id'] for line in data['line_ids']}, set(payments.ids))
        return wizard

    def _web_amounts(self, wizard, amounts, save=True):
        data = wizard.web_read(self._dialog_spec)[0]
        commands = [Command.update(line['id'], {'amount': amounts[line['payment_id']]})
                    for line in data['line_ids'] if line['payment_id'] in amounts]
        # First simulate an unsaved form change. onchange must not alter any
        # original amount or persisted native allocation.
        onchange = wizard.onchange({
            'source_payslip_id': self.slip.id, 'operation': wizard.operation,
            'line_ids': commands,
        }, ['line_ids'], self._dialog_spec)
        self.assertIn('value', onchange)
        if save:
            saved = wizard.web_save({'line_ids': commands}, self._dialog_spec)[0]
            for line in saved['line_ids']:
                if line['payment_id'] in amounts:
                    self.assertEqual(line['amount'], amounts[line['payment_id']])
            self.assertEqual(saved['total_amount'], sum(line['amount'] for line in saved['line_ids']))
            return saved
        return onchange

    def _assert_financial_preservation(self):
        self.env.invalidate_all()
        self.assertEqual(self._financial_values(), self.baseline)

    def test_inline_save_discard_cap_and_stale_row_recovery(self):
        self._start_client()
        rendered = self.Payment.with_context({'lang': 'he_IL'}).get_views(
            self.linked_action['views'], {'toolbar': True})['views']['list']
        arch = etree.fromstring(rendered['arch'])
        self.assertEqual(arch.xpath('./header/button/@name'),
                         ['action_il_add_payslip_payment', 'action_il_remove_payslip_links'])
        self.assertEqual(arch.get('edit'), '1')
        self.assertEqual(arch.get('editable'), 'bottom')
        self.assertEqual(arch.get('js_class'), 'il_payslip_allocation_autosave_list')
        self.assertEqual(arch.get('open_form_view'), '1')
        self.assertIn((self.env.ref(
            'l10n_il_hr_payroll_account.view_account_payment_form_employee').id, 'form'),
            self.linked_action['views'])
        self.assertTrue(self.linked_action['context']['edit'])
        self.assertFalse(arch.xpath("./field[@name='il_recognition_available_amount']"))
        self.assertEqual(arch.xpath('./field[@sum]/@name'), ['il_payslip_linked_amount'])
        columns = arch.xpath('./field/@name')
        self.assertEqual(columns[columns.index('amount') + 1], 'il_payslip_linked_amount')
        self.assertFalse(rendered['toolbar'].get('action'))
        payment = self.Payment.browse(self.alpha.id)
        snapshot = payment.web_read(self._list_spec)[0]['il_payslip_link_snapshot']
        onchange = payment.onchange({
            'il_payslip_linked_amount': 500.0, 'il_payslip_link_write_token': snapshot,
        }, ['il_payslip_linked_amount'], self._list_spec)
        self.assertIn('value', onchange)
        # Discard an unsaved row: no accounting write occurred.
        self.assertEqual(payment.web_read(self._list_spec)[0]['il_payslip_linked_amount'], 1000.0)

        def save(amount, token=None):
            token = token or payment.web_read(self._list_spec)[0]['il_payslip_link_snapshot']
            return payment.web_save({'il_payslip_linked_amount': amount,
                                     'il_payslip_link_write_token': token}, self._list_spec)[0]

        self.assertEqual(save(600.0)['il_payslip_linked_amount'], 600.0)
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            save(3001.0)
        self.assertEqual(save(900.0)['il_payslip_linked_amount'], 900.0)
        stale = payment.web_read(self._list_spec)[0]['il_payslip_link_snapshot']
        save(650.0)
        with self.assertRaises(UserError), self.env.cr.savepoint():
            save(550.0, stale)
        self.assertEqual(payment.web_read(self._list_spec)[0]['il_payslip_linked_amount'], 650.0)
        self.assertEqual(self.beta.il_applied_amount, 200.0)
        self._assert_financial_preservation()

    def test_multi_selection_remove_and_native_candidate_add(self):
        self._start_client()
        candidate_action = self.Payment.action_il_add_payslip_payment()
        self.assertEqual(candidate_action['target'], 'new')
        self.assertEqual(candidate_action['res_model'], 'account.payment')
        self.assertEqual(candidate_action['view_mode'], 'list,form')
        self.assertEqual(candidate_action['context']['dialog_size'], 'extra-large')
        self.assertEqual(candidate_action['context']['il_payslip_id'], self.slip.id)
        candidates = self._web_list(candidate_action)['records']
        self.assertEqual({row['id'] for row in candidates}, {self.gamma.id, self.delta.id})
        self.assertEqual(next(row['il_recognition_available_amount'] for row in candidates
                              if row['id'] == self.delta.id), 600.0)
        rendered = self.Payment.with_context({'lang': 'he_IL'}).get_views(
            candidate_action['views'], {'toolbar': True})['views']['list']
        arch = etree.fromstring(rendered['arch'])
        self.assertEqual(arch.xpath('./header/button/@name'), ['action_il_select_payslip_payments'])
        self.assertEqual(arch.get('js_class'), 'il_payslip_allocation_autosave_list')
        self.assertEqual(arch.get('open_form_view'), '1')
        self.assertEqual(arch.xpath("./field[@name='il_payslip_candidate_amount']/@widget"),
                         ['il_payslip_candidate_amount'])
        self.assertIn((self.env.ref(
            'l10n_il_hr_payroll_account.view_account_payment_form_employee').id, 'form'),
            candidate_action['views'])
        self.assertFalse(rendered['toolbar'].get('action'))
        for name in ('date', 'partner_id', 'memo', 'amount', 'il_recognition_available_amount'):
            self.assertTrue(arch.xpath("./field[@name='%s']" % name))
        Candidate = self.client['account.payment'].with_context(**candidate_action['context'])
        gamma = Candidate.browse(self.gamma.id)
        saved = gamma.web_save({'il_payslip_candidate_amount': 300.0}, self._list_spec)[0]
        self.assertEqual(saved['il_payslip_candidate_amount'], 300.0)
        # Closing the popup after saving its proposed row adds no link.
        self.assertFalse(self.gamma.il_applied_amount)
        self.assertEqual(len(self._web_list()['records']), 2)

        returned = self.Payment.browse((self.alpha | self.beta).ids).action_il_remove_payslip_links()
        self.assertEqual(returned['target'], 'current')
        self.assertFalse(self._web_list(returned)['records'])
        self.assertEqual(self.alpha.state, 'paid')
        candidate_action = self.Payment.action_il_add_payslip_payment()
        candidates = self._web_list(candidate_action)['records']
        self.assertEqual(next(row['il_recognition_available_amount'] for row in candidates
                              if row['id'] == self.alpha.id), 3000.0)
        Candidate = self.client['account.payment'].with_context(**candidate_action['context'])
        for payment, amount in ((self.alpha, 1000.0), (self.beta, 200.0)):
            Candidate.browse(payment.id).web_save({'il_payslip_candidate_amount': amount}, self._list_spec)
        returned = Candidate.browse((self.alpha | self.beta).ids).action_il_select_payslip_payments()
        self.assertEqual(returned['target'], 'current')
        self.assertEqual(returned['domain'], self.slip.action_il_open_payments()['domain'])
        self.assertEqual({row['id']: row['il_payslip_linked_amount']
                          for row in self._web_list(returned)['records']},
                         {self.alpha.id: 1000.0, self.beta.id: 200.0})
        self.assertEqual(self.alpha.il_applied_amount, 1000.0)
        self.assertEqual(self.beta.il_applied_amount, 200.0)
        self.assertFalse(self.gamma.il_applied_amount)
        self._assert_financial_preservation()

    def test_native_filter_export_and_back_navigation(self):
        self._start_client()
        original_domain = list(self.linked_action['domain'])
        first_page = self._web_list(limit=1, offset=0)
        second_page = self._web_list(limit=1, offset=1)
        self.assertEqual(first_page['length'], 2)
        self.assertNotEqual(first_page['records'][0]['id'], second_page['records'][0]['id'])
        filtered = self._web_list(extra_domain=[('memo', 'ilike', 'UI-ALPHA')])['records']
        self.assertEqual([row['id'] for row in filtered], self.alpha.ids)
        exported = self.Payment.browse([row['id'] for row in filtered]).export_data([
            'memo', 'amount', 'il_payslip_linked_amount'])['datas']
        self.assertEqual(exported, [['UI-ALPHA', 3000.0, 1000.0]])
        candidate_action = self.Payment.action_il_add_payslip_payment()
        self.assertEqual(candidate_action['target'], 'new')
        candidate = self._web_list(candidate_action, [('memo', 'ilike', 'UI-DELTA')])['records']
        self.assertEqual([row['id'] for row in candidate], self.delta.ids)
        available_export = self.Payment.browse(self.delta.id).export_data([
            'amount', 'il_recognition_available_amount'])['datas']
        self.assertEqual(available_export, [[1000.0, 600.0]])
        # Returning to the original action restores its source domain; a
        # candidate search cannot change which links belong to this payslip.
        self.assertEqual(self.linked_action['domain'], original_domain)
        self.assertEqual({row['id'] for row in self._web_list()['records']},
                         {self.alpha.id, self.beta.id})
        outside = self.client['ir.actions.actions'].get_bindings('account.payment').get('action', [])
        self.assertFalse({'שינוי סכום להכרה', 'הסרת קישור מהתלוש'} & {item['name'] for item in outside})
        self.assertEqual(self.alpha.il_applied_amount, 1000.0)
        self.assertEqual(self.beta.il_applied_amount, 200.0)
        self._assert_financial_preservation()
