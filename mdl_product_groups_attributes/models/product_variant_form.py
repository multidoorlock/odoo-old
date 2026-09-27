from odoo import Command, _, api, fields, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    # UI relations to native price records, not copies or a new pricing engine.
    # Do not filter seller_ids globally: purchasing must still be able to use
    # Odoo's shared template prices as a fallback.
    mdl_variant_seller_ids = fields.One2many(
        "product.supplierinfo",
        "product_id",
        string="Variant Vendor Prices",
        copy=False,
    )
    mdl_shared_seller_ids = fields.Many2many(
        "product.supplierinfo",
        string="All Variants",
        compute="_compute_mdl_shared_seller_ids",
        readonly=True,
    )
    mdl_variant_pricelist_item_ids = fields.One2many(
        "product.pricelist.item",
        "product_id",
        string="Variant Sales Prices",
        domain=[("applied_on", "=", "0_product_variant")],
        copy=False,
    )

    @api.depends(
        "product_tmpl_id",
        "product_tmpl_id.seller_ids",
        "product_tmpl_id.seller_ids.product_id",
    )
    @api.depends_context("company")
    def _compute_mdl_shared_seller_ids(self):
        for product in self:
            # Reference the original supplier rows. Do not duplicate prices or
            # include another variant's rows, and respect normal read access.
            product.mdl_shared_seller_ids = product.product_tmpl_id.seller_ids.filtered(
                lambda seller: not seller.product_id
            )

    def action_mdl_open_product_template(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Product Template"),
            "res_model": "product.template",
            "res_id": self.product_tmpl_id.id,
            "view_mode": "form",
            "views": [
                (self.env.ref("product.product_template_only_form_view").id, "form")
            ],
            "target": "current",
            "context": {"form_view_ref": "product.product_template_only_form_view"},
        }

    def write(self, vals):
        if "mdl_variant_pricelist_item_ids" in vals and len(self) == 1:
            # Native display_applied_on onchanges can turn an inline variant
            # row back into a template rule before the x2many is saved.  This
            # relation is variant-only, so enforce its scope at the ORM edge.
            commands = []
            for command in vals["mdl_variant_pricelist_item_ids"]:
                if command[0] != Command.CREATE:
                    commands.append(command)
                    continue
                item_vals = dict(command[2])
                item_vals.update({
                    "product_id": self.id,
                    "product_tmpl_id": self.product_tmpl_id.id,
                    "applied_on": "0_product_variant",
                })
                commands.append(Command.create(item_vals))
            vals = dict(vals, mdl_variant_pricelist_item_ids=commands)
        return super().write(vals)

    @api.model
    def _get_view(self, view_id=None, view_type="form", **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        if view_type != "form" or not arch.xpath(
            "//button[@name='action_mdl_open_product_template']"
        ):
            return arch, view

        # Odoo delegates template fields to product.product. Editing them on a
        # saved variant would silently change its siblings. Protect these in
        # the full form only; keep native model writes and new-product creation.
        # Skip nested x2many views: their fields belong to a different model.
        for node in arch.xpath("//field[not(ancestor::field)]"):
            field = self._fields.get(node.get("name"))
            if not field:
                continue
            related = field.related or ()
            if isinstance(related, str):
                related = related.split(".")
            shared = field.inherited or (
                related and related[0] == "product_tmpl_id"
            )
            # Native lst_price has an inverse writing the template list_price.
            if shared or field.name == "lst_price":
                readonly = node.get("readonly", "False")
                node.set("readonly", f"({readonly}) or id")
        return arch, view

    @api.readonly
    def action_open_documents(self):
        action = super().action_open_documents()
        # A removable search filter is not enough to scope the Documents page.
        # Match the native variant document counter with a hard domain.
        action["domain"] = [
            ("res_model", "=", "product.product"),
            ("res_id", "in", self.ids),
        ]
        return action


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def action_mdl_open_product_variants(self):
        action = self._mdl_variant_action(_("Product Variants"))
        action["context"].update({"active_test": True, "create": False})
        action["target"] = "current"
        return action
