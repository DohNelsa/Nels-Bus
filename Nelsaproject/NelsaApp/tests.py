import json
from datetime import timedelta

from django.contrib.auth.models import Permission, User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AdminAuditLog, Booking, BookingGroup, Bus, NotificationJob, Passenger, Route, Schedule


class HardeningTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="u1", password="pw12345", email="u1@example.com")
        self.staff = User.objects.create_user(
            username="staff1", password="pw12345", email="staff@example.com", is_staff=True
        )
        self.bus = Bus.objects.create(bus_number="BUS-001", bus_type="Standard", capacity=40, is_available=True)
        self.route = Route.objects.create(
            start_location="Douala",
            end_location="Yaounde",
            distance=240,
            duration=4,
            price=5000,
        )
        now = timezone.now()
        self.schedule = Schedule.objects.create(
            bus=self.bus,
            route=self.route,
            departure_time=now + timedelta(days=1),
            arrival_time=now + timedelta(days=1, hours=4),
            price=5000,
            is_available=True,
        )
        self.schedule2 = Schedule.objects.create(
            bus=self.bus,
            route=self.route,
            departure_time=now + timedelta(days=2),
            arrival_time=now + timedelta(days=2, hours=4),
            price=5200,
            is_available=True,
        )
        self.passenger = Passenger.objects.create(name="P One", email="u1@example.com", phone="+237675315422")

    def _grant(self, user: User, codename: str):
        p = Permission.objects.get(codename=codename, content_type__app_label="NelsaApp")
        user.user_permissions.add(p)

    @override_settings(
        PAYMENT_WEBHOOK_SECRET="whsec-test",
        PAYMENT_WEBHOOK_HMAC_SECRET="hmac-test",
        PAYMENT_WEBHOOK_MAX_SKEW_SECONDS=300,
    )
    def test_webhook_replay_nonce_blocked(self):
        bg = BookingGroup.objects.create(
            passenger=self.passenger,
            schedule=self.schedule,
            total_amount=5000,
            status="Pending",
            transaction_verified=False,
        )
        payload = {
            "event_id": "evt_1",
            "provider": "GENERIC",
            "booking_group_id": bg.id,
            "transaction_id": "txn_1",
            "payment_method": "MOMO",
            "status": "SUCCESS",
            "amount": "5000",
        }
        body = json.dumps(payload).encode("utf-8")
        import hashlib
        import hmac

        sig = hmac.new(b"hmac-test", body, hashlib.sha256).hexdigest()
        headers = {
            "HTTP_X_PAYMENT_WEBHOOK_SECRET": "whsec-test",
            "HTTP_X_WEBHOOK_BODY_SIGNATURE": sig,
            "HTTP_X_WEBHOOK_TIMESTAMP": str(int(timezone.now().timestamp())),
            "HTTP_X_WEBHOOK_NONCE": "nonce-abc",
            "content_type": "application/json",
        }
        r1 = self.client.post(reverse("payment_webhook"), data=body, **headers)
        self.assertEqual(r1.status_code, 200)
        r2 = self.client.post(reverse("payment_webhook"), data=body, **headers)
        self.assertEqual(r2.status_code, 409)

    def test_rbac_blocks_staff_without_permission(self):
        self.client.login(username="staff1", password="pw12345")
        resp = self.client.get(reverse("admin_payment_webhooks"))
        self.assertNotEqual(resp.status_code, 200)
        self.assertTrue(AdminAuditLog.objects.filter(action="access_denied").exists())

    @override_settings(
        WHATSAPP_ENABLED=True,
        WHATSAPP_PROVIDER="mock",
        WHATSAPP_ADMIN_HANDOFF=True,
        NOTIFICATION_FLUSH_JOBS_INLINE=True,
    )
    def test_superuser_can_confirm_and_cancel_without_ops_group(self):
        su = User.objects.create_superuser(username="su1", password="pw12345", email="su@example.com")
        self.client.login(username="su1", password="pw12345")
        bg = BookingGroup.objects.create(
            passenger=self.passenger,
            schedule=self.schedule,
            total_amount=5000,
            status="Pending",
            transaction_id="",
            transaction_verified=False,
        )
        Booking.objects.create(
            passenger=self.passenger,
            schedule=self.schedule,
            seat_number=9,
            status="Pending",
            booking_group=bg,
        )
        detail = self.client.get(reverse("admin_booking_detail", kwargs={"booking_group_id": bg.id}))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Confirm reservation")
        self.assertNotContains(detail, "Missing confirm permission")

        confirm = self.client.post(reverse("admin_confirm_booking", kwargs={"booking_group_id": bg.id}))
        self.assertEqual(confirm.status_code, 302)
        bg.refresh_from_db()
        self.assertEqual(bg.status, "Confirmed")
        self.assertTrue(bg.transaction_verified)
        self.assertTrue(bg.transaction_id)

        cancel = self.client.post(reverse("admin_cancel_booking", kwargs={"booking_group_id": bg.id}))
        self.assertEqual(cancel.status_code, 302)
        bg.refresh_from_db()
        self.assertEqual(bg.status, "Cancelled")

    def test_state_changing_admin_actions_are_post_only(self):
        self._grant(self.staff, "cancel_bookinggroup")
        self.client.login(username="staff1", password="pw12345")
        bg = BookingGroup.objects.create(passenger=self.passenger, schedule=self.schedule, total_amount=5000, status="Pending")
        resp = self.client.get(reverse("admin_cancel_booking", kwargs={"booking_group_id": bg.id}))
        self.assertEqual(resp.status_code, 405)

    def test_book_seat_duplicate_blocked(self):
        self.client.login(username="u1", password="pw12345")
        payload = {
            "schedule_id": self.schedule.id,
            "seat_ids": [5],
            "customer_name": "User One",
            "customer_phone": "+237675315422",
        }
        r1 = self.client.post(reverse("book_seats_api"), data=json.dumps(payload), content_type="application/json")
        self.assertEqual(r1.status_code, 200)
        body1 = r1.json()
        self.assertTrue(body1.get("success"))

        r2 = self.client.post(reverse("book_seats_api"), data=json.dumps(payload), content_type="application/json")
        body2 = r2.json()
        self.assertFalse(body2.get("success"))

    @override_settings(
        WHATSAPP_ENABLED=True,
        WHATSAPP_PROVIDER="mock",
        WHATSAPP_ADMIN_HANDOFF=False,
        NOTIFICATION_FLUSH_JOBS_INLINE=True,
    )
    def test_confirm_booking_sends_whatsapp(self):
        self._grant(self.staff, "confirm_bookinggroup")
        self.client.login(username="staff1", password="pw12345")
        bg = BookingGroup.objects.create(
            passenger=self.passenger,
            schedule=self.schedule,
            total_amount=5000,
            status="Pending",
            payment_waived=True,
            transaction_id="WAIVED-1",
            transaction_verified=True,
            customer_phone="+237675315422",
        )
        Booking.objects.create(
            passenger=self.passenger,
            schedule=self.schedule,
            seat_number=4,
            status="Pending",
            booking_group=bg,
        )
        resp = self.client.post(reverse("admin_confirm_booking", kwargs={"booking_group_id": bg.id}))
        self.assertEqual(resp.status_code, 302)
        bg.refresh_from_db()
        self.assertEqual(bg.status, "Confirmed")
        self.assertEqual(bg.whatsapp_status, "SENT")
        self.assertTrue(bg.whatsapp_receipt_code)

    @override_settings(
        WHATSAPP_ENABLED=True,
        WHATSAPP_PROVIDER="mock",
        WHATSAPP_ADMIN_HANDOFF=False,
        NOTIFICATION_FLUSH_JOBS_INLINE=True,
    )
    def test_verify_payment_then_confirm_sends_whatsapp(self):
        self._grant(self.staff, "confirm_bookinggroup")
        self._grant(self.staff, "access_admin_bookings")
        self.client.login(username="staff1", password="pw12345")
        bg = BookingGroup.objects.create(
            passenger=self.passenger,
            schedule=self.schedule,
            total_amount=5000,
            status="Pending",
            transaction_id="MM-12345",
            transaction_verified=False,
            customer_phone="+237675315422",
        )
        Booking.objects.create(
            passenger=self.passenger,
            schedule=self.schedule,
            seat_number=4,
            status="Pending",
            booking_group=bg,
        )
        verify = self.client.post(
            reverse("admin_verify_payment", kwargs={"booking_group_id": bg.id}),
            data={"transaction_id": "MM-12345"},
        )
        self.assertEqual(verify.status_code, 302)
        bg.refresh_from_db()
        self.assertTrue(bg.transaction_verified)

        resp = self.client.post(reverse("admin_confirm_booking", kwargs={"booking_group_id": bg.id}))
        self.assertEqual(resp.status_code, 302)
        bg.refresh_from_db()
        self.assertEqual(bg.status, "Confirmed")
        self.assertEqual(bg.whatsapp_status, "SENT")

    @override_settings(WHATSAPP_ENABLED=True, WHATSAPP_ADMIN_HANDOFF=True, NOTIFICATION_FLUSH_JOBS_INLINE=True)
    def test_confirm_redirects_to_whatsapp_handoff(self):
        self._grant(self.staff, "confirm_bookinggroup")
        self._grant(self.staff, "access_admin_bookings")
        self.client.login(username="staff1", password="pw12345")
        bg = BookingGroup.objects.create(
            passenger=self.passenger,
            schedule=self.schedule,
            total_amount=5000,
            status="Pending",
            transaction_id="16643528543",
            transaction_verified=False,
            customer_phone="+237675315422",
        )
        Booking.objects.create(
            passenger=self.passenger,
            schedule=self.schedule,
            seat_number=4,
            status="Pending",
            booking_group=bg,
        )
        resp = self.client.post(reverse("admin_confirm_booking", kwargs={"booking_group_id": bg.id}))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(f"/admin-bookings/{bg.id}/", resp.url)
        follow = self.client.get(resp.url)
        self.assertEqual(follow.status_code, 200)
        self.assertContains(follow, "Open WhatsApp")
        self.assertContains(follow, "wa.me")
        bg.refresh_from_db()
        self.assertEqual(bg.status, "Confirmed")
        self.assertTrue(bg.whatsapp_receipt_code)

    @override_settings(WHATSAPP_ENABLED=True, WHATSAPP_ADMIN_HANDOFF=True, NOTIFICATION_FLUSH_JOBS_INLINE=True)
    def test_confirm_without_txn_succeeds_manual_flow(self):
        self._grant(self.staff, "confirm_bookinggroup")
        self.client.login(username="staff1", password="pw12345")
        bg = BookingGroup.objects.create(
            passenger=self.passenger,
            schedule=self.schedule,
            total_amount=5000,
            status="Pending",
            transaction_id="",
            transaction_verified=False,
            customer_phone="+237675315422",
        )
        Booking.objects.create(
            passenger=self.passenger,
            schedule=self.schedule,
            seat_number=4,
            status="Pending",
            booking_group=bg,
        )
        resp = self.client.post(reverse("admin_confirm_booking", kwargs={"booking_group_id": bg.id}))
        self.assertEqual(resp.status_code, 302)
        bg.refresh_from_db()
        self.assertEqual(bg.status, "Confirmed")
        self.assertTrue(bg.transaction_verified)
        self.assertEqual(bg.transaction_id, f"MANUAL-{bg.id}")
        self.assertIn(f"/admin-bookings/{bg.id}/", resp.url)

    @override_settings(WHATSAPP_ENABLED=True, WHATSAPP_ADMIN_HANDOFF=True, NOTIFICATION_FLUSH_JOBS_INLINE=True)
    def test_confirm_auto_verifies_when_txn_present(self):
        self._grant(self.staff, "confirm_bookinggroup")
        self.client.login(username="staff1", password="pw12345")
        bg = BookingGroup.objects.create(
            passenger=self.passenger,
            schedule=self.schedule,
            total_amount=5000,
            status="Pending",
            transaction_id="MM-99999",
            transaction_verified=False,
            customer_phone="+237675315422",
        )
        Booking.objects.create(
            passenger=self.passenger,
            schedule=self.schedule,
            seat_number=4,
            status="Pending",
            booking_group=bg,
        )
        resp = self.client.post(reverse("admin_confirm_booking", kwargs={"booking_group_id": bg.id}))
        self.assertEqual(resp.status_code, 302)
        bg.refresh_from_db()
        self.assertTrue(bg.transaction_verified)
        self.assertEqual(bg.status, "Confirmed")
        self.assertIn(f"/admin-bookings/{bg.id}/", resp.url)

    @override_settings(
        WHATSAPP_ENABLED=True,
        WHATSAPP_PROVIDER="mock",
        WHATSAPP_ADMIN_HANDOFF=False,
        NOTIFICATION_FLUSH_JOBS_INLINE=True,
    )
    def test_verify_and_confirm_in_one_step(self):
        self._grant(self.staff, "confirm_bookinggroup")
        self._grant(self.staff, "access_admin_bookings")
        self.client.login(username="staff1", password="pw12345")
        bg = BookingGroup.objects.create(
            passenger=self.passenger,
            schedule=self.schedule,
            total_amount=5000,
            status="Pending",
            transaction_id="MM-54321",
            transaction_verified=False,
            customer_phone="+237675315422",
        )
        Booking.objects.create(
            passenger=self.passenger,
            schedule=self.schedule,
            seat_number=5,
            status="Pending",
            booking_group=bg,
        )
        resp = self.client.post(
            reverse("admin_verify_and_confirm_booking", kwargs={"booking_group_id": bg.id}),
            data={"transaction_id": "MM-54321"},
        )
        self.assertEqual(resp.status_code, 302)
        bg.refresh_from_db()
        self.assertTrue(bg.transaction_verified)
        self.assertEqual(bg.status, "Confirmed")
        self.assertEqual(bg.whatsapp_status, "SENT")

    def test_cancel_booking_post_works(self):
        self._grant(self.staff, "cancel_bookinggroup")
        self.client.login(username="staff1", password="pw12345")
        bg = BookingGroup.objects.create(
            passenger=self.passenger,
            schedule=self.schedule,
            total_amount=5000,
            status="Pending",
        )
        resp = self.client.post(reverse("admin_cancel_booking", kwargs={"booking_group_id": bg.id}))
        self.assertEqual(resp.status_code, 302)
        bg.refresh_from_db()
        self.assertEqual(bg.status, "Cancelled")

    def test_booking_requires_phone(self):
        self.client.login(username="u1", password="pw12345")
        payload = {
            "schedule_id": self.schedule.id,
            "seat_ids": [5],
            "customer_name": "User One",
            "customer_phone": "",
        }
        resp = self.client.post(reverse("book_seats_api"), data=json.dumps(payload), content_type="application/json")
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json().get("success"))

    def test_rebook_flow_creates_new_group_and_cancels_old(self):
        self._grant(self.staff, "manage_refunds_rebooks")
        self._grant(self.staff, "access_admin_bookings")
        self.client.login(username="staff1", password="pw12345")
        old = BookingGroup.objects.create(
            passenger=self.passenger,
            schedule=self.schedule,
            total_amount=5000,
            status="Confirmed",
            transaction_id="txn-old",
            transaction_verified=True,
        )
        Booking.objects.create(passenger=self.passenger, schedule=self.schedule, seat_number=1, status="Confirmed", booking_group=old)

        resp = self.client.post(
            reverse("admin_rebook_booking", kwargs={"booking_group_id": old.id}),
            data={"schedule_id": str(self.schedule2.id), "seat_numbers": "2"},
        )
        self.assertEqual(resp.status_code, 302)
        old.refresh_from_db()
        self.assertEqual(old.status, "Cancelled")
        new_group = BookingGroup.objects.get(rebooking_of=old)
        self.assertEqual(new_group.status, "Pending")
        self.assertTrue(new_group.payment_waived)
        self.assertEqual(new_group.bookings.count(), 1)

    @override_settings(VERIFY_SMS_RECEIPT_RATE_LIMIT_PER_MIN=2)
    def test_verify_sms_receipt_rate_limited(self):
        for _ in range(2):
            r = self.client.get(reverse("verify_sms_receipt", kwargs={"code": "GAR-UNKNOWN"}))
            self.assertIn(r.status_code, (404, 400))
        r3 = self.client.get(reverse("verify_sms_receipt", kwargs={"code": "GAR-UNKNOWN"}))
        self.assertEqual(r3.status_code, 429)

    def test_user_role_change_is_audited(self):
        target = User.objects.create_user(username="target", password="pw12345", email="target@example.com")
        self._grant(self.staff, "manage_staff_users")
        self.client.login(username="staff1", password="pw12345")
        resp = self.client.post(reverse("admin_users"), data={"action": "make_staff", "user_id": str(target.id)})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            AdminAuditLog.objects.filter(action="user_make_staff", target_type="User", target_id=str(target.id)).exists()
        )


class SeatLayoutTests(TestCase):
    def test_front_row_driver_aisle_and_right_seats(self):
        from .seating import build_layout_grid

        row0 = build_layout_grid(70)[0]
        types = [c.get("type") for c in row0["cells"]]
        seats = [c["seat_number"] for c in row0["cells"] if c.get("type") == "seat"]
        self.assertEqual(types, ["seat", "aisle", "seat", "seat"])
        self.assertEqual(seats, [1, 2, 3])

    def test_second_row_three_left_aisle_two_right(self):
        from .seating import build_layout_grid

        row1 = build_layout_grid(70)[1]
        seats = [c["seat_number"] for c in row1["cells"] if c.get("type") == "seat"]
        self.assertEqual(seats, [4, 5, 6, 7, 8])
        self.assertEqual(
            [c.get("type") for c in row1["cells"]],
            ["seat", "seat", "seat", "aisle", "seat", "seat"],
        )

    def test_third_row_numbering(self):
        from .seating import build_layout_grid

        row2 = build_layout_grid(70)[2]
        seats = [c["seat_number"] for c in row2["cells"] if c.get("type") == "seat"]
        self.assertEqual(seats, [9, 10, 11, 12, 13])

    def test_get_seats_api_returns_aisle_layout(self):
        bus = Bus.objects.create(bus_number="BUS-LAY", bus_type="Standard", capacity=70, is_available=True)
        route = Route.objects.create(
            start_location="Douala",
            end_location="Yaounde",
            distance=240,
            duration=4,
            price=5000,
        )
        now = timezone.now()
        schedule = Schedule.objects.create(
            bus=bus,
            route=route,
            departure_time=now + timedelta(days=1),
            arrival_time=now + timedelta(days=1, hours=4),
            price=5000,
            is_available=True,
        )
        resp = Client().get(reverse("get_seats", kwargs={"schedule_id": schedule.id}))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("layout", {}).get("type"), "3-plus-2")
        row1_seats = [
            c["seat_number"]
            for c in data["rows"][1]["cells"]
            if c.get("type") == "seat" and c.get("seat_number")
        ]
        self.assertEqual(row1_seats, [4, 5, 6, 7, 8])
        self.assertEqual(data.get("layout_version"), 5)
