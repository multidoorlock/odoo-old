from odoo import Command, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare, float_round

# (boolean field, Odoo dayofweek code, label) — display order Sunday first (Israel).
MDL_SHIFT_DAY_FIELDS = [
    ('mdl_shift_day_sunday', '6', 'ראשון'),
    ('mdl_shift_day_monday', '0', 'שני'),
    ('mdl_shift_day_tuesday', '1', 'שלישי'),
    ('mdl_shift_day_wednesday', '2', 'רביעי'),
    ('mdl_shift_day_thursday', '3', 'חמישי'),
    ('mdl_shift_day_friday', '4', 'שישי'),
    ('mdl_shift_day_saturday', '5', 'שבת'),
]

MDL_SCHEDULE_TRIGGER_FIELDS = (
    {'mdl_schedule_type', 'mdl_schedule_frequency', 'mdl_shifts_per_week'}
    | {field_name for field_name, _dow, _label in MDL_SHIFT_DAY_FIELDS}
)


class ResourceCalendar(models.Model):
    _inherit = 'resource.calendar'

    mdl_schedule_type = fields.Selection([
        ('attendance', 'נוכחות'),
        ('shifts', 'משמרות'),
    ], string='סוג לוח עבודה', required=True, default='attendance')
    mdl_schedule_frequency = fields.Selection([
        ('fixed_intervals', 'שעות קבועות'),
        ('daily_duration', 'מכסה יומית'),
        ('weekly_quota', 'מכסה שבועית'),
    ], string='שיטת שיבוץ', required=True, default='fixed_intervals')
    # בלוח שעות קבועות הערך נמשך בזמן אמת מהשעות שהוגדרו בשורות הלוח,
    # וניתן לדריסה ידנית; במכסה יומית/שבועית הערך מוזן ידנית בלבד.
    mdl_hours_per_day = fields.Float(
        string='שעות ביחידת יום',
        compute='_compute_mdl_hours_per_day', store=True, readonly=False)
    mdl_shifts_per_week = fields.Integer(string='מספר משמרות בשבוע', default=5)

    mdl_shift_day_sunday = fields.Boolean(string='ראשון')
    mdl_shift_day_monday = fields.Boolean(string='שני')
    mdl_shift_day_tuesday = fields.Boolean(string='שלישי')
    mdl_shift_day_wednesday = fields.Boolean(string='רביעי')
    mdl_shift_day_thursday = fields.Boolean(string='חמישי')
    mdl_shift_day_friday = fields.Boolean(string='שישי')
    mdl_shift_day_saturday = fields.Boolean(string='שבת')

    # schedule_type and duration_based intentionally remain Odoo's native
    # fields. The MDL selections are a UI layer which writes native values.

    @api.model
    def _mdl_native_schedule_values(self, frequency):
        return {
            'schedule_type': 'flexible' if frequency == 'weekly_quota' else 'fully_fixed',
            'duration_based': frequency == 'daily_duration',
        }

    def _mdl_company(self):
        self.ensure_one()
        return self.company_id or self.env.company

    @api.depends('mdl_schedule_type', 'mdl_schedule_frequency', 'two_weeks_calendar',
                 'attendance_ids', 'attendance_ids.hour_from', 'attendance_ids.hour_to',
                 'attendance_ids.duration_hours', 'attendance_ids.day_period')
    def _compute_mdl_hours_per_day(self):
        for calendar in self:
            if (calendar.mdl_schedule_type == 'attendance'
                    and calendar.mdl_schedule_frequency == 'fixed_intervals'):
                calendar.mdl_hours_per_day = float_round(
                    calendar._get_hours_per_day(), precision_digits=2)
            else:
                # מכסה יומית/שבועית — ערך ידני, אין לדרוס.
                calendar.mdl_hours_per_day = calendar.mdl_hours_per_day

    @api.depends(
        'mdl_schedule_type', 'mdl_hours_per_day',
        'company_id.mdl_shift_morning_hours')
    def _compute_hours_per_day(self):
        # "שעות ביחידת יום" הוא מקור האמת בכל לוחות הנוכחות; בלוחות משמרות —
        # שעות המשמרת בתשלום מהגדרות החברה.
        shift_calendars = self.filtered(lambda c: c.mdl_schedule_type == 'shifts')
        attendance_calendars = self.filtered(lambda c: c.mdl_schedule_type == 'attendance')
        for calendar in shift_calendars:
            calendar.hours_per_day = calendar._mdl_company().mdl_shift_morning_hours
        for calendar in attendance_calendars:
            calendar.hours_per_day = calendar.mdl_hours_per_day
        super(ResourceCalendar, self - shift_calendars - attendance_calendars)._compute_hours_per_day()

    @api.depends(
        'mdl_schedule_type', 'mdl_schedule_frequency', 'mdl_shifts_per_week',
        'company_id.mdl_shift_morning_hours')
    def _compute_hours_per_week(self):
        shift_weekly = self.filtered(
            lambda c: c.mdl_schedule_type == 'shifts'
            and c.mdl_schedule_frequency == 'weekly_quota')
        for calendar in shift_weekly:
            calendar.hours_per_week = (
                calendar.mdl_shifts_per_week
                * calendar._mdl_company().mdl_shift_morning_hours)
        super(ResourceCalendar, self - shift_weekly)._compute_hours_per_week()

    def _mdl_sync_shift_attendance_lines(self):
        """Rebuild the attendance lines of a 'shifts + daily quota' calendar
        from the selected shift-day checkboxes (one full-shift line per day)."""
        for calendar in self:
            if calendar.mdl_schedule_type != 'shifts' or calendar.mdl_schedule_frequency != 'daily_duration':
                continue
            paid_hours = calendar._mdl_company().mdl_shift_morning_hours
            commands = [Command.clear()]
            for field_name, dayofweek, label in MDL_SHIFT_DAY_FIELDS:
                if calendar[field_name]:
                    commands.append(Command.create({
                        'name': 'משמרת %s' % label,
                        'dayofweek': dayofweek,
                        'day_period': 'full_day',
                        'duration_hours': paid_hours,
                        'mdl_day_input_method': 'hours',
                    }))
            calendar.with_context(mdl_skip_shift_line_sync=True).attendance_ids = commands

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # בלוח משמרות או מכסה יומית אין להזרים את שורות ברירת המחדל
            # הסטנדרטיות (הכוללות הפסקת צהריים שאסורה בלוח מבוסס־משך).
            schedule_type = vals.get('mdl_schedule_type', 'attendance')
            frequency = vals.get('mdl_schedule_frequency', 'fixed_intervals')
            vals.update(self._mdl_native_schedule_values(frequency))
            if frequency == 'daily_duration' and vals.get('attendance_ids'):
                # Odoo forbids break lines on a duration-based calendar. Keep
                # all real work rows supplied by the form/copy and discard only
                # CREATE commands representing a lunch break. Rows copied from
                # a fixed calendar keep their actual duration instead of being
                # reinterpreted as a whole daily unit by the MDL input helper.
                attendance_commands = []
                for command in vals['attendance_ids']:
                    if command[0] == Command.CREATE:
                        line_values = dict(command[2])
                        if line_values.get('day_period') == 'lunch':
                            continue
                        line_values['mdl_day_input_method'] = 'hours'
                        command = Command.create(line_values)
                    attendance_commands.append(command)
                vals['attendance_ids'] = attendance_commands
            if (schedule_type == 'shifts' or frequency == 'daily_duration') \
                    and 'attendance_ids' not in vals:
                vals['attendance_ids'] = []
        calendars = super().create(vals_list)
        calendars._mdl_sync_shift_attendance_lines()
        return calendars

    def write(self, vals):
        vals = dict(vals)
        old_duration_based = {
            calendar.id: calendar.duration_based for calendar in self
        }
        if 'mdl_schedule_frequency' in vals:
            vals.update(self._mdl_native_schedule_values(
                vals['mdl_schedule_frequency']
            ))
        res = super().write(vals)
        if 'mdl_schedule_frequency' in vals:
            frequency = vals['mdl_schedule_frequency']
            if frequency == 'daily_duration':
                self.filtered(
                    lambda calendar: not old_duration_based.get(calendar.id)
                    and calendar.duration_based
                ).attendance_ids.filtered(
                    lambda line: line.day_period == 'lunch'
                ).unlink()
            elif frequency == 'fixed_intervals':
                for calendar in self.filtered(
                        lambda item: old_duration_based.get(item.id)
                        and not item.duration_based
                        and item.mdl_schedule_type == 'attendance'):
                    # This is the same conversion used by Odoo's native
                    # switch_based_on_duration() when returning to fixed hours.
                    calendar.attendance_ids.unlink()
                    calendar.attendance_ids = calendar._get_default_attendance_ids(
                        calendar.company_id
                    )
                    if calendar.two_weeks_calendar:
                        calendar.attendance_ids = calendar._get_two_weeks_attendance()
        if (MDL_SCHEDULE_TRIGGER_FIELDS & vals.keys()
                and not self.env.context.get('mdl_skip_shift_line_sync')):
            # במעבר למכסה יומית יש להסיר שורות הפסקה — כמו במנגנון הסטנדרטי
            # (switch_based_on_duration).
            self.filtered(
                lambda c: c.mdl_schedule_frequency == 'daily_duration'
            ).attendance_ids.filtered(lambda line: line.day_period == 'lunch').unlink()
            self._mdl_sync_shift_attendance_lines()
        return res

    @api.onchange('mdl_schedule_type', 'mdl_schedule_frequency')
    def _onchange_mdl_schedule_type(self):
        # משמרות + שעות קבועות אינו שילוב חוקי (סעיף 11 באפיון).
        if self.mdl_schedule_type == 'shifts' and self.mdl_schedule_frequency == 'fixed_intervals':
            self.mdl_schedule_frequency = 'daily_duration'
        # Update the real Odoo fields in the unsaved form as well. The list
        # view modifiers use parent.duration_based and react immediately.
        self.update(self._mdl_native_schedule_values(
            self.mdl_schedule_frequency
        ))

    @api.constrains('mdl_schedule_type', 'mdl_schedule_frequency',
                    'hours_per_week', 'hours_per_day')
    def _check_mdl_schedule(self):
        for calendar in self:
            if calendar.mdl_schedule_type == 'shifts' and calendar.mdl_schedule_frequency == 'fixed_intervals':
                raise ValidationError('לוח משמרות אינו יכול לעבוד בשיטת שעות קבועות.')
            if calendar.mdl_schedule_frequency == 'weekly_quota':
                if float_compare(calendar.hours_per_week, 0.0, precision_digits=2) <= 0:
                    raise ValidationError('לוח במכסה שבועית מחייב הגדרת שעות בשבוע.')
                if float_compare(calendar.hours_per_day, 0.0, precision_digits=2) <= 0:
                    raise ValidationError('לוח במכסה שבועית מחייב הגדרת שעות ביחידת יום.')
            if (calendar.mdl_schedule_frequency == 'daily_duration'
                    and float_compare(calendar.hours_per_day, 0.0, precision_digits=2) <= 0):
                raise ValidationError('לוח במכסה יומית מחייב הגדרת שעות ביחידת יום גדולה מאפס.')
