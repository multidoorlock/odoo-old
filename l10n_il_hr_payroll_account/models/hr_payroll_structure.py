# -*- coding: utf-8 -*-
from odoo import Command, api, models


# Accounts are looked up by code first and then by their exact translated
# name.  This keeps upgrades idempotent and avoids creating a duplicate when a
# customer already has an account for the same purpose under a different code.
IL_PAYROLL_ACCOUNT_SPECS = {
    'salary_expense': ('630000', 'Salary Expenses', 'הוצאות שכר', 'expense'),
    'overtime_expense': ('630100', 'Overtime Expenses', 'הוצאות שכר - שעות נוספות', 'expense'),
    'additional_days_expense': ('630110', 'Additional Days Expenses', 'הוצאות שכר - ימים נוספים', 'expense'),
    'salary_adjustment_expense': ('630120', 'Salary Adjustment Expenses', 'הוצאות התאמות שכר', 'expense'),
    'employer_ni_expense': ('630200', 'Employer National Insurance Expenses', 'הוצאות ביטוח לאומי - מעסיק', 'expense'),
    'employer_pension_expense': ('630300', 'Employer Pension Expenses', 'הוצאות פנסיה - מעסיק', 'expense'),
    'employer_severance_expense': ('630400', 'Employer Severance Expenses', 'הוצאות פיצויים - מעסיק', 'expense'),
    'employer_study_expense': ('630500', 'Employer Study Fund Expenses', 'הוצאות קרן השתלמות - מעסיק', 'expense'),
    'equalization_expense': ('630600', 'Equalization Levy Expenses', 'הוצאות היטל השוואה', 'expense'),
    'payroll_rounding': ('630900', 'Payroll Rounding Differences', 'הפרשי עיגול שכר', 'expense'),
    'salary_payable': ('230000', 'Salaries Payable', 'משכורות לתשלום', 'liability_current'),
    'outstanding_payments': ('101404', 'Outstanding Payments', 'תשלומים בדרך', 'asset_current'),
    'income_tax_payable': ('230110', 'Income Tax Payable', 'מס הכנסה לשלם', 'liability_current'),
    'national_insurance_payable': ('230120', 'National Insurance Payable', 'ביטוח לאומי לשלם', 'liability_current'),
    'health_insurance_payable': ('230130', 'Health Insurance Payable', 'ביטוח בריאות לשלם', 'liability_current'),
    'health_stamp_payable': ('230140', 'Health Stamp Payable', 'בול בריאות לשלם', 'liability_current'),
    'organization_tax_payable': ('230150', 'Organization Tax Payable', 'מס ארגון לשלם', 'liability_current'),
    'pension_payable': ('230300', 'Pension Funds Payable', 'קופות פנסיה לשלם', 'liability_current'),
    'study_fund_payable': ('230400', 'Study Fund Payable', 'קרן השתלמות לשלם', 'liability_current'),
    'severance_payable': ('230500', 'Severance Payable', 'פיצויים לשלם', 'liability_current'),
    'equalization_payable': ('230600', 'Equalization Levy Payable', 'היטל השוואה לשלם', 'liability_current'),
}


# Values are ``(account_debit, account_credit)`` field keys.  Employee
# deductions are negative salary-rule amounts.  Odoo therefore produces their
# desired credit entry from ``account_debit`` (the native payroll accounting
# engine reverses debit/credit for negative amounts).
IL_RULE_ACCOUNT_MAP = {
    'BASIC': ('salary_expense', False),
    'IL_OVERTIME': ('overtime_expense', False),
    'IL_WEEKEND_GROSS': ('overtime_expense', False),
    'IL_ADDITIONAL_DAY_GROSS': ('additional_days_expense', False),
    'IL_ADJUSTMENT_GROSS': ('salary_adjustment_expense', False),
    'IL_ADJUSTMENT_NET_GROSSUP': ('salary_adjustment_expense', False),
    'IL_ISR_INCOME_TAX': ('income_tax_payable', False),
    'IL_PAL_INCOME_TAX': ('income_tax_payable', False),
    'IL_ISR_NI_EE': ('national_insurance_payable', False),
    'IL_PAL_NI_EE': ('national_insurance_payable', False),
    'IL_ISR_HEALTH_EE': ('health_insurance_payable', False),
    'IL_PAL_HEALTH_STAMP': ('health_stamp_payable', False),
    'IL_PAL_ORGANIZATION_TAX': ('organization_tax_payable', False),
    'IL_ISR_PENSION_EE': ('pension_payable', False),
    'IL_PAL_PENSION_EE': ('pension_payable', False),
    'IL_ISR_STUDY_EE': ('study_fund_payable', False),
    'IL_PAL_STUDY_EE': ('study_fund_payable', False),
    'IL_ISR_NI_ER': ('employer_ni_expense', 'national_insurance_payable'),
    'IL_PAL_NI_ER': ('employer_ni_expense', 'national_insurance_payable'),
    'IL_ISR_PENSION_ER': ('employer_pension_expense', 'pension_payable'),
    'IL_PAL_PENSION_ER': ('employer_pension_expense', 'pension_payable'),
    'IL_ISR_SEVERANCE_ER': ('employer_severance_expense', 'severance_payable'),
    'IL_PAL_SEVERANCE_ER': ('employer_severance_expense', 'severance_payable'),
    'IL_ISR_STUDY_ER': ('employer_study_expense', 'study_fund_payable'),
    'IL_PAL_STUDY_ER': ('employer_study_expense', 'study_fund_payable'),
    'IL_PAL_EQUALIZATION_ER': ('equalization_expense', 'equalization_payable'),
    'NET': (False, 'salary_payable'),
}


class HrPayrollStructure(models.Model):
    _inherit = 'hr.payroll.structure'

    @api.model
    def _il_ensure_payroll_accounting_configuration(self, overwrite=False):
        """Create missing payroll accounts and map existing IL salary rules.

        No salary rule is created here.  With the default ``overwrite=False``,
        an accountant's existing rule mapping is preserved.  ``overwrite`` is
        reserved for an explicit setup/reset operation.
        """
        company = self.env.company
        Account = self.env['account.account'].with_company(company).with_context(
            allowed_company_ids=[company.id],
        )
        hebrew_installed = bool(self.env['res.lang']._lang_get('he_IL'))
        accounts = {}
        for key, (code, name_en, name_he, account_type) in IL_PAYROLL_ACCOUNT_SPECS.items():
            account = Account.search([
                ('company_ids', 'in', company.id),
                ('code', '=', code),
            ], limit=1)
            if not account:
                account = Account.with_context(lang='en_US').search([
                    ('company_ids', 'in', company.id),
                    ('name', '=', name_en),
                ], limit=1)
            if not account and hebrew_installed:
                account = Account.with_context(lang='he_IL').search([
                    ('company_ids', 'in', company.id),
                    ('name', '=', name_he),
                ], limit=1)
            if not account:
                account = Account.with_context(lang='en_US').create({
                    'code': code,
                    'name': name_en,
                    'account_type': account_type,
                    'company_ids': [Command.set(company.ids)],
                    'reconcile': True,
                })
                if hebrew_installed:
                    account.with_context(lang='he_IL').name = name_he
            elif not account.reconcile:
                account.reconcile = True
            accounts[key] = account

        structures = self.with_context(active_test=False).search([
            ('code', 'in', (
                'IL_ISR_MONTHLY', 'IL_ISR_DAILY',
                'IL_PAL_MONTHLY', 'IL_PAL_DAILY',
            )),
        ])
        # Odoo uses the salary journal's default account only for the balancing
        # line when independently rounded salary components differ by a cent.
        # It is an accounting adjustment and does not add a rounding rule or a
        # visible rounding line to the payslip.
        for journal in structures.mapped('journal_id').filtered(
                lambda item: item.company_id == company and not item.default_account_id):
            journal.default_account_id = accounts['payroll_rounding']
        rules = structures.mapped('rule_ids').with_context(active_test=False).filtered(
            lambda rule: rule.code in IL_RULE_ACCOUNT_MAP
        )
        for rule in rules.with_company(company):
            debit_key, credit_key = IL_RULE_ACCOUNT_MAP[rule.code]
            desired = {
                'account_debit': accounts.get(debit_key) if debit_key else False,
                'account_credit': accounts.get(credit_key) if credit_key else False,
            }
            values = {
                field_name: account
                for field_name, account in desired.items()
                if overwrite or not rule[field_name]
            }
            if values:
                rule.write(values)
        payment_accounts = {
            'il_employee_payment_debit_account_id': accounts['salary_payable'],
            'il_employee_payment_credit_account_id': accounts['outstanding_payments'],
        }
        company_values = {
            field_name: account
            for field_name, account in payment_accounts.items()
            if overwrite or not company[field_name]
        }
        if company_values:
            company.write(company_values)
        return True

    @api.model
    def _il_sync_structures_and_rules(self):
        # Payments and Net to Pay are live reconciliation-backed payslip
        # summary values, not salary rules. Retire every legacy copy before
        # synchronising the four Israeli structures.
        self.env['hr.salary.rule'].with_context(active_test=False).search([
            ('code', 'in', ('IL_PAYMENTS', 'IL_NET_TO_PAY')),
        ]).write({
            'active': False,
            'appears_on_payslip': False,
        })
        refs = {
            'isr_monthly': self.env.ref('l10n_il_hr_payroll_account.hr_payroll_structure_il'),
            'pal_monthly': self.env.ref('l10n_il_hr_payroll_account.hr_payroll_structure_il_pal_monthly'),
            'isr_daily': self.env.ref('l10n_il_hr_payroll_account.hr_payroll_structure_il_isr_daily'),
            'pal_daily': self.env.ref('l10n_il_hr_payroll_account.hr_payroll_structure_il_pal_daily'),
        }
        country = self.env.ref('base.il')
        obsolete_structures = self.with_context(active_test=False).search([
            ('country_id', '=', country.id),
            ('id', 'not in', [structure.id for structure in refs.values()]),
        ])
        for structure in obsolete_structures:
            if self.env['hr.payslip'].search_count([('struct_id', '=', structure.id)]):
                structure.active = False
            else:
                structure.unlink()
        template = refs['isr_monthly']
        rules = template.rule_ids
        common = rules.filtered(lambda r: not r.code.startswith(('IL_ISR_', 'IL_PAL_', 'IL_FOR_')))
        groups = {
            'pal_monthly': common | rules.filtered(lambda r: r.code.startswith('IL_PAL_')),
            'isr_daily': common | rules.filtered(lambda r: r.code.startswith('IL_ISR_')),
            'pal_daily': common | rules.filtered(lambda r: r.code.startswith('IL_PAL_')),
        }
        values_by_key = {}
        for key, selected in groups.items():
            values_by_key[key] = []
            for rule in selected:
                values = rule.copy_data(default={
                    'struct_id': False,
                    # copy_data adds "(copy)" by default. These are the same
                    # statutory rules in another structure, so keep the
                    # canonical user-facing name.
                    'name': rule.name,
                })[0]
                values_by_key[key].append((rule.code, values))
        inputs = template.input_line_type_ids

        def retire(rule):
            """Never delete a salary rule referenced by historical payslip lines."""
            if self.env['hr.payslip.line'].search_count([('salary_rule_id', '=', rule.id)]):
                rule.active = False
            else:
                rule.unlink()

        # Keep XML-owned common/Israeli template rules stable across upgrades,
        # while excluding rules belonging to other employee populations.
        for rule in template.with_context(active_test=False).rule_ids.filtered(
                lambda item: item.code.startswith(('IL_PAL_', 'IL_FOR_'))):
            retire(rule)
        for key, structure in refs.items():
            if key == 'isr_monthly':
                structure.input_line_type_ids = inputs
                continue
            existing_rules = structure.with_context(active_test=False).rule_ids
            desired_codes = {code for code, values in values_by_key[key]}
            for code, values in values_by_key[key]:
                matches = existing_rules.filtered(lambda item: item.code == code)
                values.update({'struct_id': structure.id, 'active': True})
                if matches:
                    matches[:1].write(values)
                    for duplicate in matches[1:]:
                        retire(duplicate)
                else:
                    self.env['hr.salary.rule'].create(values)
            for rule in existing_rules.filtered(lambda item: item.active and item.code not in desired_codes):
                retire(rule)
            structure.input_line_type_ids = inputs
        return True
