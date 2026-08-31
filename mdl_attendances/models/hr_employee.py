from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    segment_ruleset_id = fields.Many2one(
        related="version_id.segment_ruleset_id",
        readonly=False,
        inherited=True,
        groups="hr.group_hr_manager",
    )
