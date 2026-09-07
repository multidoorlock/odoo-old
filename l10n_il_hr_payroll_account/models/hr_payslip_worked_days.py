from decimal import Decimal, ROUND_HALF_UP

from odoo import api, fields, models


class HrPayslipWorkedDays(models.Model):
    _inherit = 'hr.payslip.worked_days'

    daily_wage = fields.Float(
        string='שכר יומי',
        compute='_compute_daily_wage',
    )

    @api.depends('amount', 'number_of_days')
    def _compute_daily_wage(self):
        for line in self:
            line.daily_wage = (
                line.amount / line.number_of_days
                if line.number_of_days
                else 0.0
            )

    @api.depends(
        'is_paid', 'number_of_hours', 'payslip_id',
        'version_id.wage', 'version_id.hourly_wage',
        'version_id.mdl_daily_wage',
        'version_id.mdl_wage_type', 'version_id.mdl_wage_rate_type',
        'version_id.mdl_additional_day_wage',
        'version_id.resource_calendar_id.hours_per_day',
        'version_id.resource_calendar_id.mdl_schedule_type',
        'version_id.company_id.mdl_shift_morning_hours',
        'payslip_id.sum_worked_hours',
        'payslip_id.currency_id.rounding',
        'work_entry_type_id.amount_rate',
        'work_entry_type_id.is_extra_hours',
    )
    def _compute_amount(self):
        super()._compute_amount()
        for worked_days in self:
            version = worked_days.version_id
            if (worked_days.code in ('WORK100', 'ADDITIONAL_DAY')
                    and version
                    and version.mdl_wage_type == 'mdl_daily'
                    and version.mdl_wage_rate_type == 'gross'):
                hours_per_day = (
                    version.company_id.mdl_shift_morning_hours
                    if version.resource_calendar_id.mdl_schedule_type == 'shifts'
                    else version.resource_calendar_id.hours_per_day
                )
                if worked_days.is_paid and hours_per_day:
                    exact_rate = (
                        Decimal(str(version.mdl_daily_wage or 0.0))
                        / Decimal(str(hours_per_day))
                    )
                    amount = Decimal(str(worked_days.number_of_hours or 0.0)) * exact_rate
                    currency = (
                        worked_days.payslip_id.currency_id
                        or version.company_id.currency_id
                    )
                    increment = Decimal(str(currency.rounding or 0.01))
                    worked_days.amount = float(
                        (amount / increment).quantize(
                            Decimal('1'), rounding=ROUND_HALF_UP
                        ) * increment
                    )
                else:
                    worked_days.amount = 0.0
                continue
            if (worked_days.code != 'ADDITIONAL_DAY'
                    or not version
                    or version.mdl_wage_type != 'mdl_monthly'
                    or version.mdl_wage_rate_type != 'gross'):
                continue
            hours_per_day = (
                version.company_id.mdl_shift_morning_hours
                if version.resource_calendar_id.mdl_schedule_type == 'shifts'
                else version.resource_calendar_id.hours_per_day
            )
            worked_days.amount = (
                worked_days.number_of_hours / hours_per_day
                * version.mdl_additional_day_wage
                if worked_days.is_paid and hours_per_day else 0.0
            )
