from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestProductCatalog(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.category = cls.env["product.category"].create(
            {"name": "דלת", "mdl_sku_component": "10"}
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
                "mdl_model_sku_component": "01",
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": self.width.id,
                            "sequence": 10,
                            "mdl_name_mode": "value",
                            "mdl_name_suffix": "/",
                            "value_ids": [
                                Command.set([self.width_80.id, self.width_90.id])
                            ],
                        }
                    ),
                    Command.create(
                        {
                            "attribute_id": self.height.id,
                            "sequence": 20,
                            "mdl_name_mode": "value",
                            "mdl_name_suffix": " +ידית",
                            "value_ids": [Command.set([self.height_100.id])],
                        }
                    ),
                ],
            }
        )

    def test_generates_standard_internal_reference_and_final_name(self):
        template = self._create_template()
        self.assertEqual(template.name, "דלת כנף")
        self.assertEqual(template.display_name, "1001 - דלת כנף")
        self.assertEqual(len(template.product_variant_ids), 2)
        by_width = {
            product.product_template_attribute_value_ids.filtered(
                lambda value: value.attribute_id == self.width
            ).product_attribute_value_id.name: product
            for product in template.product_variant_ids
        }
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
        clean_display_name = (
            product.display_name
            .replace("\u2066", "")
            .replace("\u2069", "")
        )
        self.assertEqual(
            clean_display_name,
            "[100180100] דלת כנף 80/100 +ידית",
        )
        self.assertIn(
            product.id,
            dict(self.env["product.product"].name_search("100180100")),
        )
        self.assertIn(
            template.id,
            dict(self.env["product.template"].name_search("100180100")),
        )

        self.env["ir.config_parameter"].sudo().set_param(
            "mdl_product_catalog.variant_display_format",
            "[מק״ט] | [שם הפריט]",
        )
        product.invalidate_recordset(["display_name"])
        self.assertEqual(
            product.display_name
            .replace("\u2066", "")
            .replace("\u2069", ""),
            "[100180100] | דלת כנף 80/100 +ידית",
        )
        self.env["ir.config_parameter"].sudo().set_param(
            "mdl_product_catalog.variant_display_format",
            "[מק״ט] [שם הפריט]",
        )

    def test_opening_direction_marker_is_displayed_at_the_end(self):
        opening = self.env["product.attribute"].create(
            {"name": "צורת פתיחה לדלת", "create_variant": "always"}
        )
        left = self.env["product.attribute.value"].create(
            {
                "name": "L שמאל",
                "attribute_id": opening.id,
                "mdl_sku_component": "1",
            }
        )
        template = self.env["product.template"].create(
            {
                "name": "כנף",
                "categ_id": self.category.id,
                "mdl_model_sku_component": "01",
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": opening.id,
                            "sequence": 5,
                            "mdl_name_suffix": " ",
                            "value_ids": [Command.set([left.id])],
                        }
                    ),
                    Command.create(
                        {
                            "attribute_id": self.width.id,
                            "sequence": 10,
                            "mdl_name_suffix": "/",
                            "value_ids": [Command.set([self.width_80.id])],
                        }
                    ),
                    Command.create(
                        {
                            "attribute_id": self.height.id,
                            "sequence": 20,
                            "value_ids": [Command.set([self.height_100.id])],
                        }
                    ),
                ],
            }
        )
        product = template.product_variant_id
        self.assertEqual(product.default_code, "1001180100")
        self.assertEqual(product.mdl_generated_name, "דלת כנף שמאל 80/100 L")
        self.assertEqual(
            product.display_name.replace("\u2066", "").replace("\u2069", ""),
            "[1001180100] דלת כנף שמאל 80/100 L",
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

    def test_model_specific_value_overrides(self):
        template = self._create_template()
        value = template.attribute_line_ids.product_template_value_ids.filtered(
            lambda item: item.product_attribute_value_id == self.width_80
        )
        value.write(
            {
                "mdl_sku_component_override": "080",
                "mdl_name_component_override": "80 ס״מ",
            }
        )
        product = template.product_variant_ids.filtered(
            lambda variant: self.width_80
            in variant.product_template_attribute_value_ids.product_attribute_value_id
        )
        self.assertEqual(product.default_code, "1001080100")
        self.assertEqual(product.mdl_generated_name, "דלת כנף 80 ס״מ/100 +ידית")

    def test_base_defaults_and_overrides_drive_the_result(self):
        template = self._create_template()
        self.assertEqual(template.mdl_group_default_name, "דלת")
        self.assertEqual(template.mdl_group_default_sku, "10")
        self.assertEqual(template.mdl_model_default_name, "כנף")
        self.assertEqual(template.mdl_model_sku_component, "01")
        self.assertEqual(template.mdl_effective_base_name, "דלת כנף")
        self.assertEqual(template.mdl_sku_prefix, "1001")

        template.write(
            {
                "mdl_group_name_override": "סט דלת",
                "mdl_group_sku_override": "90",
                "mdl_model_name_override": "מיוחדת",
                "mdl_model_sku_override": "07",
            }
        )
        self.assertEqual(template.mdl_effective_base_name, "סט דלת מיוחדת")
        self.assertEqual(template.mdl_sku_prefix, "9007")
        self.assertTrue(
            all(
                product.default_code.startswith("9007")
                and product.mdl_generated_name.startswith("סט דלת מיוחדת")
                for product in template.product_variant_ids
            )
        )

    def test_attribute_value_defaults_are_editable_from_the_model_table(self):
        template = self._create_template()
        template_value = template.mdl_attribute_value_ids.filtered(
            lambda item: item.product_attribute_value_id == self.width_80
        )
        template_value.write(
            {
                "mdl_default_name_component": "80 ס״מ",
                "mdl_default_sku_component": "080",
            }
        )
        product = template.product_variant_ids.filtered(
            lambda variant: self.width_80
            in variant.product_template_attribute_value_ids.product_attribute_value_id
        )
        self.assertEqual(self.width_80.name, "80 ס״מ")
        self.assertEqual(self.width_80.mdl_sku_component, "080")
        self.assertEqual(product.default_code, "1001080100")
        self.assertEqual(product.mdl_generated_name, "דלת כנף 80 ס״מ/100 +ידית")

    def test_native_attribute_line_controls_name(self):
        template = self._create_template()
        width_line = template.attribute_line_ids.filtered(
            lambda line: line.attribute_id == self.width
        )
        height_line = template.attribute_line_ids.filtered(
            lambda line: line.attribute_id == self.height
        )
        width_line.write(
            {
                "mdl_name_mode": "attribute_value",
                "mdl_name_suffix": " +ידית",
            }
        )
        height_line.mdl_name_mode = "hidden"
        self.assertTrue(
            all(
                product.mdl_generated_name
                in {
                    "דלת כנף רוחב 80 +ידית",
                    "דלת כנף רוחב 90 +ידית",
                }
                for product in template.product_variant_ids
            )
        )

    def test_group_change_updates_model_and_final_names(self):
        template = self._create_template()
        frame_category = self.env["product.category"].create(
            {"name": "משקוף", "mdl_sku_component": "11"}
        )
        template.categ_id = frame_category
        self.assertEqual(template.name, "משקוף כנף")
        self.assertTrue(
            all(
                product.mdl_generated_name.startswith("משקוף כנף")
                for product in template.product_variant_ids
            )
        )

    def test_group_rename_updates_model_and_final_names(self):
        template = self._create_template()
        self.category.name = "דלתות"
        self.assertEqual(template.name, "דלתות כנף")
        self.assertTrue(
            all(
                product.mdl_generated_name.startswith("דלתות כנף")
                for product in template.product_variant_ids
            )
        )

    def test_missing_attribute_code_is_reported(self):
        color = self.env["product.attribute"].create(
            {"name": "צבע", "create_variant": "always"}
        )
        white = self.env["product.attribute.value"].create(
            {"name": "לבן", "attribute_id": color.id}
        )
        template = self._create_template()
        template.attribute_line_ids = [
            Command.create(
                {
                    "attribute_id": color.id,
                    "value_ids": [Command.set([white.id])],
                }
            )
        ]
        with self.assertRaises(UserError):
            template.action_mdl_check_and_rebuild()

    def test_dash_attribute_code_intentionally_adds_nothing_to_sku(self):
        finish = self.env["product.attribute"].create(
            {"name": "גימור", "create_variant": "always"}
        )
        drawing = self.env["product.attribute.value"].create(
            {
                "name": "מיוחד על פי שרטוט",
                "attribute_id": finish.id,
                "mdl_sku_component": "—",
            }
        )
        template = self.env["product.template"].create(
            {
                "name": "צינור 4\"",
                "categ_id": self.category.id,
                "mdl_group_sku_override": "—",
                "mdl_model_sku_component": "TEST-NO-COMPONENT-3040",
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": finish.id,
                            "value_ids": [Command.set([drawing.id])],
                        }
                    )
                ],
            }
        )
        product = template.product_variant_id
        self.assertEqual(product.default_code, "TEST-NO-COMPONENT-3040")
        self.assertFalse(template._mdl_get_catalog_issues())

    def test_variant_base_name_can_differ_from_model_name(self):
        template = self._create_template()
        template.write(
            {
                "mdl_group_name_override": "סט דלת",
                "mdl_model_name_override": "מיוחדת",
            }
        )
        self.assertTrue(
            all(
                product.mdl_generated_name.startswith("סט דלת מיוחדת")
                for product in template.product_variant_ids
            )
        )
