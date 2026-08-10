from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare

PAYROLL_GROUP = "hr_payroll.group_hr_payroll_user"


class HrVersion(models.Model):
    _inherit = 'hr.version'

    # ------------------------------------------------------------------
    # שדות שכבת הממשק (סעיפים 4–5, 8 באפיון)
    # ------------------------------------------------------------------

    mdl_wage_type = fields.Selection([
        ('mdl_monthly', 'חודשי'),
        ('mdl_daily', 'יומי'),
    ], string='סוג שכר', required=True, default='mdl_monthly',
        groups=PAYROLL_GROUP, tracking=True)
    mdl_monthly_wage = fields.Monetary(
        related='wage', readonly=False, string='שכר חודשי', groups=PAYROLL_GROUP)
    mdl_daily_wage = fields.Monetary(
        string='שכר יומי', compute='_compute_mdl_daily_wage', store=True,
        readonly=False, copy=True, groups=PAYROLL_GROUP, tracking=True)
    mdl_hourly_wage = fields.Monetary(
        related='hourly_wage', string='תעריף שעה', groups=PAYROLL_GROUP)

    mdl_average_monthly_hours = fields.Float(
        string='ממוצע שעות בחודש', compute='_compute_mdl_average_monthly_hours',
        groups=PAYROLL_GROUP)
    mdl_standard_day_hours = fields.Float(
        related='resource_calendar_id.hours_per_day', string='שעות ביחידת יום',
        groups=PAYROLL_GROUP)

    mdl_additional_day_wage = fields.Monetary(
        string='תעריף יום נוסף', groups=PAYROLL_GROUP, tracking=True)
    mdl_additional_day_rate_type = fields.Selection([
        ('gross', 'ברוטו'),
        ('net', 'נטו'),
    ], string='סוג תעריף יום נוסף', groups=PAYROLL_GROUP)
    mdl_weekend_wage = fields.Monetary(
        string='תעריף סוף שבוע', groups=PAYROLL_GROUP, tracking=True)
    mdl_weekend_rate_type = fields.Selection([
        ('gross', 'ברוטו'),
        ('net', 'נטו'),
    ], string='סוג תעריף סוף שבוע', groups=PAYROLL_GROUP)

    mdl_additional_day_hourly_wage = fields.Monetary(
        string='תעריף שעה ליום נוסף', compute='_compute_mdl_special_hourly_wages',
        groups=PAYROLL_GROUP)
    mdl_weekend_hourly_wage = fields.Monetary(
        string='תעריף שעה לסוף שבוע', compute='_compute_mdl_special_hourly_wages',
        groups=PAYROLL_GROUP)

    mdl_overtime_wage_type = fields.Selection([
        ('fixed', 'סכום קבוע'),
        ('percentage', 'אחוז מתעריף שעה'),
    ], string='אופן חישוב שעות נוספות', groups=PAYROLL_GROUP, tracking=True)
    mdl_overtime_fixed_wage = fields.Monetary(
        string='תשלום לשעה נוספת', groups=PAYROLL_GROUP)
    mdl_overtime_percentage = fields.Float(
        string='אחוז מתעריף שעה', groups=PAYROLL_GROUP)

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
                 'resource_calendar_id.hours_per_day', 'resource_calendar_id.hours_per_week')
    def _compute_mdl_hourly_wage(self):
        for version in self:
            if version.mdl_wage_type == 'mdl_daily':
                std_hours = version.resource_calendar_id.hours_per_day
                version.hourly_wage = version.mdl_daily_wage / std_hours if std_hours else 0.0
            else:
                avg_hours = version.mdl_average_monthly_hours
                version.hourly_wage = version.wage / avg_hours if avg_hours else 0.0

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

    @api.depends('mdl_additional_day_wage', 'mdl_weekend_wage',
                 'resource_calendar_id.hours_per_day')
    def _compute_mdl_special_hourly_wages(self):
        for version in self:
            std_hours = version.resource_calendar_id.hours_per_day
            version.mdl_additional_day_hourly_wage = (
                version.mdl_additional_day_wage / std_hours if std_hours else 0.0)
            version.mdl_weekend_hourly_wage = (
                version.mdl_weekend_wage / std_hours if std_hours else 0.0)

    @api.model
    def _get_whitelist_fields_from_template(self):
        return super()._get_whitelist_fields_from_template() + [
            'mdl_wage_type', 'mdl_daily_wage',
            'mdl_additional_day_wage', 'mdl_additional_day_rate_type',
            'mdl_weekend_wage', 'mdl_weekend_rate_type',
            'mdl_overtime_wage_type', 'mdl_overtime_fixed_wage', 'mdl_overtime_percentage',
        ]

    # ------------------------------------------------------------------
    # ולידציות (סעיף 35 באפיון)
    # ------------------------------------------------------------------

    @api.constrains('mdl_wage_type', 'mdl_daily_wage', 'resource_calendar_id')
    def _check_mdl_daily_wage(self):
        for version in self:
            if version.mdl_wage_type != 'mdl_daily':
                continue
            if float_compare(version.mdl_daily_wage, 0.0, precision_digits=2) <= 0:
                raise ValidationError('לעובד יומי חובה להזין שכר יומי גדול מאפס.')
            if float_compare(version.resource_calendar_id.hours_per_day, 0.0, precision_digits=2) <= 0:
                raise ValidationError(
                    'לעובד יומי חובה לוח עבודה עם שעות ביחידת יום גדולות מאפס.')

    @api.constrains('mdl_weekend_wage', 'mdl_weekend_rate_type',
                    'mdl_additional_day_wage', 'mdl_additional_day_rate_type')
    def _check_mdl_rate_types(self):
        for version in self:
            if (float_compare(version.mdl_weekend_wage, 0.0, precision_digits=2) > 0
                    and not version.mdl_weekend_rate_type):
                raise ValidationError('הוגדר תעריף סוף שבוע — חובה לבחור סוג תעריף (ברוטו/נטו).')
            if (float_compare(version.mdl_additional_day_wage, 0.0, precision_digits=2) > 0
                    and not version.mdl_additional_day_rate_type):
                raise ValidationError('הוגדר תעריף יום נוסף — חובה לבחור סוג תעריף (ברוטו/נטו).')

    @api.constrains('mdl_overtime_wage_type', 'mdl_overtime_fixed_wage', 'mdl_overtime_percentage')
    def _check_mdl_overtime(self):
        for version in self:
            if (version.mdl_overtime_wage_type == 'fixed'
                    and float_compare(version.mdl_overtime_fixed_wage, 0.0, precision_digits=2) <= 0):
                raise ValidationError('בחישוב שעות נוספות בסכום קבוע חובה להזין תשלום לשעה נוספת.')
            if (version.mdl_overtime_wage_type == 'percentage'
                    and float_compare(version.mdl_overtime_percentage, 0.0, precision_digits=2) <= 0):
                raise ValidationError('בחישוב שעות נוספות באחוזים חובה להזין אחוז גדול מאפס.')
