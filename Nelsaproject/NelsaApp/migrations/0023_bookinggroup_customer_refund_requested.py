# Generated manually — production DB may already have NOT NULL column without Django state.

from django.db import migrations, models


def _column_exists(schema_editor, table_name: str, column_name: str) -> bool:
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        if connection.vendor == "sqlite":
            cursor.execute(f'PRAGMA table_info("{table_name}")')
            return any(row[1] == column_name for row in cursor.fetchall())
        if connection.vendor == "postgresql":
            cursor.execute(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = %s
                  AND column_name = %s
                """,
                [table_name.lower(), column_name.lower()],
            )
            return cursor.fetchone() is not None
    with connection.cursor() as cursor:
        if table_name not in connection.introspection.table_names(cursor):
            return False
        desc = connection.introspection.get_table_description(cursor, table_name)
        return any(getattr(d, "name", d[0]) == column_name for d in desc)


def add_customer_refund_requested_if_missing(apps, schema_editor):
    BookingGroup = apps.get_model("NelsaApp", "BookingGroup")
    table_name = BookingGroup._meta.db_table
    if _column_exists(schema_editor, table_name, "customer_refund_requested"):
        return

    field = models.BooleanField(
        default=False,
        db_index=True,
        help_text="True when the customer has requested a refund for this booking group.",
    )
    field.set_attributes_from_name("customer_refund_requested")
    schema_editor.add_field(BookingGroup, field)


class Migration(migrations.Migration):

    dependencies = [
        ("NelsaApp", "0022_bookinggroup_customer_notification_status"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="bookinggroup",
                    name="customer_refund_requested",
                    field=models.BooleanField(
                        default=False,
                        db_index=True,
                        help_text="True when the customer has requested a refund for this booking group.",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunPython(
                    add_customer_refund_requested_if_missing,
                    migrations.RunPython.noop,
                ),
            ],
        ),
    ]
