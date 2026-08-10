from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    l10n_il_employee_category = fields.Selection(readonly=False, related="version_id.l10n_il_employee_category", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_il_tax_residency = fields.Selection(readonly=False, related="version_id.l10n_il_tax_residency", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_il_credit_points = fields.Float(readonly=False, related="version_id.l10n_il_credit_points", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_il_main_employer = fields.Boolean(readonly=False, related="version_id.l10n_il_main_employer", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_il_form101_state = fields.Selection(
        selection=[
            ("missing", "חסר"),
            ("draft", "טיוטה"),
            ("sent", "נשלח"),
            ("signed", "נחתם"),
            ("applied", "פעיל"),
            ("expired", "פג תוקף"),
        ],
        string="סטטוס טופס 101",
        compute="_compute_l10n_il_form101_state", store=True,
        groups="hr_payroll.group_hr_payroll_user",
        help="מחושב אוטומטית מטופסי ה-101 של העובד: תמיד מוצג המצב הטוב ביותר הקיים "
             "(פעיל > נחתם > נשלח > טיוטה > פג תוקף > חסר).",
    )
    l10n_il_tax_coordination = fields.Boolean(readonly=False, related="version_id.l10n_il_tax_coordination", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_il_tax_coordination_rate = fields.Float(readonly=False, related="version_id.l10n_il_tax_coordination_rate", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_il_tax_coordination_expiry = fields.Date(readonly=False, related="version_id.l10n_il_tax_coordination_expiry", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_il_settlement_code = fields.Char(readonly=False, related="version_id.l10n_il_settlement_code", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_il_pension_fund_id = fields.Many2one(readonly=False, related="version_id.l10n_il_pension_fund_id", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_il_pension_member_no = fields.Char(readonly=False, related="version_id.l10n_il_pension_member_no", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_il_pension_employee_rate = fields.Float(readonly=False, related="version_id.l10n_il_pension_employee_rate", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_il_pension_employer_rate = fields.Float(readonly=False, related="version_id.l10n_il_pension_employer_rate", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_il_severance_rate = fields.Float(readonly=False, related="version_id.l10n_il_severance_rate", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_il_section14 = fields.Boolean(readonly=False, related="version_id.l10n_il_section14", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_il_hishtalmut = fields.Boolean(readonly=False, related="version_id.l10n_il_hishtalmut", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_il_hishtalmut_fund_id = fields.Many2one(readonly=False, related="version_id.l10n_il_hishtalmut_fund_id", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_il_hishtalmut_employee_rate = fields.Float(readonly=False, related="version_id.l10n_il_hishtalmut_employee_rate", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_il_hishtalmut_employer_rate = fields.Float(readonly=False, related="version_id.l10n_il_hishtalmut_employer_rate", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_il_aliyah_date = fields.Date(readonly=False, related="version_id.l10n_il_aliyah_date", inherited=True, groups="hr.group_hr_user")
    l10n_il_spouse_id = fields.Char(readonly=False, related="version_id.l10n_il_spouse_id", inherited=True, groups="hr.group_hr_user")
    l10n_il_kupat_holim = fields.Selection(readonly=False, related="version_id.l10n_il_kupat_holim", inherited=True, groups="hr.group_hr_user")
    l10n_il_citizenship_code = fields.Char(
        related="country_id.code", string="קוד אזרחות",
        help="שדה טכני לקביעת נראות תאריך העלייה: רלוונטי רק כשהאזרחות אינה ישראל.")
    l10n_il_child_ids = fields.One2many(
        "l10n.il.employee.child", "employee_id",
        string="ילדים",
        groups="hr.group_hr_user",
    )
    l10n_il_form101_ids = fields.One2many(
        "l10n.il.form101", "employee_id",
        string="טופסי 101",
        groups="hr_payroll.group_hr_payroll_user",
    )
    l10n_il_form101_count = fields.Integer(
        compute="_compute_l10n_il_form101_count",
        groups="hr_payroll.group_hr_payroll_user",
    )
    l10n_il_daily_wage = fields.Monetary(readonly=False, related="version_id.l10n_il_daily_wage", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_il_weekend_daily_wage = fields.Monetary(readonly=False, related="version_id.l10n_il_weekend_daily_wage", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_il_computed_daily_wage = fields.Monetary(related="version_id.l10n_il_computed_daily_wage", groups="hr_payroll.group_hr_payroll_user")
    l10n_il_computed_weekly_wage = fields.Monetary(related="version_id.l10n_il_computed_weekly_wage", groups="hr_payroll.group_hr_payroll_user")
    l10n_il_computed_monthly_wage = fields.Monetary(related="version_id.l10n_il_computed_monthly_wage", groups="hr_payroll.group_hr_payroll_user")
    l10n_il_extra_day_rate = fields.Monetary(readonly=False, related="version_id.l10n_il_extra_day_rate", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_il_overtime_payment_type = fields.Selection(readonly=False, related="version_id.l10n_il_overtime_payment_type", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_il_overtime_percentage = fields.Float(readonly=False, related="version_id.l10n_il_overtime_percentage", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_il_overtime_fixed_rate = fields.Monetary(readonly=False, related="version_id.l10n_il_overtime_fixed_rate", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_il_computed_overtime_hour_rate = fields.Monetary(related="version_id.l10n_il_computed_overtime_hour_rate", groups="hr_payroll.group_hr_payroll_user")

    def _compute_l10n_il_form101_count(self):
        for employee in self:
            employee.l10n_il_form101_count = len(employee.l10n_il_form101_ids)

    @api.depends("l10n_il_form101_ids.state")
    def _compute_l10n_il_form101_state(self):
        # תמיד המצב הטוב ביותר מבין הטפסים הקיימים
        order = ["applied", "signed", "sent", "draft", "expired"]
        for employee in self:
            states = set(employee.l10n_il_form101_ids.mapped("state"))
            employee.l10n_il_form101_state = next((s for s in order if s in states), "missing")
