from psycopg2 import sql


TRANSLATED_COLUMNS = {
    "product_template": (
        "mdl_group_default_name",
        "mdl_group_name_override",
        "mdl_model_name_override",
        "mdl_native_name_override",
        "mdl_native_name_source",
        "mdl_effective_base_name",
        "mdl_variant_base_name",
        "mdl_name_suffix",
    ),
    "product_product": ("mdl_generated_name",),
    "product_template_attribute_line": ("mdl_name_suffix",),
    "product_template_attribute_value": ("mdl_name_component_override",),
}


def migrate(cr, version):
    """Preserve existing text while enabling Odoo's translated JSON storage."""
    for table_name, column_names in TRANSLATED_COLUMNS.items():
        for column_name in column_names:
            cr.execute(
                """
                SELECT data_type
                  FROM information_schema.columns
                 WHERE table_schema = current_schema()
                   AND table_name = %s
                   AND column_name = %s
                """,
                (table_name, column_name),
            )
            row = cr.fetchone()
            if not row or row[0] == "jsonb":
                continue
            # Existing varchar indexes are not suitable for Odoo's translated
            # JSONB expression. The ORM recreates the requested index after
            # the field definition is loaded.
            cr.execute(
                sql.SQL("DROP INDEX IF EXISTS {index}").format(
                    index=sql.Identifier(
                        f"{table_name}_{column_name}_index"
                    )
                )
            )
            cr.execute(
                sql.SQL(
                    """
                    ALTER TABLE {table}
                    ALTER COLUMN {column} TYPE jsonb
                    USING CASE
                        WHEN {column} IS NULL THEN NULL
                        ELSE jsonb_build_object('en_US', {column}::text)
                    END
                    """
                ).format(
                    table=sql.Identifier(table_name),
                    column=sql.Identifier(column_name),
                )
            )
