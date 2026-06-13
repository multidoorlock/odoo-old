from odoo import fields, models


class LabelsBatchWizard(models.TransientModel):
    _name = "labels.batch.wizard"
    _description = "יצירת טווח תוויות"

    prefix = fields.Char(string="תחילית", size=1)
    first_number = fields.Integer(string="מספר ראשון", required=True, default=1)
    last_number = fields.Integer(string="מספר אחרון", required=True, default=1)

    def action_save(self):
        self.ensure_one()
        batch = self.env["labels.batch"].create(
            {
                "prefix": self.prefix,
                "first_number": self.first_number,
                "last_number": self.last_number,
            }
        )
        return batch.action_generate_labels()
