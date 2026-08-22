from odoo.fields import Command
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestProductCatalog(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.category = cls.env["product.category"].create(
            {"name": "דלת", "mdl_group_code": "10"}
        )
        cls.width = cls.env["product.attribute"].create(
            {"name": "רוחב", "create_variant": "always"}
        )
        cls.height = cls.env["product.attribute"].create(
            {"name": "גובה", "create_variant": "always"}
        )
        cls.width_80 = cls.env["product.attribute.value"].create(
            {
                "name": "80",
                "attribute_id": cls.width.id,
                "mdl_sku_component": "80",
            }
        )
        cls.width_90 = cls.env["product.attribute.value"].create(
            {
                "name": "90",
                "attribute_id": cls.width.id,
                "mdl_sku_component": "90",
            }
        )
        cls.height_100 = cls.env["product.attribute.value"].create(
            {
                "name": "100",
                "attribute_id": cls.height.id,
                "mdl_sku_component": "100",
            }
        )

    def _create_template(self):
        return self.env["product.template"].create(
            {
                "name": "כנף",
                "categ_id": self.category.id,
                "mdl_model_code": "01",
                "mdl_name_format": "[שם קבוצת פריטים] [דגם] [רוחב]/[גובה] +ידית",
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": self.width.id,
                            "value_ids": [Command.set([self.width_80.id, self.width_90.id])],
                        }
                    ),
                    Command.create(
                        {
                            "attribute_id": self.height.id,
                            "value_ids": [Command.set([self.height_100.id])],
                        }
                    ),
                ],
            }
        )

    def test_generates_sku_and_name_from_format(self):
        template = self._create_template()
        self.assertEqual(template.name, "דלת כנף")
        self.assertEqual(template.mdl_model_lookup, "1001 - דלת כנף")
        self.assertEqual(len(template.product_variant_ids), 2)
        by_width = {
            product.product_template_attribute_value_ids.filtered(
                lambda value: value.attribute_id == self.width
            ).product_attribute_value_id.name: product
            for product in template.product_variant_ids
        }
        self.assertEqual(by_width["80"].mdl_generated_sku, "100180100")
        self.assertEqual(by_width["80"].default_code, "100180100")
        self.assertEqual(
            by_width["80"].mdl_generated_name,
            "דלת כנף 80/100 +ידית",
        )

    def test_final_product_display_and_search(self):
        template = self._create_template()
        product = template.product_variant_ids.filtered(
            lambda variant: variant.default_code == "100180100"
        )
        self.assertEqual(
            product.display_name.replace("\u2066", "").replace("\u2069", ""),
            "מק״ט 100180100 — דלת כנף 80/100 +ידית",
        )
        product_results = dict(
            self.env["product.product"].name_search("100180100")
        )
        self.assertIn(product.id, product_results)
        template_results = dict(
            self.env["product.template"].name_search("100180100")
        )
        self.assertIn(template.id, template_results)

        self.env["ir.config_parameter"].sudo().set_param(
            "mdl_product_catalog.variant_display_format",
            "[מק״ט] | [שם הפריט]",
        )
        product.invalidate_recordset(["display_name"])
        self.assertEqual(
            product.display_name.replace("\u2066", "").replace("\u2069", ""),
            "100180100 | דלת כנף 80/100 +ידית",
        )
        self.env["ir.config_parameter"].sudo().set_param(
            "mdl_product_catalog.variant_display_format",
            "מק״ט [מק״ט] — [שם הפריט]",
        )

    def test_quotation_uses_final_product_name(self):
        template = self._create_template()
        product = template.product_variant_ids.filtered(
            lambda variant: variant.default_code == "100180100"
        )
        partner = self.env["res.partner"].create({"name": "לקוח בדיקה"})
        order = self.env["sale.order"].create({"partner_id": partner.id})
        line = self.env["sale.order.line"].create(
            {
                "order_id": order.id,
                "product_id": product.id,
                "product_uom_qty": 1,
            }
        )
        self.assertEqual(
            line.name.splitlines()[0],
            "דלת כנף 80/100 +ידית",
        )

    def test_model_specific_name_override(self):
        template = self._create_template()
        template.mdl_template_value_ids.filtered(
            lambda value: value.product_attribute_value_id == self.width_80
        ).mdl_name_component_override = "80 ס״מ"
        product = template.product_variant_ids.filtered(
            lambda variant: self.width_80
            in variant.product_template_attribute_value_ids.product_attribute_value_id
        )
        self.assertEqual(product.mdl_generated_name, "דלת כנף 80 ס״מ/100 +ידית")

    def test_group_change_updates_full_model_name_without_duplication(self):
        template = self._create_template()
        frame_category = self.env["product.category"].create(
            {"name": "משקוף", "mdl_group_code": "11"}
        )
        template.categ_id = frame_category
        self.assertEqual(template.name, "משקוף כנף")
        self.assertEqual(template.mdl_model_lookup, "1101 - משקוף כנף")
        self.assertTrue(
            all(
                product.mdl_generated_name.startswith("משקוף כנף")
                for product in template.product_variant_ids
            )
        )

    def test_group_rename_updates_model_and_final_product_names(self):
        template = self._create_template()
        self.category.name = "דלתות"
        self.assertEqual(template.name, "דלתות כנף")
        self.assertTrue(
            all(
                product.mdl_generated_name.startswith("דלתות כנף")
                for product in template.product_variant_ids
            )
        )

    def test_unknown_token_is_reported(self):
        template = self._create_template()
        template.mdl_name_format = "[שם קבוצת פריטים] [דגם] [צבע]"
        self.assertEqual(template.mdl_catalog_status, "error")
        self.assertIn("[צבע]", template.mdl_catalog_errors)

    def test_group_and_model_name_components(self):
        template = self._create_template()
        template.write(
            {
                "mdl_group_name_component": "סט דלת",
                "mdl_model_name_component": "כנף מיוחדת",
            }
        )
        self.assertTrue(
            all(
                product.mdl_generated_name.startswith("סט דלת כנף מיוחדת")
                for product in template.product_variant_ids
            )
        )
        template.mdl_suppress_model_name = True
        self.assertTrue(
            all(
                product.mdl_generated_name.startswith("סט דלת 80")
                or product.mdl_generated_name.startswith("סט דלת 90")
                for product in template.product_variant_ids
            )
        )
