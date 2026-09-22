"""Regression tests for materializing the old multilingual name base.

The pure cases also run without an Odoo runtime:
    python mdl_product_groups_attributes/tests/test_name_source_migration.py
The TransactionCase below additionally checks real JSONB updates under Odoo.
"""
import copy
import importlib.util
import json
from pathlib import Path
import unittest


_PATH = Path(__file__).resolve().parents[1] / "migrations" / "19.0.3.5.0" / "pre-migrate.py"
_SPEC = importlib.util.spec_from_file_location("mdl_name_source_pre_migration_350", _PATH)
migration = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(migration)


def _row(**values):
    return {
        "id": 1, "active": True, "mdl_catalog_managed": True,
        "name": {"en_US": "Window Panel"},
        "mdl_group_default_name": {"en_US": "Window"},
        "mdl_group_name_override": None, "mdl_model_name_override": None,
        "mdl_native_name_override": None, "mdl_model_as_attribute": False,
        "default_code": "ORIGINAL-001", "bom_ids": [11, 12],
        "write_date": "2026-09-13 01:02:03", "other_data": {"price": 125.0},
        **values,
    }


class _Cursor:
    """Assert the migration's narrowly scoped SQL contract without an ORM."""
    def __init__(self, rows):
        self.rows = {r["id"]: copy.deepcopy(r) for r in rows}
        self.result = None
        self.updates = []
        self.selects = 0

    def execute(self, statement, params):
        sql = " ".join(statement.split())
        if sql.startswith("SELECT id, name,"):
            assert "WHERE mdl_catalog_managed IS TRUE AND id > %s" in sql
            assert "active =" not in sql and "active IS" not in sql
            assert sql.endswith("ORDER BY id LIMIT 500")
            columns = ("id",) + migration._SOURCE_COLUMNS + ("mdl_model_as_attribute", migration._STORED_BASE_COLUMN)
            selected = [r for rid, r in sorted(self.rows.items())
                        if rid > params[0] and r["mdl_catalog_managed"]][:500]
            self.result = [tuple(copy.deepcopy(r.get(c)) for c in columns) for r in selected]
            self.selects += 1
        elif sql == "UPDATE product_template SET mdl_group_default_name = %s::jsonb WHERE id = %s":
            value, record_id = params
            self.rows[record_id]["mdl_group_default_name"] = json.loads(value)
            self.updates.append(record_id)
            self.result = None
        else:
            raise AssertionError("Unexpected migration SQL: " + sql)

    def fetchall(self):
        assert self.result is not None
        return self.result


class TestNameSourceMigrationFormula(unittest.TestCase):
    def test_native_override_precedence_and_intentional_empty(self):
        original = _row(
            mdl_group_name_override={"en_US": "Ignored group"},
            mdl_model_name_override={"en_US": "Ignored model"},
            mdl_native_name_override={
                "en_US": "  Direct\nname / [25mm]  ", "he_IL": "—", "ar_001": "اسم مباشر",
            },
        )
        self.assertEqual(migration._materialized_names(original), {
            "en_US": "Direct name / [25mm]", "he_IL": "", "ar_001": "اسم مباشر",
        })

    def test_per_field_english_fallback_and_explicit_empty_translation(self):
        original = _row(
            name={"en_US": "Window Panel", "he_IL": "חלון כנף"},
            mdl_group_default_name={"en_US": "Window", "he_IL": "חלון"},
            mdl_group_name_override={"en_US": "Custom group", "he_IL": ""},
            mdl_model_name_override={"en_US": "", "he_IL": "—", "ar_001": "طراز"},
        )
        expected = {"en_US": "Custom group Panel", "he_IL": "חלון", "ar_001": "Custom group طراز"}
        names = migration._materialized_names(original)
        self.assertEqual(names, expected)
        self.assertEqual(migration._translated(names, "fr_FR"), "Custom group Panel")
        self.assertEqual(migration._old_base_name(original, "fr_FR"), "Custom group Panel")

    def test_model_attribute_excludes_legacy_title_but_not_group_override(self):
        original = _row(
            mdl_model_as_attribute=True,
            mdl_group_name_override={"en_US": "  Legacy   window ", "he_IL": "חלון"},
            mdl_model_name_override={"en_US": "Never include this"},
        )
        self.assertEqual(migration._materialized_names(original), {
            "en_US": "Legacy window", "he_IL": "חלון",
        })

    def test_group_prefix_removal_uses_original_source_not_override(self):
        self.assertEqual(migration._materialized_names(_row(
            mdl_group_name_override={"en_US": "Door"},
        )), {"en_US": "Door Panel"})
        # A shared prefix inside a word must not be removed.
        self.assertEqual(migration._materialized_names(_row(
            name={"en_US": "Windowpane"},
        )), {"en_US": "Window Windowpane"})
        self.assertEqual(migration._materialized_names(_row(
            name={"en_US": "Window"},
        )), {"en_US": "Window"})

    def test_empty_and_unicode_text_preserve_punctuation(self):
        original = _row(
            name={"en_US": "Unrelated title"},
            mdl_group_default_name={"en_US": "—", "he_IL": " \n "},
            mdl_group_name_override={"en_US": "—"},
            mdl_model_name_override={"en_US": "—"},
        )
        self.assertEqual(migration._materialized_names(original), {"en_US": "", "he_IL": ""})
        text = "חלון / [24מ״מ] / \u2066L\u2069"
        self.assertEqual(migration._materialized_names(_row(
            mdl_native_name_override={"en_US": text},
        )), {"en_US": text})

    def test_languages_come_from_all_inputs_including_inactive_language(self):
        original = _row(
            mdl_native_name_override={"en_US": "", "de_DE": "Fenster"},
            mdl_model_name_override={"en_US": None, "he_IL": "כנף"},
        )
        self.assertEqual(migration._materialized_names(original), {
            "en_US": "Window Panel", "de_DE": "Fenster", "he_IL": "Window כנף",
        })

    def test_scalar_legacy_storage_and_json_null_fallback(self):
        self.assertEqual(migration._materialized_names(_row(
            name="Window Panel", mdl_group_default_name="Window",
            mdl_group_name_override={"en_US": "Door", "he_IL": None},
        )), {"en_US": "Door Panel", "he_IL": "Door Panel"})

    def test_stale_legacy_inputs_cannot_rename_the_actual_stored_name(self):
        original = _row(
            mdl_model_as_attribute=True,
            mdl_group_default_name={"en_US": "חלון אלומיניום"},
            mdl_native_name_override={
                "en_US": "חלון אלומיניום דור חדש 1700 כנף על כנף", "he_IL": "חלון אלומיניום הזזה",
            },
            mdl_effective_base_name={"en_US": "חלון אלומיניום", "he_IL": "חלון אלומיניום הזזה"},
        )
        self.assertNotEqual(migration._old_base_name(original, "en_US"), "חלון אלומיניום")
        self.assertEqual(migration._materialized_names(original), {
            "en_US": "חלון אלומיניום", "he_IL": "חלון אלומיניום הזזה",
        })
        self.assertEqual(migration._translated(migration._materialized_names(original), "ar_001"), "חלון אלומיניום")

    def test_stored_blank_and_null_never_introduce_a_title_prefix(self):
        self.assertEqual(migration._materialized_names(_row(
            mdl_effective_base_name={"en_US": "Existing", "he_IL": "", "ar_001": None},
        )), {"en_US": "Existing", "he_IL": "", "ar_001": "Existing"})
        self.assertEqual(migration._materialized_names(_row(
            mdl_effective_base_name=None,
            mdl_native_name_override={"en_US": "Must not restore", "he_IL": "לא להוסיף"},
        )), {"en_US": "", "he_IL": ""})

    def test_missing_stored_language_uses_stored_english_not_translated_legacy_inputs(self):
        self.assertEqual(migration._materialized_names(_row(
            mdl_effective_base_name={"en_US": "Preserved current base"},
            mdl_native_name_override={"en_US": "Stale English", "he_IL": "שם אחר"},
        )), {"en_US": "Preserved current base", "he_IL": "Preserved current base"})

    def test_migration_is_idempotent_when_stored_base_and_legacy_inputs_disagree(self):
        cursor = _Cursor([_row(
            mdl_group_name_override={"en_US": "Legacy override"},
            mdl_effective_base_name={"en_US": "Existing exact base"},
        )])
        with self.assertLogs(migration._logger, level="WARNING"):
            migration.migrate(cursor, "19.0.3.4.9")
        after_first = copy.deepcopy(cursor.rows)
        with self.assertLogs(migration._logger, level="WARNING"):
            migration.migrate(cursor, "19.0.3.4.9")
        self.assertEqual(cursor.rows, after_first)
        self.assertEqual(cursor.updates, [1])

    def test_literal_stored_em_dash_fails_instead_of_silently_omitting_it(self):
        cursor = _Cursor([_row(id=37, mdl_effective_base_name={"en_US": "Existing", "he_IL": " — "})])
        before = copy.deepcopy(cursor.rows)
        with self.assertRaisesRegex(RuntimeError, "product group 37"):
            migration.migrate(cursor, "19.0.3.4.9")
        self.assertEqual(cursor.rows, before)
        self.assertEqual(cursor.updates, [])

    def test_includes_archived_skips_unmanaged_and_only_changes_visible_source(self):
        records = [
            _row(id=1, mdl_effective_base_name={"en_US": "Window Panel"}),
            _row(id=2, active=False, mdl_native_name_override={"en_US": "Archived / special"},
                 mdl_effective_base_name={"en_US": "Archived / special"}),
            _row(id=3, mdl_catalog_managed=False),
            _row(id=4, mdl_model_as_attribute=True, mdl_effective_base_name={"en_US": "Window"}),
        ]
        cursor = _Cursor(records)
        migration.migrate(cursor, "19.0.3.4.9")
        self.assertEqual(cursor.updates, [1, 2])
        self.assertEqual(cursor.rows[1]["mdl_group_default_name"], {"en_US": "Window Panel"})
        self.assertEqual(cursor.rows[2]["mdl_group_default_name"], {"en_US": "Archived / special"})
        for old in records:
            new = copy.deepcopy(cursor.rows[old["id"]])
            new["mdl_group_default_name"] = old["mdl_group_default_name"]
            self.assertEqual(new, old)

    def test_upgrade_is_keyset_batched_without_missing_archived_records(self):
        cursor = _Cursor([_row(id=i, active=bool(i % 2), mdl_effective_base_name={"en_US": "Window Panel"}) for i in range(1, 504)])
        migration.migrate(cursor, "19.0.3.4.9")
        self.assertEqual(cursor.updates, list(range(1, 504)))
        self.assertEqual(cursor.selects, 3)

    def test_new_install_does_not_run_old_data_conversion(self):
        cursor = _Cursor([_row()])
        migration.migrate(cursor, None)
        self.assertEqual(cursor.selects, 0)
        self.assertEqual(cursor.updates, [])


try:
    from odoo.tests import tagged
    from odoo.tests.common import TransactionCase
except ModuleNotFoundError:
    TransactionCase = None


if TransactionCase is not None:
    @tagged("post_install", "-at_install")
    class TestNameSourceMigrationDatabase(TransactionCase):
        def test_sql_preserves_titles_legacy_inputs_products_and_archives(self):
            templates = self.env["product.template"].with_context(
                skip_mdl_catalog_sync=True, mdl_defer_variant_rebuild=True,
            ).create([
                {"name": "Upgrade active fixture", "default_code": "UPGRADE-A"},
                {"name": "Upgrade archived fixture", "default_code": "UPGRADE-B", "active": False},
                {"name": "Upgrade ordinary fixture", "default_code": "UPGRADE-C"},
            ])
            self.env.flush_all()
            for template, managed in zip(templates, (True, True, False)):
                self.env.cr.execute(
                    """UPDATE product_template
                          SET name = %s::jsonb, mdl_group_default_name = %s::jsonb,
                              mdl_group_name_override = %s::jsonb,
                              mdl_model_name_override = %s::jsonb,
                              mdl_native_name_override = %s::jsonb,
                              mdl_effective_base_name = %s::jsonb,
                              mdl_model_as_attribute = FALSE,
                              mdl_catalog_managed = %s
                        WHERE id = %s""",
                    (json.dumps({"en_US": "Window Panel", "he_IL": "חלון כנף"}),
                     json.dumps({"en_US": "Window", "he_IL": "חלון"}),
                     json.dumps({"en_US": "Custom window", "he_IL": ""}),
                     json.dumps({"en_US": "", "he_IL": "—"}),
                     json.dumps({"en_US": "", "ar_001": "اسم محفوظ"}),
                     json.dumps({"en_US": "Actually displayed base", "he_IL": "", "ar_001": "اسم محفوظ"}),
                     managed, template.id),
                )

            def snapshot():
                self.env.cr.execute("SELECT id, to_jsonb(t) FROM product_template t WHERE id = ANY(%s) ORDER BY id", (templates.ids,))
                template_rows = dict(self.env.cr.fetchall())
                self.env.cr.execute("SELECT id, to_jsonb(p) FROM product_product p WHERE product_tmpl_id = ANY(%s) ORDER BY id", (templates.ids,))
                return template_rows, dict(self.env.cr.fetchall())

            before_templates, before_products = snapshot()
            migration.migrate(self.env.cr, "19.0.3.4.9")
            after_templates, after_products = snapshot()
            self.assertEqual(after_products, before_products)
            expected_names = {"en_US": "Actually displayed base", "he_IL": "", "ar_001": "اسم محفوظ"}
            for template, managed in zip(templates, (True, True, False)):
                old, new = before_templates[template.id], after_templates[template.id]
                if managed:
                    self.assertEqual(new["mdl_group_default_name"], expected_names)
                    new = {**new, "mdl_group_default_name": old["mdl_group_default_name"]}
                self.assertEqual(new, old)
            self.env.invalidate_all(flush=False)


if __name__ == "__main__":
    unittest.main()
