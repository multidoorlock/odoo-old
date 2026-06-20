from odoo import api, fields, models
from odoo.exceptions import ValidationError


class LabelsLabel(models.Model):
    _name = "labels.label"
    _description = "תווית"
    _order = "prefix, number, id"

    name = fields.Char(
        string="שם",
        compute="_compute_name",
        store=True,
        readonly=True,
    )
    prefix = fields.Char(string="תחילית", size=1)
    number = fields.Integer(string="מספר", required=True)
    status = fields.Selection(
        selection=[
            ("draft", "חדש"),
            ("printed", "הודפס"),
            ("cancelled", "מבוטל"),
        ],
        string="סטטוס",
        default="draft",
        required=True,
    )
    label_key = fields.Char(
        string="מפתח תווית",
        compute="_compute_label_key",
        store=True,
        readonly=True,
        index=True,
    )
    batch_id = fields.Many2one(
        comodel_name="labels.batch",
        string="טווח",
        readonly=True,
        ondelete="restrict",
        index=True,
    )

    _sql_constraints = [
        (
            "labels_label_key_uniq",
            "unique(label_key)",
            "כבר קיימת תווית עם אותו מספר ואותה תחילית.",
        ),
        (
            "labels_label_number_positive",
            "CHECK(number > 0)",
            "מספר התווית חייב להיות גדול מ-0.",
        ),
    ]

    @api.depends("prefix", "number")
    def _compute_name(self):
        for label in self:
            prefix = label.prefix or ""
            label.name = f"{prefix}{label.number:06d}" if label.number else False

    @api.depends("prefix", "number")
    def _compute_label_key(self):
        for label in self:
            prefix = label.prefix or ""
            label.label_key = f"{prefix}:{label.number}" if label.number else False

    @api.constrains("prefix")
    def _check_prefix(self):
        for label in self:
            self._validate_prefix(label.prefix)

    @api.constrains("number")
    def _check_number(self):
        for label in self:
            if label.number <= 0:
                raise ValidationError("מספר התווית חייב להיות גדול מ-0.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if "prefix" in vals:
                vals["prefix"] = self._normalize_prefix(vals.get("prefix"))
        return super().create(vals_list)

    def write(self, vals):
        if "prefix" in vals:
            vals = dict(vals)
            vals["prefix"] = self._normalize_prefix(vals.get("prefix"))
        return super().write(vals)

    @api.model
    def _normalize_prefix(self, prefix):
        prefix = (prefix or "").strip().upper()
        self._validate_prefix(prefix)
        return prefix or False

    @api.model
    def _validate_prefix(self, prefix):
        if prefix and (len(prefix) != 1 or not prefix.isalpha()):
            raise ValidationError("התחילית חייבת להיות אות אחת בלבד.")
