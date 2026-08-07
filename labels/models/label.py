from odoo import fields, models


class LabelsLabel(models.Model):
    _name = "labels.label"
    _description = "תווית"
    _order = "id desc"

    name = fields.Char(string="שם", required=True)
