from psycopg2 import sql


TRANSLATED_COLUMNS = {
    "product_template": (
        "mdl_group_default_name",
        "mdl_group_name_override",
        "mdl_model_name_override",
        "mdl_native_name_override",
        "mdl_native_name_source",
    ),
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
