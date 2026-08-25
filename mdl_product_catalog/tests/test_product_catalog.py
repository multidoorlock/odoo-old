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
                "mdl_name_suffix": " +ידית",
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

    def test_empty_text_after_adds_a_natural_space(self):
        template = self._create_template()
        width_line = template.attribute_line_ids.filtered(
            lambda line: line.attribute_id == self.width
        )
        width_line.mdl_name_suffix = False
        names = set(template.product_variant_ids.mapped("mdl_generated_name"))
        self.assertIn("דלת כנף 80 100 +ידית", names)
        self.assertIn("דלת כנף 90 100 +ידית", names)

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
                "mdl_sku_component_value": "080",
                "mdl_name_component_value": "80 ס״מ",
            }
        )
        self.assertEqual(value.mdl_sku_component_override, "080")
        self.assertEqual(value.mdl_name_component_override, "80 ס״מ")
        self.assertEqual(self.width_80.mdl_sku_component, "80")
        self.assertEqual(self.width_80.name, "80")
        product = template.product_variant_ids.filtered(
            lambda variant: self.width_80
            in variant.product_template_attribute_value_ids.product_attribute_value_id
        )
        self.assertEqual(product.default_code, "1001080100")
        self.assertEqual(product.mdl_generated_name, "דלת כנף 80 ס״מ/100 +ידית")

        value.action_mdl_reset_components()
        self.assertFalse(value.mdl_sku_component_override)
        self.assertFalse(value.mdl_name_component_override)
        self.assertEqual(value.mdl_sku_component_value, "80")
        self.assertEqual(value.mdl_name_component_value, "80")
        self.assertEqual(product.default_code, "100180100")
        self.assertEqual(product.mdl_generated_name, "דלת כנף 80/100 +ידית")

    def test_separate_exclusion_table_manages_native_rules(self):
        template = self._create_template()
        height_110 = self.env["product.attribute.value"].create(
            {
                "name": "110",
                "attribute_id": self.height.id,
                "mdl_sku_component": "110",
            }
        )
        height_line = template.attribute_line_ids.filtered(
            lambda line: line.attribute_id == self.height
        )
        height_line.write({"value_ids": [Command.link(height_110.id)]})
        width_value = template.mdl_attribute_value_ids.filtered(
            lambda value: value.product_attribute_value_id == self.width_80
        )
        height_value = template.mdl_attribute_value_ids.filtered(
            lambda value: value.product_attribute_value_id == self.height_100
        )
        height_110_value = template.mdl_attribute_value_ids.filtered(
            lambda value: value.product_attribute_value_id == height_110
        )

        template.write(
            {
                "mdl_exclusion_ids": [
                    Command.create(
                        {
                            "product_template_attribute_value_id": width_value.id,
                            "value_ids": [
                                Command.set((height_value | height_110_value).ids)
                            ],
                        }
                    )
                ]
            }
        )
        native_rule = template.mdl_exclusion_ids
        self.assertEqual(len(native_rule), 1)
        self.assertEqual(
            native_rule.product_template_attribute_value_id,
            width_value,
        )
        self.assertEqual(native_rule.mdl_source_attribute_id, self.width)
        self.assertEqual(native_rule.value_ids, height_value | height_110_value)
        self.assertTrue(native_rule)
        self.assertEqual(len(template.product_variant_ids), 2)

        native_rule.write({"value_ids": [Command.unlink(height_value.id)]})
        self.assertEqual(native_rule.value_ids, height_110_value)
        self.assertEqual(len(template.product_variant_ids), 3)

        template.write({"mdl_exclusion_ids": [Command.unlink(native_rule.id)]})
        self.assertFalse(native_rule.exists())
        self.assertEqual(len(template.product_variant_ids), 4)

    def test_base_defaults_and_overrides_drive_the_result(self):
        template = self._create_template()
        self.assertEqual(template.mdl_group_name_value, "דלת")
        self.assertEqual(template.mdl_group_sku_value, "10")
        self.assertEqual(template.mdl_model_name_value, "כנף")
        self.assertEqual(template.mdl_model_sku_value, "01")
        self.assertEqual(template.mdl_effective_base_name, "דלת כנף")
        self.assertEqual(template.mdl_sku_prefix, "1001")

        template.write(
            {
                "mdl_effective_base_name": "סט דלת מיוחדת",
                "mdl_sku_prefix": "9007",
            }
        )
        self.assertEqual(template.mdl_group_name_override, "—")
        self.assertEqual(template.mdl_group_sku_override, "—")
        self.assertEqual(template.mdl_model_name_override, "סט דלת מיוחדת")
        self.assertEqual(template.mdl_model_sku_override, "9007")
        self.assertEqual(template.mdl_effective_base_name, "סט דלת מיוחדת")
        self.assertEqual(template.mdl_sku_prefix, "9007")
        self.assertTrue(
            all(
                product.default_code.startswith("9007")
                and product.mdl_generated_name.startswith("סט דלת מיוחדת")
                for product in template.product_variant_ids
            )
        )

        template.action_mdl_reset_base_values()
        self.assertFalse(template.mdl_group_name_override)
        self.assertFalse(template.mdl_group_sku_override)
        self.assertFalse(template.mdl_model_name_override)
        self.assertFalse(template.mdl_model_sku_override)
        self.assertEqual(template.mdl_group_name_value, "דלת")
        self.assertEqual(template.mdl_group_sku_value, "10")
        self.assertEqual(template.mdl_model_name_value, "כנף")
        self.assertEqual(template.mdl_model_sku_value, "01")
        self.assertEqual(template.mdl_effective_base_name, "דלת כנף")
        self.assertEqual(template.mdl_sku_prefix, "1001")

    def test_technical_data_is_stored_on_the_final_variant(self):
        template = self._create_template()
        variants = template.product_variant_ids.sorted("default_code")
        first = variants[0]
        second = variants[1]

        first.write(
            {
                "mdl_length_cm": 120.5,
                "mdl_width_cm": 80.0,
                "mdl_height_cm": 40.0,
                "weight": 49.4,
                "volume": 0.3856,
                "mdl_max_protected_area_m2": 20.0,
                "mdl_installation_type": "overhead",
            }
        )

        self.assertEqual(first.mdl_length_cm, 120.5)
        self.assertEqual(first.mdl_width_cm, 80.0)
        self.assertEqual(first.mdl_height_cm, 40.0)
        self.assertEqual(first.weight, 49.4)
        self.assertEqual(first.volume, 0.39)
        self.assertEqual(first.mdl_max_protected_area_m2, 20.0)
        self.assertEqual(first.mdl_installation_type, "overhead")
        self.assertFalse(second.mdl_length_cm)
        self.assertFalse(second.mdl_max_protected_area_m2)
        self.assertFalse(second.mdl_installation_type)

    def test_optional_values_do_not_leave_dangling_separators(self):
        wall = self.env["product.attribute"].create(
            {"name": "עובי קיר", "create_variant": "always"}
        )
        dressing = self.env["product.attribute"].create(
            {"name": "עומק הלבשה", "create_variant": "always"}
        )
        company = self.env["product.attribute"].create(
            {"name": "חברה", "create_variant": "always"}
        )
        wall_30 = self.env["product.attribute.value"].create(
            {
                "name": "30",
                "attribute_id": wall.id,
                "mdl_sku_component": "30",
            }
        )
        no_dressing = self.env["product.attribute.value"].create(
            {
                "name": "ללא הלבשה",
                "attribute_id": dressing.id,
                "mdl_sku_component": "—",
            }
        )
        dressing_3 = self.env["product.attribute.value"].create(
            {
                "name": "3",
                "attribute_id": dressing.id,
                "mdl_sku_component": "03",
            }
        )
        multidoorlock = self.env["product.attribute.value"].create(
            {
                "name": "מולטי דורלוק",
                "attribute_id": company.id,
                "mdl_sku_component": "—",
            }
        )
        rav_bariach = self.env["product.attribute.value"].create(
            {
                "name": "רב בריח",
                "attribute_id": company.id,
                "mdl_sku_component": "01",
            }
        )
        template = self.env["product.template"].with_context(
            skip_mdl_catalog_sync=True
        ).create(
            {
                "name": "חלון",
                "categ_id": self.category.id,
                "mdl_model_sku_component": "32",
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": wall.id,
                            "sequence": 10,
                            "mdl_name_suffix": "+",
                            "value_ids": [Command.set([wall_30.id])],
                        }
                    ),
                    Command.create(
                        {
                            "attribute_id": dressing.id,
                            "sequence": 20,
                            "mdl_name_suffix": " ",
                            "value_ids": [
                                Command.set([no_dressing.id, dressing_3.id])
                            ],
                        }
                    ),
                    Command.create(
                        {
                            "attribute_id": company.id,
                            "sequence": 30,
                            "value_ids": [
                                Command.set([multidoorlock.id, rav_bariach.id])
                            ],
                        }
                    ),
                ],
            }
        )
        for value in template.attribute_line_ids.product_template_value_ids:
            if value.product_attribute_value_id in (
                no_dressing,
                multidoorlock,
            ):
                value.mdl_name_component_override = "—"
        template.with_context(
            skip_mdl_catalog_sync=False
        )._mdl_sync_variant_codes()
        names = set(template.product_variant_ids.mapped("mdl_generated_name"))
        self.assertIn("דלת חלון 30", names)
        self.assertIn("דלת חלון 30+3", names)
        self.assertIn("דלת חלון 30 רב בריח", names)
        self.assertIn("דלת חלון 30+3 רב בריח", names)

    def test_attribute_value_edit_in_model_does_not_change_the_source(self):
        template = self._create_template()
        template_value = template.mdl_attribute_value_ids.filtered(
            lambda item: item.product_attribute_value_id == self.width_80
        )
        template_value.write(
            {
                "mdl_name_component_value": "80 ס״מ",
                "mdl_sku_component_value": "080",
            }
        )
        product = template.product_variant_ids.filtered(
            lambda variant: self.width_80
            in variant.product_template_attribute_value_ids.product_attribute_value_id
        )
        self.assertEqual(self.width_80.name, "80")
        self.assertEqual(self.width_80.mdl_sku_component, "80")
        self.assertEqual(template_value.mdl_name_component_value, "80 ס״מ")
        self.assertEqual(template_value.mdl_sku_component_value, "080")
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
