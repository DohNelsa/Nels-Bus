from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("NelsaApp", "0025_booking_whatsapp_notifications"),
    ]

    operations = [
        migrations.AddField(
            model_name="bookinggroup",
            name="customer_phone",
            field=models.CharField(
                blank=True,
                help_text="WhatsApp/phone number entered at booking time (E.164, e.g. +237699123456).",
                max_length=20,
                null=True,
            ),
        ),
    ]
