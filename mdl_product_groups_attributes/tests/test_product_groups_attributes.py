from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.mdl_product_groups_attributes.hooks import (
    migrate_catalog_structure,
)
from odoo.addons.mdl_product_groups_attributes.models.catalog_utils import (
    render_format,
)


@tagged("post_install", "-at_install")
class TestProductGroupsAttributes(TransactionCase):
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
                            "value_ids": [Command.set([self.height_100.id])],
                        }
                    ),
                ],
            }
        )

    def test_generates_standard_internal_reference_and_final_name(self):
        template = self._create_template()
        self.assertEqual(template.name, "דלת כנף")
        self.assertEqual(template.display_name, "דלת כנף")
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
        display_without_native_code = product.with_context(
            display_default_code=False
        ).display_name
        self.assertEqual(
            display_without_native_code
            .replace("\u2066", "")
            .replace("\u2069", ""),
            "[100180100] דלת כנף 80/100 +ידית",
        )
        search_results = dict(
            self.env["product.product"]
            .with_context(display_default_code=False)
            .name_search("100180100")
        )
        self.assertEqual(
            search_results[product.id]
            .replace("\u2066", "")
            .replace("\u2069", ""),
            "[100180100] דלת כנף 80/100 +ידית",
        )
        self.assertEqual(
            product.with_context(
                display_default_code=True,
                formatted_display_name=True,
            ).display_name,
            "דלת כנף 80/100 +ידית\t--100180100--",
        )

        self.env["ir.config_parameter"].sudo().set_param(
            "mdl_product_groups_attributes.variant_display_format",
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
            "mdl_product_groups_attributes.variant_display_format",
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
            product.with_context(display_default_code=True).display_name,
        )

        sale_view = self.env.ref(
            "mdl_product_groups_attributes.mdl_sale_order_form_final_product"
        )
        self.assertTrue(sale_view.active)
        self.assertIn("product_id", sale_view.arch)
        self.assertIn("product_template_id", sale_view.arch)

    def test_variant_action_uses_full_product_form(self):
        template = self._create_template()
        action = template.action_mdl_open_variants()
        normal_form = self.env.ref("product.product_normal_form_view")

        self.assertIn((normal_form.id, "form"), action["views"])
        self.assertEqual(
            action["context"]["form_view_ref"],
            "product.product_normal_form_view",
        )

        archived_action = template.action_mdl_open_archived_variants()
        self.assertIn(("active", "=", False), archived_action["domain"])
        self.assertFalse(archived_action["context"]["active_test"])

        blocked_action = template.action_mdl_open_blocked_rules()
        self.assertEqual(
            blocked_action["res_model"],
            "mdl.blocked.variant.preview",
        )
        self.assertEqual(
            blocked_action["views"],
            [
                (
                    self.env.ref(
                        "mdl_product_groups_attributes."
                        "mdl_blocked_variant_preview_list_view"
                    ).id,
                    "list",
                ),
            ],
        )

    def test_variant_list_name_omits_the_separate_internal_reference(self):
        template = self._create_template()
        product = template.product_variant_ids.filtered(
            lambda variant: variant.default_code == "100180100"
        )

        self.assertEqual(
            product.mdl_variant_list_name,
            product.mdl_generated_name,
        )
        self.assertNotIn(product.default_code, product.mdl_variant_list_name)

        ordinary = self.env["product.template"].create(
            {"name": "מוצר Odoo רגיל"}
        ).product_variant_id
        ordinary.default_code = "ODOO-NATIVE-1"
        self.assertEqual(ordinary.mdl_variant_list_name, "מוצר Odoo רגיל")

    def test_quotation_keeps_only_real_extra_description_below_product(self):
        template = self._create_template()
        product = template.product_variant_ids.filtered(
            lambda variant: variant.default_code == "100180100"
        )
        product.description_sale = "הערת מכירה נוספת"
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
            line.name.splitlines(),
            [
                product.with_context(display_default_code=True).display_name,
                "הערת מכירה נוספת",
            ],
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

    def test_single_column_exclusion_table_manages_native_rules(self):
        template = self._create_template()
        width_value = template.mdl_attribute_value_ids.filtered(
            lambda value: value.product_attribute_value_id == self.width_80
        )
        width_90_value = template.mdl_attribute_value_ids.filtered(
            lambda value: value.product_attribute_value_id == self.width_90
        )
        height_value = template.mdl_attribute_value_ids.filtered(
            lambda value: value.product_attribute_value_id == self.height_100
        )

        template.write(
            {
                "mdl_exclusion_ids": [
                    Command.create(
                        {
                            "mdl_is_catalog_condition": True,
                            "mdl_combination_value_ids": [
                                Command.set((width_value | height_value).ids)
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
        self.assertEqual(native_rule.value_ids, height_value)
        self.assertEqual(
            native_rule.mdl_combination_value_ids,
            width_value | height_value,
        )
        self.assertTrue(native_rule)
        self.assertEqual(len(template.product_variant_ids), 1)

        native_rule.write(
            {
                "mdl_combination_value_ids": [
                    Command.set((width_90_value | height_value).ids)
                ]
            }
        )
        self.assertEqual(
            native_rule.mdl_combination_value_ids,
            width_90_value | height_value,
        )
        self.assertEqual(len(template.product_variant_ids), 1)

        template.write({"mdl_exclusion_ids": [Command.unlink(native_rule.id)]})
        self.assertFalse(native_rule.exists())
        self.assertEqual(len(template.product_variant_ids), 2)

    def test_switching_forbidden_rule_to_allowed_is_atomic(self):
        template = self._create_template()
        values = template.mdl_attribute_value_ids
        width_80 = values.filtered(
            lambda value: value.product_attribute_value_id == self.width_80
        )
        height_100 = values.filtered(
            lambda value: value.product_attribute_value_id == self.height_100
        )
        rule = self.env["product.template.attribute.exclusion"].create(
            {
                "product_tmpl_id": template.id,
                "mdl_is_catalog_condition": True,
                "mdl_rule_type": "forbidden",
                "mdl_combination_value_ids": [
                    Command.set((width_80 | height_100).ids)
                ],
            }
        )
        self.assertEqual(
            template.product_variant_ids.product_template_attribute_value_ids
            .product_attribute_value_id.filtered(
                lambda value: value.attribute_id == self.width
            ),
            self.width_90,
        )

        rule.mdl_rule_type = "allowed"

        self.assertFalse(rule.product_template_attribute_value_id)
        self.assertFalse(rule.value_ids)
        self.assertEqual(
            template.product_variant_ids.product_template_attribute_value_ids
            .product_attribute_value_id.filtered(
                lambda value: value.attribute_id == self.width
            ),
            self.width_80,
        )

    def test_no_variant_value_cannot_be_used_in_combination_rule(self):
        template = self._create_template()
        note_attribute = self.env["product.attribute"].create(
            {"name": "הערה", "create_variant": "no_variant"}
        )
        note_value = self.env["product.attribute.value"].create(
            {"name": "מיוחד", "attribute_id": note_attribute.id}
        )
        template.attribute_line_ids = [
            Command.create(
                {
                    "attribute_id": note_attribute.id,
                    "value_ids": [Command.set(note_value.ids)],
                }
            )
        ]
        values = template.mdl_attribute_value_ids
        width_80 = values.filtered(
            lambda value: value.product_attribute_value_id == self.width_80
        )
        note_template_value = values.filtered(
            lambda value: value.product_attribute_value_id == note_value
        )
        with self.assertRaises(ValidationError):
            self.env["product.template.attribute.exclusion"].create(
                {
                    "product_tmpl_id": template.id,
                    "mdl_is_catalog_condition": True,
                    "mdl_rule_type": "forbidden",
                    "mdl_combination_value_ids": [
                        Command.set((width_80 | note_template_value).ids)
                    ],
                }
            )
        height_100 = values.filtered(
            lambda value: value.product_attribute_value_id == self.height_100
        )
        with self.assertRaises(ValidationError):
            self.env["product.template.attribute.exclusion"].create(
                {
                    "product_tmpl_id": template.id,
                    "mdl_is_catalog_condition": True,
                    "mdl_rule_type": "allowed",
                    "mdl_combination_value_ids": [
                        Command.set((width_80 | height_100).ids)
                    ],
                }
            )

    def test_symmetric_exclusion_rows_are_collapsed(self):
        template = self._create_template()
        width_value = template.mdl_attribute_value_ids.filtered(
            lambda value: value.product_attribute_value_id == self.width_80
        )
        height_value = template.mdl_attribute_value_ids.filtered(
            lambda value: value.product_attribute_value_id == self.height_100
        )
        Exclusion = self.env["product.template.attribute.exclusion"]

        first_rule = Exclusion.create(
            {
                "product_tmpl_id": template.id,
                "product_template_attribute_value_id": width_value.id,
                "value_ids": [Command.set(height_value.ids)],
            }
        )
        reverse_rule = Exclusion.create(
            {
                "product_tmpl_id": template.id,
                "product_template_attribute_value_id": height_value.id,
                "value_ids": [Command.set(width_value.ids)],
            }
        )

        self.assertFalse(first_rule.exists())
        self.assertTrue(reverse_rule.exists())
        self.assertEqual(template.mdl_exclusion_ids, reverse_rule)
        self.assertEqual(
            reverse_rule.mdl_combination_value_ids,
            width_value | height_value,
        )
        self.assertEqual(len(template.product_variant_ids), 1)

    def test_mixed_optional_product_exclusion_stays_fully_native(self):
        template = self._create_template()
        optional_template = self.env["product.template"].create(
            {
                "name": "אביזר",
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": self.height.id,
                            "value_ids": [Command.set(self.height_100.ids)],
                        }
                    )
                ],
            }
        )
        template.optional_product_ids = [Command.set(optional_template.ids)]
        source = template.mdl_attribute_value_ids.filtered(
            lambda value: value.product_attribute_value_id == self.width_80
        )
        local_target = template.mdl_attribute_value_ids.filtered(
            lambda value: value.product_attribute_value_id == self.height_100
        )
        external_target = (
            optional_template.attribute_line_ids.product_template_value_ids
        )
        native_targets = local_target | external_target
        rule = self.env[
            "product.template.attribute.exclusion"
        ].with_context(mdl_skip_combination_sync=True).create(
            {
                "product_tmpl_id": template.id,
                "product_template_attribute_value_id": source.id,
                "value_ids": [Command.set(native_targets.ids)],
                "mdl_is_catalog_condition": True,
                "mdl_combination_value_ids": [
                    Command.set((source | local_target).ids)
                ],
            }
        )

        normalized = rule._mdl_expand_native_rules()

        self.assertFalse(normalized)
        self.assertEqual(set(rule.value_ids.ids), set(native_targets.ids))
        self.assertFalse(rule.mdl_is_catalog_condition)
        self.assertFalse(rule.mdl_combination_value_ids)

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

    def test_category_change_updates_group_names_and_skus(self):
        template = self._create_template()
        original_codes = set(template.product_variant_ids.mapped("default_code"))
        original_names = set(
            template.product_variant_ids.mapped("mdl_generated_name")
        )
        frame_category = self.env["product.category"].create(
            {"name": "משקוף", "mdl_sku_component": "11"}
        )
        template.categ_id = frame_category
        self.assertEqual(template.categ_id, frame_category)
        self.assertEqual(template.mdl_group_default_name, "משקוף")
        self.assertEqual(template.mdl_group_default_sku, "11")
        updated_codes = set(
            template.product_variant_ids.mapped("default_code")
        )
        updated_names = set(
            template.product_variant_ids.mapped("mdl_generated_name")
        )
        self.assertNotEqual(updated_codes, original_codes)
        self.assertNotEqual(updated_names, original_names)
        self.assertTrue(all(code.startswith("1101") for code in updated_codes))
        self.assertTrue(all(name.startswith("משקוף") for name in updated_names))

    def test_category_rename_does_not_change_the_catalog_group(self):
        template = self._create_template()
        original_codes = set(template.product_variant_ids.mapped("default_code"))
        original_names = set(
            template.product_variant_ids.mapped("mdl_generated_name")
        )
        self.category.name = "דלתות"
        self.assertEqual(template.mdl_group_default_name, "דלת")
        self.assertEqual(
            set(template.product_variant_ids.mapped("default_code")),
            original_codes,
        )
        self.assertEqual(
            set(template.product_variant_ids.mapped("mdl_generated_name")),
            original_names,
        )

    def test_model_is_converted_to_an_ordered_regular_attribute(self):
        template = self._create_template()
        products_before = template.product_variant_ids
        expected_before = {
            product.id: (product.default_code, product.mdl_generated_name)
            for product in products_before
        }

        converted = template._mdl_convert_models_to_attributes()

        self.assertEqual(converted, template)
        self.assertTrue(template.mdl_model_as_attribute)
        model_line = template.attribute_line_ids.filtered(
            "mdl_is_model_attribute"
        )
        self.assertEqual(len(model_line), 1)
        self.assertEqual(model_line.attribute_id.name, "דגם")
        self.assertEqual(model_line.value_ids.name, "כנף")
        self.assertEqual(model_line.value_ids.mdl_sku_component, "01")
        model_template_value = model_line.product_template_value_ids
        self.assertFalse(model_template_value.mdl_sku_component_override)
        self.assertLess(
            model_line.sequence,
            min((template.attribute_line_ids - model_line).mapped("sequence")),
        )
        self.assertEqual(template.mdl_effective_base_name, "דלת")
        self.assertEqual(template.mdl_sku_prefix, "10")
        self.assertEqual(template.product_variant_ids.ids, products_before.ids)
        self.assertEqual(
            {
                product.id: (product.default_code, product.mdl_generated_name)
                for product in template.product_variant_ids
            },
            expected_before,
        )

        model_template_value.mdl_sku_component_value = "99"
        self.assertEqual(model_template_value.mdl_sku_component_override, "99")
        model_template_value.action_mdl_reset_sku_component()
        self.assertFalse(model_template_value.mdl_sku_component_override)
        self.assertEqual(
            {
                product.id: product.default_code
                for product in template.product_variant_ids
            },
            {
                product_id: values[0]
                for product_id, values in expected_before.items()
            },
        )

        model_line.sequence = 30
        self.assertEqual(
            set(template.product_variant_ids.mapped("mdl_generated_name")),
            {
                "דלת 80/100 כנף +ידית",
                "דלת 90/100 כנף +ידית",
            },
        )
        self.assertEqual(
            set(template.product_variant_ids.mapped("default_code")),
            {"108010001", "109010001"},
        )

    def test_native_template_name_tracks_single_or_multiple_model_values(self):
        template = self._create_template()
        template._mdl_convert_models_to_attributes()
        model_line = template.attribute_line_ids.filtered(
            "mdl_is_model_attribute"
        )
        first_model = model_line.value_ids
        second_model = self.env["product.attribute.value"].create(
            {
                "name": "משקוף",
                "attribute_id": model_line.attribute_id.id,
                "mdl_sku_component": "02",
            }
        )
        self.assertEqual(template.name, "דלת כנף")

        model_line.value_ids = [Command.set((first_model | second_model).ids)]

        self.assertEqual(template.name, "דלת")
        self.assertTrue(
            all(
                name.count("כנף") <= 1 and name.count("משקוף") <= 1
                for name in template.product_variant_ids.mapped(
                    "mdl_generated_name"
                )
            )
        )

        model_line.value_ids = [Command.set(first_model.ids)]
        self.assertEqual(template.name, "דלת כנף")

    def test_copy_preserves_converted_structure_overrides_and_rules(self):
        template = self._create_template()
        template._mdl_convert_models_to_attributes()
        width_value = template.mdl_attribute_value_ids.filtered(
            lambda value: value.product_attribute_value_id == self.width_80
        )
        width_value.write(
            {
                "mdl_name_component_value": "80 ס״מ",
                "mdl_sku_component_value": "080",
            }
        )
        source_rule = self.env[
            "product.template.attribute.exclusion"
        ].create(
            {
                "product_tmpl_id": template.id,
                "mdl_is_catalog_condition": True,
                "mdl_rule_type": "forbidden",
                "mdl_combination_value_ids": [
                    Command.set(
                        template.mdl_attribute_value_ids.filtered(
                            lambda value: value.product_attribute_value_id
                            in (self.width_90 | self.height_100)
                        ).ids
                    )
                ],
            }
        )

        copied = template.copy()

        self.assertNotEqual(copied.id, template.id)
        self.assertTrue(copied.mdl_model_as_attribute)
        self.assertEqual(
            len(copied.attribute_line_ids.filtered("mdl_is_model_attribute")),
            1,
        )
        copied_width = copied.mdl_attribute_value_ids.filtered(
            lambda value: value.product_attribute_value_id == self.width_80
        )
        self.assertEqual(copied_width.mdl_name_component_override, "80 ס״מ")
        self.assertEqual(copied_width.mdl_sku_component_override, "080")
        copied_rules = copied.mdl_exclusion_ids.filtered(
            "mdl_is_catalog_condition"
        )
        self.assertEqual(len(copied_rules), 1)
        self.assertEqual(copied_rules.mdl_rule_type, source_rule.mdl_rule_type)
        self.assertTrue(
            all(
                name.count("כנף") <= 1
                for name in copied.product_variant_ids.mapped(
                    "mdl_generated_name"
                )
            )
        )

    def test_bulk_template_copy_uses_odoo_multi_record_contract(self):
        first = self._create_template()
        second = self._create_template()
        (first | second)._mdl_convert_models_to_attributes()

        copied = (first | second).copy()

        self.assertEqual(len(copied), 2)
        for source, target in zip(first | second, copied):
            self.assertNotEqual(source.id, target.id)
            self.assertTrue(target.mdl_model_as_attribute)
            self.assertEqual(
                target.mdl_group_default_name,
                f"{source.mdl_group_default_name} (copy)",
            )

    def test_copy_with_explicit_name_preserves_odoo_copy_default(self):
        template = self._create_template()
        template._mdl_convert_models_to_attributes()

        copied = template.copy({"name": "קבוצה מועתקת"})

        self.assertEqual(copied.name, "קבוצה מועתקת")
        self.assertEqual(copied.mdl_group_default_name, "קבוצה מועתקת")
        copied._mdl_ensure_full_model_names()
        self.assertEqual(copied.name, "קבוצה מועתקת")

        separate_group = template.copy(
            {
                "name": "שם תבנית מפורש",
                "mdl_group_default_name": "שם קבוצה מפורש",
            }
        )
        separate_group._mdl_ensure_full_model_names()
        self.assertEqual(separate_group.name, "שם תבנית מפורש")
        self.assertEqual(
            separate_group.mdl_group_default_name,
            "שם קבוצה מפורש",
        )

    def test_copy_ignores_historical_archived_template_values(self):
        template = self._create_template()
        width_line = template.attribute_line_ids.filtered(
            lambda line: line.attribute_id == self.width
        )
        width_line.value_ids = [Command.set(self.width_80.ids)]
        historical = width_line.product_template_value_ids.filtered(
            lambda value: value.product_attribute_value_id == self.width_90
        )
        if not historical:
            historical = self.env["product.template.attribute.value"].create(
                {
                    "attribute_line_id": width_line.id,
                    "product_attribute_value_id": self.width_90.id,
                    "ptav_active": False,
                }
            )
        else:
            historical.ptav_active = False
        self.assertFalse(historical.ptav_active)

        copied = template.copy()

        self.assertTrue(copied)
        self.assertFalse(
            copied.attribute_line_ids.product_template_value_ids.filtered(
                lambda value: (
                    not value.ptav_active
                    and value.product_attribute_value_id == self.width_90
                )
            )
        )

    def test_field_specific_reset_matches_native_undo_behavior(self):
        template = self._create_template()
        value = template.mdl_attribute_value_ids.filtered(
            lambda item: item.product_attribute_value_id == self.width_80
        )
        value.write(
            {
                "mdl_name_component_value": "80 ס״מ",
                "mdl_sku_component_value": "080",
            }
        )

        value.action_mdl_reset_name_component()

        self.assertFalse(value.mdl_name_component_override)
        self.assertEqual(value.mdl_sku_component_override, "080")

        value.write({"mdl_name_component_value": "80 ס״מ"})
        value.action_mdl_reset_sku_component()

        self.assertEqual(value.mdl_name_component_override, "80 ס״מ")
        self.assertFalse(value.mdl_sku_component_override)

    def test_sync_clears_stale_code_when_every_component_is_blank(self):
        no_code_value = self.env["product.attribute.value"].create(
            {
                "name": "ללא קוד",
                "attribute_id": self.width.id,
                "mdl_sku_component": "—",
            }
        )
        template = self.env["product.template"].create(
            {
                "name": "ללא קוד",
                "categ_id": self.category.id,
                "mdl_group_sku_override": "—",
                "mdl_model_sku_override": "—",
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": self.width.id,
                            "value_ids": [Command.set(no_code_value.ids)],
                        }
                    )
                ],
            }
        )
        product = template.product_variant_id
        product.with_context(skip_mdl_catalog_sync=True).default_code = "STALE"

        product._mdl_sync_default_code()

        self.assertFalse(product.default_code)

    def test_install_upgrade_migration_preserves_ids_and_archive_state(self):
        template = self._create_template()
        variants = template.product_variant_ids.sorted("id")
        manually_archived = variants[0]
        legacy_blocked = variants[1]
        original_ids = set(variants.ids)
        manually_archived.active = False
        legacy_blocked.with_context(skip_mdl_catalog_sync=True).write(
            {"mdl_catalog_allowed": False, "active": False}
        )

        migrate_catalog_structure(self.env)

        migrated_variants = template.with_context(
            active_test=False
        ).product_variant_ids
        self.assertEqual(set(migrated_variants.ids), original_ids)
        self.assertFalse(manually_archived.active)
        self.assertFalse(legacy_blocked.active)
        self.assertTrue(legacy_blocked.mdl_catalog_allowed)
        self.assertTrue(template.mdl_model_as_attribute)
        exact_rules = template.mdl_exclusion_ids.filtered(
            lambda rule: (
                rule.mdl_is_catalog_condition
                and rule.mdl_rule_type == "forbidden"
                and len(rule.mdl_combination_value_ids) == 3
            )
        )
        self.assertEqual(len(exact_rules), 1)

    def test_migration_preserves_archive_on_already_converted_template(self):
        template = self._create_template()
        template._mdl_convert_models_to_attributes()
        variants = template.product_variant_ids.sorted("id")
        manually_archived = variants[0]
        original_ids = set(variants.ids)
        manually_archived.active = False

        migrate_catalog_structure(self.env)

        migrated_variants = template.with_context(
            active_test=False
        ).product_variant_ids
        self.assertEqual(set(migrated_variants.ids), original_ids)
        self.assertFalse(manually_archived.active)

    def test_migration_keeps_legacy_flag_when_nary_rule_is_not_supported(self):
        note_attribute = self.env["product.attribute"].create(
            {"name": "הערה", "create_variant": "no_variant"}
        )
        note_value = self.env["product.attribute.value"].create(
            {
                "name": "מיוחד",
                "attribute_id": note_attribute.id,
                "mdl_sku_component": "—",
            }
        )
        template = self._create_template()
        template.attribute_line_ids = [
            Command.create(
                {
                    "attribute_id": note_attribute.id,
                    "value_ids": [Command.set(note_value.ids)],
                }
            )
        ]
        legacy_blocked = template.product_variant_ids[:1]
        legacy_blocked.with_context(skip_mdl_catalog_sync=True).write(
            {"mdl_catalog_allowed": False, "active": False}
        )

        migrate_catalog_structure(self.env)

        self.assertFalse(legacy_blocked.mdl_catalog_allowed)
        self.assertFalse(legacy_blocked.active)
        self.assertFalse(
            template.mdl_exclusion_ids.filtered(
                lambda rule: (
                    rule.mdl_is_catalog_condition
                    and len(rule.mdl_combination_value_ids) > 2
                )
            )
        )

    def test_preserve_variant_ids_context_accepts_odoo_access_argument(self):
        template = self._create_template()
        product = template.product_variant_ids[:1]

        product.with_context(
            mdl_preserve_variant_ids=True
        )._unlink_or_archive(check_access=False)

        self.assertTrue(product.exists())
        self.assertFalse(product.active)

    def test_migration_detects_legacy_template_from_category_code_only(self):
        template = self.env["product.template"].create(
            {
                "name": self.category.name,
                "categ_id": self.category.id,
            }
        )
        product_id = template.product_variant_id.id
        template.with_context(skip_mdl_catalog_sync=True).write(
            {
                "mdl_catalog_managed": False,
                "mdl_group_default_name": False,
                "mdl_group_default_sku": False,
                "mdl_model_sku_component": False,
                "mdl_model_as_attribute": False,
            }
        )
        self.assertFalse(template.mdl_sku_prefix)

        Modules = self.env["ir.module.module"].sudo()
        bridge = Modules.search(
            [("name", "=", "mdl_product_catalog")],
            limit=1,
        )
        if bridge:
            bridge.write({"state": "uninstalled"})
        else:
            bridge = Modules.create(
                {
                    "name": "mdl_product_catalog",
                    "state": "uninstalled",
                }
            )

        migrate_catalog_structure(self.env)

        self.assertTrue(template.mdl_catalog_managed)
        self.assertTrue(template.mdl_model_as_attribute)
        self.assertEqual(template.mdl_group_default_name, self.category.name)
        self.assertEqual(template.mdl_sku_prefix, self.category.mdl_sku_component)
        self.assertEqual(template.product_variant_id.id, product_id)
        self.assertFalse(
            template.attribute_line_ids.filtered("mdl_is_model_attribute")
        )

    def test_migration_removes_inactive_bridge_from_apps(self):
        Modules = self.env["ir.module.module"].sudo()
        bridge = Modules.search(
            [("name", "=", "mdl_product_catalog")],
            limit=1,
        )
        if bridge:
            bridge.write({"state": "uninstalled"})
        else:
            bridge = Modules.create(
                {
                    "name": "mdl_product_catalog",
                    "state": "uninstalled",
                }
            )

        migrate_catalog_structure(self.env)

        self.assertFalse(bridge.exists())

    def test_group_without_distinct_model_does_not_duplicate_its_name(self):
        template = self.env["product.template"].create(
            {
                "name": "דלת",
                "categ_id": self.category.id,
                "mdl_model_sku_component": "01",
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": self.width.id,
                            "value_ids": [Command.set(self.width_80.ids)],
                        }
                    )
                ],
            }
        )
        product = template.product_variant_id
        product_id = product.id
        code_before = product.default_code
        name_before = product.mdl_generated_name

        template._mdl_convert_models_to_attributes()

        self.assertTrue(template.mdl_model_as_attribute)
        self.assertFalse(
            template.attribute_line_ids.filtered("mdl_is_model_attribute")
        )
        self.assertEqual(template.product_variant_id.id, product_id)
        self.assertEqual(template.product_variant_id.default_code, code_before)
        self.assertEqual(template.product_variant_id.mdl_generated_name, name_before)
        self.assertNotIn("דלת דלת", template.product_variant_id.mdl_generated_name)

        template.action_mdl_reset_base_values()
        self.assertEqual(template.product_variant_id.default_code, code_before)

    def test_multi_value_rule_can_depend_on_model_and_other_attributes(self):
        template = self._create_template()
        template._mdl_convert_models_to_attributes()
        model_line = template.attribute_line_ids.filtered(
            "mdl_is_model_attribute"
        )
        second_model = self.env["product.attribute.value"].create(
            {
                "name": "כנף מתקדמת",
                "attribute_id": model_line.attribute_id.id,
                "mdl_sku_component": "02",
            }
        )
        model_line.write(
            {"value_ids": [Command.link(second_model.id)]}
        )
        self.assertEqual(len(template.product_variant_ids), 4)

        template_values = template.mdl_attribute_value_ids
        first_model_value = template_values.filtered(
            lambda value: (
                value.attribute_line_id == model_line
                and value.product_attribute_value_id.name == "כנף"
            )
        )
        width_value = template_values.filtered(
            lambda value: value.product_attribute_value_id == self.width_80
        )
        height_value = template_values.filtered(
            lambda value: value.product_attribute_value_id == self.height_100
        )
        rule = self.env["product.template.attribute.exclusion"].create(
            {
                "product_tmpl_id": template.id,
                "mdl_is_catalog_condition": True,
                "mdl_rule_type": "forbidden",
                "mdl_combination_value_ids": [
                    Command.set(
                        (first_model_value | width_value | height_value).ids
                    )
                ],
            }
        )

        self.assertFalse(rule.product_template_attribute_value_id)
        self.assertFalse(rule.value_ids)
        self.assertEqual(len(template.product_variant_ids), 3)
        self.assertEqual(template.mdl_blocked_variant_count, 1)
        archived_combinations = {
            frozenset(combination)
            for combination in template._get_attribute_exclusions()[
                "archived_combinations"
            ]
        }
        self.assertIn(
            frozenset(
                (first_model_value | width_value | height_value).ids
            ),
            archived_combinations,
        )

        model_line.with_context(mdl_preserve_variant_ids=True).write(
            {"value_ids": [Command.unlink(first_model_value.product_attribute_value_id.id)]}
        )
        self.assertTrue(rule.exists())
        self.assertTrue(first_model_value.exists())
        self.assertFalse(first_model_value.ptav_active)
        self.assertEqual(len(template.product_variant_ids), 2)

    def test_allowed_rules_form_an_explicit_whitelist(self):
        template = self._create_template()
        template._mdl_convert_models_to_attributes()
        model_line = template.attribute_line_ids.filtered(
            "mdl_is_model_attribute"
        )
        second_model = self.env["product.attribute.value"].create(
            {
                "name": "כנף מתקדמת",
                "attribute_id": model_line.attribute_id.id,
                "mdl_sku_component": "02",
            }
        )
        model_line.write(
            {"value_ids": [Command.link(second_model.id)]}
        )
        values = template.mdl_attribute_value_ids
        first_model_value = values.filtered(
            lambda value: (
                value.attribute_line_id == model_line
                and value.product_attribute_value_id.name == "כנף"
            )
        )
        second_model_value = values.filtered(
            lambda value: value.product_attribute_value_id == second_model
        )
        width_80 = values.filtered(
            lambda value: value.product_attribute_value_id == self.width_80
        )
        width_90 = values.filtered(
            lambda value: value.product_attribute_value_id == self.width_90
        )

        self.env["product.template.attribute.exclusion"].create(
            [
                {
                    "product_tmpl_id": template.id,
                    "mdl_is_catalog_condition": True,
                    "mdl_rule_type": "allowed",
                    "mdl_combination_value_ids": [
                        Command.set((first_model_value | width_80).ids)
                    ],
                },
                {
                    "product_tmpl_id": template.id,
                    "mdl_is_catalog_condition": True,
                    "mdl_rule_type": "allowed",
                    "mdl_combination_value_ids": [
                        Command.set((second_model_value | width_90).ids)
                    ],
                },
            ]
        )

        combinations = {
            tuple(
                sorted(
                    product.product_template_attribute_value_ids
                    .product_attribute_value_id.mapped("name")
                )
            )
            for product in template.product_variant_ids
        }
        self.assertIn(tuple(sorted(("כנף", "80", "100"))), combinations)
        self.assertIn(
            tuple(sorted(("כנף מתקדמת", "90", "100"))),
            combinations,
        )
        self.assertEqual(len(combinations), 2)
        self.assertEqual(template.mdl_blocked_variant_count, 2)

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
        template_value = template.mdl_attribute_value_ids.filtered(
            lambda value: value.product_attribute_value_id == drawing
        )
        self.assertFalse(template_value.mdl_sku_component_value)
        template_value.action_mdl_reset_sku_component()
        self.assertFalse(template_value.mdl_sku_component_override)
        self.assertFalse(template_value.mdl_sku_component_value)
        self.assertEqual(product.default_code, "TEST-NO-COMPONENT-3040")
        self.assertFalse(template._mdl_get_catalog_issues())

        product_id = product.id
        template._mdl_convert_models_to_attributes()
        self.assertTrue(template.mdl_catalog_managed)
        self.assertEqual(template.product_variant_id.id, product_id)
        self.assertEqual(
            template.product_variant_id.default_code,
            "TEST-NO-COMPONENT-3040",
        )
        self.assertTrue(template.product_variant_id.mdl_generated_name)

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

    def test_translatable_names_keep_sku_fields_language_independent(self):
        template_fields = self.env["product.template"]._fields
        product_fields = self.env["product.product"]._fields
        attribute_fields = self.env["product.attribute"]._fields
        attribute_value_fields = self.env["product.attribute.value"]._fields
        value_fields = self.env["product.template.attribute.value"]._fields
        line_fields = self.env["product.template.attribute.line"]._fields

        self.assertTrue(attribute_fields["name"].translate)
        self.assertTrue(attribute_value_fields["name"].translate)
        self.assertTrue(template_fields["name"].translate)
        self.assertTrue(template_fields["mdl_group_default_name"].translate)
        self.assertTrue(template_fields["mdl_group_name_override"].translate)
        self.assertTrue(template_fields["mdl_effective_base_name"].translate)
        self.assertTrue(template_fields["mdl_name_suffix"].translate)
        self.assertTrue(product_fields["mdl_generated_name"].translate)
        self.assertTrue(value_fields["mdl_name_component_override"].translate)
        self.assertTrue(line_fields["mdl_name_suffix"].translate)
        self.assertFalse(template_fields["mdl_group_default_sku"].translate)
        self.assertFalse(value_fields["mdl_sku_component_override"].translate)

    def test_english_and_legacy_display_tokens_render_the_same_identity(self):
        values = {
            "SKU": "[100180100]",
            "Product Name": "Door 80/100",
            "מק״ט": "[100180100]",
            "שם הפריט": "Door 80/100",
        }
        english, english_missing = render_format(
            "[SKU] [Product Name]", values
        )
        legacy, legacy_missing = render_format(
            "[מק״ט] [שם הפריט]", values
        )

        self.assertFalse(english_missing)
        self.assertFalse(legacy_missing)
        self.assertEqual(english, legacy)
