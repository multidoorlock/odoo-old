from odoo import fields, models
from odoo.tools.sql import drop_view_if_exists


class L10nIlPayslipReport(models.Model):
    """דוח שכר ישראל: שורה לכל תלוש עם כל הסכומים המרכזיים, לניתוח בציר/רשימה/גרף.

    משמש כבסיס לריכוזי 102 (חודשי), 106 (שנתי לעובד), הפרשות לקרנות ועלות מעסיק.
    הסכומים של ניכויים מוצגים כערכים חיוביים לנוחות הקריאה.
    """
    _name = "l10n.il.payslip.report"
    _description = "דוח שכר - ישראל"
    _auto = False
    _order = "date_from desc, employee_id"

    payslip_id = fields.Many2one("hr.payslip", string="תלוש", readonly=True)
    employee_id = fields.Many2one("hr.employee", string="עובד", readonly=True)
    department_id = fields.Many2one("hr.department", string="מחלקה", readonly=True)
    company_id = fields.Many2one("res.company", string="חברה", readonly=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    pension_fund_id = fields.Many2one("res.partner", string="קרן פנסיה", readonly=True)
    hishtalmut_fund_id = fields.Many2one("res.partner", string="קרן השתלמות", readonly=True)
    date_from = fields.Date(string="מתאריך", readonly=True)
    month = fields.Date(string="חודש", readonly=True)
    year = fields.Integer(string="שנת מס", readonly=True)
    state = fields.Selection(
        selection=[
            ("draft", "טיוטה"),
            ("validated", "מאושר"),
            ("paid", "שולם"),
        ],
        string="סטטוס תלוש", readonly=True,
    )

    basic = fields.Monetary(string="שכר בסיס", readonly=True)
    overtime = fields.Monetary(string="שעות נוספות", readonly=True)
    other_allowances = fields.Monetary(string="תוספות אחרות", readonly=True)
    gross = fields.Monetary(string="ברוטו", readonly=True)
    income_tax = fields.Monetary(string="מס הכנסה", readonly=True)
    nii_employee = fields.Monetary(string="ביטוח לאומי - עובד", readonly=True)
    health_employee = fields.Monetary(string="דמי בריאות", readonly=True)
    pension_employee = fields.Monetary(string="פנסיה - עובד", readonly=True)
    hishtalmut_employee = fields.Monetary(string="קרן השתלמות - עובד", readonly=True)
    other_deductions = fields.Monetary(string="ניכויים אחרים", readonly=True)
    net = fields.Monetary(string="נטו", readonly=True)
    net_to_pay_adjustments = fields.Monetary(
        string="התאמות נטו לתשלום", readonly=True,
        help="תשלומי עובד (מפרעות/הלוואות) והתאמות שכר ששולמו - משפיעים רק על נטו לתשלום, לא על הנטו.")
    net_to_pay = fields.Monetary(string="נטו לתשלום", readonly=True)
    pension_employer = fields.Monetary(string="פנסיה - מעסיק", readonly=True)
    severance_employer = fields.Monetary(string="פיצויים - מעסיק", readonly=True)
    hishtalmut_employer = fields.Monetary(string="קרן השתלמות - מעסיק", readonly=True)
    nii_employer = fields.Monetary(string="ביטוח לאומי - מעסיק", readonly=True)
    employer_cost = fields.Monetary(string="עלות מעסיק כוללת", readonly=True)

    def init(self):
        drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE VIEW {self._table} AS (
                SELECT
                    p.id AS id,
                    p.id AS payslip_id,
                    p.employee_id,
                    p.department_id,
                    p.company_id,
                    p.date_from,
                    (date_trunc('month', p.date_from))::date AS month,
                    (EXTRACT(YEAR FROM p.date_from))::int AS year,
                    p.state,
                    v.l10n_il_pension_fund_id AS pension_fund_id,
                    v.l10n_il_hishtalmut_fund_id AS hishtalmut_fund_id,
                    COALESCE(SUM(l.total) FILTER (WHERE l.code = 'BASIC'), 0) AS basic,
                    COALESCE(SUM(l.total) FILTER (WHERE l.code = 'IL_OT'), 0) AS overtime,
                    COALESCE(SUM(l.total) FILTER (WHERE l.code IN ('IL_COMMISSION', 'IL_TRAVEL', 'IL_HAVRAA', 'IL_OTHER_ADD')), 0) AS other_allowances,
                    COALESCE(SUM(l.total) FILTER (WHERE l.code = 'GROSS'), 0) AS gross,
                    COALESCE(-SUM(l.total) FILTER (WHERE l.code = 'IL_INCTAX'), 0) AS income_tax,
                    COALESCE(-SUM(l.total) FILTER (WHERE l.code = 'IL_NII_EE'), 0) AS nii_employee,
                    COALESCE(-SUM(l.total) FILTER (WHERE l.code = 'IL_HEALTH_EE'), 0) AS health_employee,
                    COALESCE(-SUM(l.total) FILTER (WHERE l.code = 'IL_PENS_EE'), 0) AS pension_employee,
                    COALESCE(-SUM(l.total) FILTER (WHERE l.code = 'IL_HISHT_EE'), 0) AS hishtalmut_employee,
                    COALESCE(-SUM(l.total) FILTER (WHERE l.code IN ('IL_LOAN', 'IL_MEALS', 'IL_OTHER_DED')), 0) AS other_deductions,
                    COALESCE(SUM(l.total) FILTER (WHERE l.code = 'NET'), 0) AS net,
                    COALESCE(-SUM(l.total) FILTER (WHERE l.code IN ('IL_PAYMENT_ADJ', 'IL_SALARY_ADJ_PAID_DED')), 0) AS net_to_pay_adjustments,
                    COALESCE(SUM(l.total) FILTER (WHERE l.code = 'NET_TO_PAY'), 0) AS net_to_pay,
                    COALESCE(SUM(l.total) FILTER (WHERE l.code = 'IL_PENS_ER'), 0) AS pension_employer,
                    COALESCE(SUM(l.total) FILTER (WHERE l.code = 'IL_SEV_ER'), 0) AS severance_employer,
                    COALESCE(SUM(l.total) FILTER (WHERE l.code = 'IL_HISHT_ER'), 0) AS hishtalmut_employer,
                    COALESCE(SUM(l.total) FILTER (WHERE l.code = 'IL_NII_ER'), 0) AS nii_employer,
                    COALESCE(SUM(l.total) FILTER (WHERE l.code = 'GROSS'), 0)
                        + COALESCE(SUM(l.total) FILTER (WHERE l.code IN ('IL_PENS_ER', 'IL_SEV_ER', 'IL_HISHT_ER', 'IL_NII_ER')), 0) AS employer_cost
                FROM hr_payslip p
                JOIN hr_payroll_structure s ON s.id = p.struct_id
                JOIN res_country c ON c.id = s.country_id AND c.code = 'IL'
                LEFT JOIN hr_version v ON v.id = p.version_id
                JOIN hr_payslip_line l ON l.slip_id = p.id
                WHERE p.state != 'cancel'
                GROUP BY
                    p.id, p.employee_id, p.department_id, p.company_id, p.date_from,
                    p.state, v.l10n_il_pension_fund_id, v.l10n_il_hishtalmut_fund_id
            )
        """)
