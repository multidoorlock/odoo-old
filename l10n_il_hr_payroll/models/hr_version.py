from decimal import Decimal, ROUND_HALF_UP

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare

PAYROLL_GROUP = "hr_payroll.group_hr_payroll_user"
HOURLY_RATE_QUANTUM = Decimal('0.0000000001')


def _decimal(value):
    """Build a Decimal from Odoo values without a binary-float calculation."""
    return Decimal(str(value or 0))


class HrVersion(models.Model):
    _inherit = 'hr.version'

    # ------------------------------------------------------------------
    # שדות שכבת הממשק (סעיפים 4–5, 8 באפיון)
    # ------------------------------------------------------------------

    mdl_wage_type = fields.Selection([
        ('mdl_monthly', 'חודשי'),
        ('mdl_daily', 'יומי'),
    ], string='סוג שכר מותאם', required=True, default='mdl_monthly',
        groups=PAYROLL_GROUP, tracking=True)
    mdl_wage_rate_type = fields.Selection([
        ('gross', 'ברוטו'),
        ('net', 'נטו'),
    ], string='הזנת שכר לפי', required=True, default='gross',
        groups=PAYROLL_GROUP, tracking=True,
        help='קובע אם התעריפים המוזנים הם ברוטו או יעד נטו לגילום בתלוש.')
    mdl_monthly_wage = fields.Monetary(
        related='wage', readonly=False, string='שכר חודשי', groups=PAYROLL_GROUP)
    mdl_daily_wage = fields.Monetary(
        string='שכר יומי מותאם', compute='_compute_mdl_daily_wage', store=True,
        readonly=False, copy=True, groups=PAYROLL_GROUP, tracking=True)
    mdl_hourly_wage = fields.Monetary(
        related='hourly_wage', string='תעריף שעה', groups=PAYROLL_GROUP)
    mdl_hourly_wage_exact = fields.Float(
        string='תעריף שעה מדויק', digits=(32, 10),
        compute='_compute_mdl_hourly_wage', store=True, readonly=True,
        groups=PAYROLL_GROUP,
        help='תעריף פנימי לחישובי שכר. נשמר כ-NUMERIC בדיוק של 10 ספרות; '
             'התעריף המוצג לעובד נשאר מעוגל לפי דיוק המטבע.')
    mdl_average_monthly_hours = fields.Float(
        string='ממוצע שעות בחודש', compute='_compute_mdl_average_monthly_hours',
        groups=PAYROLL_GROUP)
    mdl_standard_day_hours = fields.Float(
        related='resource_calendar_id.hours_per_day', string='שעות ביחידת יום',
        groups=PAYROLL_GROUP)

    mdl_additional_day_wage = fields.Monetary(
        string='תעריף יום נוסף מותאם', groups=PAYROLL_GROUP, tracking=True)
    mdl_additional_day_hourly_wage = fields.Monetary(
        string='תעריף שעה ליום נוסף', compute='_compute_mdl_additional_day_hourly_wage',
        groups=PAYROLL_GROUP)

    mdl_resource_calendar_type = fields.Selection(
        related='resource_calendar_id.mdl_schedule_type', string='סוג לוח עבודה')

    # ------------------------------------------------------------------
    # סנכרון שדות הליבה של Odoo (סעיף 4.3 באפיון)
    # ------------------------------------------------------------------

    wage = fields.Monetary(compute='_compute_mdl_wage', store=True, readonly=False)
    hourly_wage = fields.Monetary(
        compute='_compute_mdl_hourly_wage', store=True, readonly=False)

    @api.depends('mdl_wage_type')
    def _compute_wage_type(self):
        super()._compute_wage_type()
        for version in self:
            if version.mdl_wage_type == 'mdl_daily':
                version.wage_type = 'hourly'
            elif version.mdl_wage_type == 'mdl_monthly':
                version.wage_type = 'monthly'

    @api.depends('mdl_wage_type')
    def _compute_mdl_wage(self):
        for version in self:
            # לעובד יומי wage נשאר אפס; לעובד חודשי הערך מוזן דרך "שכר חודשי".
            version.wage = 0.0 if version.mdl_wage_type == 'mdl_daily' else version.wage

    @api.depends('mdl_wage_type', 'mdl_daily_wage', 'wage',
                 'resource_calendar_id.hours_per_day', 'resource_calendar_id.hours_per_week',
                 'resource_calendar_id.mdl_schedule_type',
                 'company_id.mdl_shift_morning_hours')
    def _compute_mdl_hourly_wage(self):
        for version in self:
            if version.mdl_wage_type == 'mdl_daily':
                std_hours = (
                    version.company_id.mdl_shift_morning_hours
                    if version.resource_calendar_id.mdl_schedule_type == 'shifts'
                    else version.resource_calendar_id.hours_per_day
                )
                exact_rate = (
                    _decimal(version.mdl_daily_wage) / _decimal(std_hours)
                    if std_hours else Decimal('0')
                )
            else:
                weekly_hours = _decimal(version.resource_calendar_id.hours_per_week)
                avg_hours = weekly_hours * Decimal(52) / Decimal(12) if weekly_hours else Decimal('0')
                exact_rate = (
                    _decimal(version.wage) / avg_hours
                    if avg_hours else Decimal('0')
                )
            exact_rate = exact_rate.quantize(HOURLY_RATE_QUANTUM, rounding=ROUND_HALF_UP)
            version.mdl_hourly_wage_exact = exact_rate
            # Odoo's standard Monetary field remains the legally displayed,
            # currency-rounded hourly rate. Payroll calculations use the exact
            # NUMERIC field above through the localization helpers.
            version.hourly_wage = exact_rate

    @api.depends('resource_calendar_id.hours_per_week')
    def _compute_mdl_average_monthly_hours(self):
        for version in self:
            version.mdl_average_monthly_hours = (
                version.resource_calendar_id.hours_per_week * 52 / 12)

    @api.depends('mdl_wage_type', 'wage',
                 'resource_calendar_id.hours_per_day', 'resource_calendar_id.hours_per_week')
    def _compute_mdl_daily_wage(self):
        for version in self:
            if version.mdl_wage_type == 'mdl_daily':
                # ערך שמוזן על ידי המשתמש — אין לדרוס.
                version.mdl_daily_wage = version.mdl_daily_wage
            else:
                avg_hours = version.mdl_average_monthly_hours
                std_hours = version.resource_calendar_id.hours_per_day
                version.mdl_daily_wage = (
                    version.wage * std_hours / avg_hours if avg_hours else 0.0)

    @api.depends(
        'mdl_additional_day_wage', 'resource_calendar_id.hours_per_day',
        'resource_calendar_id.mdl_schedule_type',
        'company_id.mdl_shift_morning_hours')
    def _compute_mdl_additional_day_hourly_wage(self):
        for version in self:
            std_hours = (
                version.company_id.mdl_shift_morning_hours
                if version.resource_calendar_id.mdl_schedule_type == 'shifts'
                else version.resource_calendar_id.hours_per_day
            )
            version.mdl_additional_day_hourly_wage = (
                version.mdl_additional_day_wage / std_hours if std_hours else 0.0)

    @api.model
    def _get_whitelist_fields_from_template(self):
        return super()._get_whitelist_fields_from_template() + [
            'mdl_wage_type', 'mdl_wage_rate_type', 'mdl_daily_wage',
            'mdl_additional_day_wage',
        ]

    # ------------------------------------------------------------------
    # ולידציות (סעיף 35 באפיון)
    # ------------------------------------------------------------------

    @api.constrains('mdl_wage_type', 'mdl_wage_rate_type', 'mdl_daily_wage',
                    'resource_calendar_id')
    def _check_mdl_daily_wage(self):
        for version in self:
            if version.mdl_wage_type != 'mdl_daily':
                continue
            if float_compare(version.mdl_daily_wage, 0.0, precision_digits=2) <= 0:
                raise ValidationError('לעובד יומי חובה להזין שכר יומי גדול מאפס.')
            if float_compare(version.resource_calendar_id.hours_per_day, 0.0, precision_digits=2) <= 0:
                raise ValidationError(
                    'לעובד יומי חובה לוח עבודה עם שעות ביחידת יום גדולות מאפס.')

    @api.constrains('mdl_additional_day_wage')
    def _check_mdl_additional_day_wage(self):
        for version in self:
            if float_compare(
                    version.mdl_additional_day_wage, 0.0, precision_digits=2) < 0:
                raise ValidationError('תעריף יום נוסף אינו יכול להיות שלילי.')
