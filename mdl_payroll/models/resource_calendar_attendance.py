from odoo import api, fields, models
from odoo.tools import float_compare

MDL_DAILY_UNIT_FACTORS = {
    'half_day': 0.5,
    'one_day': 1.0,
    'one_and_half_days': 1.5,
    'two_days': 2.0,
    'two_and_half_days': 2.5,
    'three_days': 3.0,
}


class ResourceCalendarAttendance(models.Model):
    _inherit = 'resource.calendar.attendance'

    mdl_day_input_method = fields.Selection([
        ('daily_units', 'לפי יחידות יום'),
        ('hours', 'לפי שעות'),
    ], string='אופן הזנה', default='daily_units')
    mdl_daily_units = fields.Selection([
        ('half_day', 'חצי יחידת יום'),
        ('one_day', 'יחידת יום אחת'),
        ('one_and_half_days', 'יחידת יום וחצי'),
        ('two_days', 'שתי יחידות יום'),
        ('two_and_half_days', 'שתי יחידות יום וחצי'),
        ('three_days', 'שלוש יחידות יום'),
    ], string='מספר יחידות יום', default='one_day')

    def _mdl_uses_daily_units(self):
        self.ensure_one()
        calendar = self.calendar_id
        return (
            calendar.mdl_schedule_type == 'attendance'
            and calendar.mdl_schedule_frequency == 'daily_duration'
            and self.day_period != 'lunch'
            and not self.display_type
            and self.mdl_day_input_method == 'daily_units'
            and self.mdl_daily_units
        )

    def _mdl_apply_daily_units(self):
        for line in self:
            if not line._mdl_uses_daily_units():
                continue
            target = (
                line.calendar_id.hours_per_day
                * MDL_DAILY_UNIT_FACTORS[line.mdl_daily_units]
            )
            if float_compare(line.duration_hours, target, precision_digits=2):
                line.with_context(mdl_skip_daily_units=True).write({
                    'duration_hours': target,
                    'day_period': 'full_day',
                })

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        if not self.env.context.get('mdl_skip_daily_units'):
            lines._mdl_apply_daily_units()
        return lines

    def write(self, vals):
        res = super().write(vals)
        if (not self.env.context.get('mdl_skip_daily_units')
                and {'mdl_day_input_method', 'mdl_daily_units', 'duration_hours', 'day_period'} & vals.keys()):
            self._mdl_apply_daily_units()
        return res

    @api.onchange('mdl_day_input_method', 'mdl_daily_units')
    def _onchange_mdl_daily_units(self):
        if (self.mdl_day_input_method == 'daily_units' and self.mdl_daily_units
                and self.day_period != 'lunch'):
            self.day_period = 'full_day'
            self.duration_hours = (
                self.calendar_id.hours_per_day
                * MDL_DAILY_UNIT_FACTORS[self.mdl_daily_units]
            )
