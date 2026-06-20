from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


MAX_LABEL_RANGE = 1000


class LabelsBatch(models.Model):
    _name = "labels.batch"
    _description = "טווח תוויות"
    _order = "id desc"

    name = fields.Char(
        string="שם",
        compute="_compute_name",
        store=True,
        readonly=True,
    )
    prefix = fields.Char(string="תחילית", size=1)
    first_number = fields.Integer(string="מספר ראשון", required=True, default=1)
    last_number = fields.Integer(string="מספר אחרון", required=True, default=1)
    label_count = fields.Integer(
        string="כמות תוויות",
        compute="_compute_label_count",
        store=True,
    )
    generated_label_count = fields.Integer(
        string="תוויות שנוצרו",
        compute="_compute_generated_label_count",
    )
    state = fields.Selection(
        selection=[
            ("draft", "טיוטה"),
            ("generated", "נוצר"),
            ("cancelled", "מבוטל"),
        ],
        string="סטטוס",
        default="draft",
        required=True,
    )
    label_ids = fields.One2many(
        comodel_name="labels.label",
        inverse_name="batch_id",
        string="תוויות",
        readonly=True,
    )

    @api.depends("prefix", "first_number", "last_number")
    def _compute_name(self):
        for batch in self:
            prefix = batch.prefix or ""
            batch.name = f"טווח {prefix}{batch.first_number} - {prefix}{batch.last_number}"

    @api.depends("first_number", "last_number")
    def _compute_label_count(self):
        for batch in self:
            if batch.first_number > 0 and batch.last_number >= batch.first_number:
                batch.label_count = batch.last_number - batch.first_number + 1
            else:
                batch.label_count = 0

    @api.depends("label_ids")
    def _compute_generated_label_count(self):
        label_groups = self.env["labels.label"].read_group(
            [("batch_id", "in", self.ids)],
            ["batch_id"],
            ["batch_id"],
        )
        counts = {
            group["batch_id"][0]: group["batch_id_count"]
            for group in label_groups
            if group.get("batch_id")
        }
        for batch in self:
            batch.generated_label_count = counts.get(batch.id, 0)

    @api.constrains("prefix")
    def _check_prefix(self):
        for batch in self:
            self._validate_prefix(batch.prefix)

    @api.constrains("first_number", "last_number")
    def _check_numbers(self):
        for batch in self:
            if batch.first_number <= 0:
                raise ValidationError("המספר הראשון חייב להיות גדול מ-0.")
            if batch.last_number <= 0:
                raise ValidationError("המספר האחרון חייב להיות גדול מ-0.")
            if batch.last_number < batch.first_number:
                raise ValidationError("המספר האחרון חייב להיות גדול או שווה למספר הראשון.")
            if batch.last_number - batch.first_number + 1 > MAX_LABEL_RANGE:
                raise ValidationError("לא ניתן ליצור יותר מ-1000 תוויות בטווח אחד.")

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

    def unlink(self):
        batches_with_labels = self.filtered("label_ids")
        if batches_with_labels:
            raise UserError("לא ניתן למחוק טווח שכבר נוצרו עבורו תוויות.")
        return super().unlink()

    def action_generate_labels(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError("ניתן ליצור תוויות רק מטווח במצב טיוטה.")

        prefix = self._normalize_prefix(self.prefix)
        self._validate_range()
        existing_labels = self.env["labels.label"].search(
            [
                ("prefix", "=", prefix or False),
                ("number", ">=", self.first_number),
                ("number", "<=", self.last_number),
            ],
            order="number",
            limit=20,
        )
        if existing_labels:
            existing_names = "\n".join(existing_labels.mapped("name"))
            raise UserError(
                _(
                    "כבר קיימות תוויות בטווח המבוקש:\n%(labels)s",
                    labels=existing_names,
                )
            )

        labels = self.env["labels.label"].create(
            [
                {
                    "prefix": prefix,
                    "number": number,
                    "batch_id": self.id,
                }
                for number in range(self.first_number, self.last_number + 1)
            ]
        )
        self.write({"prefix": prefix, "state": "generated"})

        action = self.action_open_labels()
        action["domain"] = [("id", "in", labels.ids)]
        return action

    def action_open_labels(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "תוויות",
            "res_model": "labels.label",
            "view_mode": "list,form,kanban",
            "domain": [("batch_id", "=", self.id)],
            "context": {"default_batch_id": self.id, "default_prefix": self.prefix},
        }

    def action_cancel(self):
        for batch in self:
            if batch.label_ids:
                raise UserError("ניתן לבטל טווח רק לפני יצירת תוויות.")
        self.write({"state": "cancelled"})

    def action_reset_to_draft(self):
        for batch in self:
            if batch.label_ids:
                raise UserError("ניתן להחזיר לטיוטה רק טווח ללא תוויות.")
        self.write({"state": "draft"})

    def _validate_range(self):
        self.ensure_one()
        if self.first_number <= 0:
            raise UserError("המספר הראשון חייב להיות גדול מ-0.")
        if self.last_number <= 0:
            raise UserError("המספר האחרון חייב להיות גדול מ-0.")
        if self.last_number < self.first_number:
            raise UserError("המספר האחרון חייב להיות גדול או שווה למספר הראשון.")
        if self.last_number - self.first_number + 1 > MAX_LABEL_RANGE:
            raise UserError("לא ניתן ליצור יותר מ-1000 תוויות בטווח אחד.")

    @api.model
    def _normalize_prefix(self, prefix):
        prefix = (prefix or "").strip().upper()
        self._validate_prefix(prefix)
        return prefix or False

    @api.model
    def _validate_prefix(self, prefix):
        if prefix and (len(prefix) != 1 or not prefix.isalpha()):
            raise ValidationError("התחילית חייבת להיות אות אחת בלבד.")
