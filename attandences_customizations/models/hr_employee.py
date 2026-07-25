from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    att_record_type = fields.Selection(
        readonly=False, related="version_id.att_record_type", inherited=True,
        groups="hr.group_hr_user")
    att_classification_ruleset_id = fields.Many2one(
        readonly=False, related="version_id.att_classification_ruleset_id", inherited=True, groups="hr.group_hr_manager")
    att_overtime_hourly_rate = fields.Float(
        readonly=False, related="version_id.att_overtime_hourly_rate", inherited=True,
        groups="hr_payroll.group_hr_payroll_user")
