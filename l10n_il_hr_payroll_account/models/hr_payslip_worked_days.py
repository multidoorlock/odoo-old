from odoo import api, models


class HrPayslipWorkedDays(models.Model):
    _inherit = 'hr.payslip.worked_days'

    @api.depends(
        'is_paid', 'number_of_hours', 'payslip_id',
        'version_id.wage', 'version_id.hourly_wage',
        'version_id.mdl_wage_type', 'version_id.mdl_wage_rate_type',
        'version_id.mdl_additional_day_wage',
        'version_id.resource_calendar_id.hours_per_day',
        'version_id.resource_calendar_id.mdl_schedule_type',
        'version_id.company_id.mdl_shift_morning_hours',
        'payslip_id.sum_worked_hours',
        'work_entry_type_id.amount_rate',
        'work_entry_type_id.is_extra_hours',
    )
    def _compute_amount(self):
        super()._compute_amount()
        for worked_days in self:
            version = worked_days.version_id
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
