import copy
import io
import unittest
from unittest.mock import Mock, patch

import app as campus_app
from PIL import Image
from werkzeug.security import check_password_hash

INITIAL_REPORTS = copy.deepcopy(campus_app.DEMO_REPORTS)
INITIAL_LOCATIONS = copy.deepcopy(campus_app.DEMO_LOCATIONS)
INITIAL_WORK_LOGS = copy.deepcopy(campus_app.DEMO_WORK_LOGS)


class CampusCareTests(unittest.TestCase):
    def setUp(self):
        campus_app.app.config.update(TESTING=True)
        self.client = campus_app.app.test_client()
        campus_app.DEMO_REPORTS[:] = copy.deepcopy(INITIAL_REPORTS)
        campus_app.DEMO_LOCATIONS[:] = copy.deepcopy(INITIAL_LOCATIONS)
        campus_app.DEMO_WORK_LOGS[:] = copy.deepcopy(INITIAL_WORK_LOGS)
        campus_app.DEMO_NEXT_ID = 2000
        campus_app.DEMO_NEXT_LOCATION_ID = 5
        campus_app.DEMO_SETTINGS.update(
            {
                "public_board_enabled": True,
                "anonymous_reports_enabled": True,
                **{
                    f"sla_hours_{urgency.lower()}": ""
                    for urgency in campus_app.SLA_URGENCIES
                },
            }
        )

    def csrf_token(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as session:
            return session["csrf_token"]

    def set_role(self, role):
        token = self.csrf_token()
        response = self.client.post(
            "/demo-role", data={"csrf_token": token, "role": role}
        )
        self.assertEqual(response.status_code, 302)

    def test_dashboard_and_board_render(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        board = self.client.get("/?view=board")
        self.assertEqual(board.status_code, 200)
        self.assertIn(b"Campus board", board.data)
        self.assertIn(b"Projector flickers during lectures", board.data)
        self.assertNotIn(b"Dr. Samuel Mensah", board.data)
        self.assertNotIn(b"Technician is checking the power connection.", board.data)

    def test_report_lists_include_progress_and_operational_filters(self):
        dashboard = self.client.get("/")
        self.assertIn(b"Technician is checking the power connection.", dashboard.data)
        self.assertIn(b'data-status-filter', dashboard.data)
        self.assertIn(b'data-place-filter', dashboard.data)
        self.assertIn(b'data-density-toggle', dashboard.data)

    def test_public_board_and_summary_do_not_require_sign_in(self):
        self.client.delete_cookie("session")
        board = self.client.get("/?view=board")
        self.assertEqual(board.status_code, 200)
        detail = self.client.get("/report/1041?public=1")
        self.assertEqual(detail.status_code, 200)
        self.assertNotIn(b"Two desks near the front row", detail.data)
        self.assertNotIn(b"Dr. Samuel Mensah", detail.data)
        self.assertNotIn(b"Kofi Boateng", detail.data)

    def test_public_detail_hides_reporter_and_description(self):
        response = self.client.get("/report/1041?public=1")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Loose desk row needs repair", response.data)
        self.assertNotIn(b"Two desks near the front row", response.data)
        self.assertNotIn(b"Dr. Samuel Mensah", response.data)

    def test_reporter_cannot_open_another_personal_report(self):
        self.assertEqual(self.client.get("/report/1041").status_code, 403)

    def test_maintenance_cannot_update_an_unassigned_report(self):
        self.set_role("maintenance")
        token = self.csrf_token()
        response = self.client.post(
            "/report/1040/update",
            data={
                "csrf_token": token,
                "status": "Resolved",
                "note": "Unauthorized update attempt.",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_student_can_submit_and_track_report(self):
        token = self.csrf_token()
        response = self.client.post(
            "/report",
            data={
                "csrf_token": token,
                "title": "Broken fan in room 12",
                "category": "Electrical",
                "urgency": "High",
                "location_id": "1",
                "description": "The ceiling fan does not turn on.",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Broken fan in room 12", response.data)
        self.assertIn(b"Report received.", response.data)
        self.assertIn(b"Block C", response.data)

    def test_user_supplied_html_is_escaped(self):
        token = self.csrf_token()
        response = self.client.post(
            "/report",
            data={
                "csrf_token": token,
                "title": "<script>alert(1)</script>",
                "category": "Electrical",
                "urgency": "Normal",
                "location_id": "1",
                "description": "A test issue with encoded markup in its title.",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"&lt;script&gt;alert(1)&lt;/script&gt;", response.data)
        self.assertNotIn(b"<script>alert(1)</script>", response.data)

    def test_uploaded_file_must_be_a_real_image(self):
        token = self.csrf_token()
        report_count = len(campus_app.DEMO_REPORTS)
        response = self.client.post(
            "/report",
            data={
                "csrf_token": token,
                "title": "Invalid image upload",
                "category": "Electrical",
                "urgency": "Normal",
                "location_id": "1",
                "description": "The uploaded file is not a real image.",
                "photo": (io.BytesIO(b"not an image"), "photo.png"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"valid JPG, PNG, or WebP image", response.data)
        self.assertEqual(len(campus_app.DEMO_REPORTS), report_count)

    def test_uploaded_images_are_reencoded(self):
        original = io.BytesIO()
        image = Image.new("RGB", (4, 4), "red")
        image.info["comment"] = b"private metadata"
        image.save(original, format="PNG")
        original.seek(0)
        token = self.csrf_token()
        response = self.client.post(
            "/report",
            data={
                "csrf_token": token,
                "title": "Valid image upload",
                "category": "Electrical",
                "urgency": "Normal",
                "location_id": "1",
                "description": "The uploaded image is a valid PNG.",
                "photo": (original, "photo.png"),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        report = next(item for item in campus_app.DEMO_REPORTS if item["title"] == "Valid image upload")
        image_path = campus_app.UPLOAD_DIR / report["photo_name"]
        try:
            self.assertTrue(image_path.exists())
            self.assertNotIn(b"private metadata", image_path.read_bytes())
            with Image.open(image_path) as saved:
                self.assertEqual(saved.format, "PNG")
        finally:
            image_path.unlink(missing_ok=True)

    def test_report_form_uses_building_and_room_directory(self):
        response = self.client.get("/report")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'name="location_id"', response.data)
        self.assertIn(b'<optgroup label="Block C">', response.data)
        self.assertNotIn(b'name="location"', response.data)

        token = self.csrf_token()
        invalid = self.client.post(
            "/report",
            data={
                "csrf_token": token,
                "title": "Unlisted location",
                "category": "Electrical",
                "urgency": "Normal",
                "location_id": "9999",
                "description": "This location is not in the approved directory.",
            },
        )
        self.assertEqual(invalid.status_code, 200)
        self.assertEqual(len(campus_app.DEMO_REPORTS), len(INITIAL_REPORTS))

    def test_admin_can_manage_campus_locations(self):
        self.set_role("admin")
        self.assertEqual(self.client.get("/admin/locations").status_code, 200)
        token = self.csrf_token()
        response = self.client.post(
            "/admin/locations",
            data={
                "csrf_token": token,
                "action": "add",
                "building": "Science Centre",
                "room": "Lab 2",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            any(
                location["building"] == "Science Centre"
                and location["room"] == "Lab 2"
                for location in campus_app.DEMO_LOCATIONS
            )
        )
        token = self.csrf_token()
        response = self.client.post(
            "/admin/locations",
            data={
                "csrf_token": token,
                "action": "toggle",
                "location_id": "5",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        inactive = next(
            location
            for location in campus_app.DEMO_LOCATIONS
            if location["id"] == 5
        )
        self.assertFalse(inactive["active"])

    def test_roles_see_their_workflows(self):
        self.set_role("maintenance")
        maintenance = self.client.get("/")
        self.assertEqual(maintenance.status_code, 200)
        self.assertIn(b"Work queue", maintenance.data)
        self.assertIn(b"Projector flickers during lectures", maintenance.data)

        self.set_role("admin")
        admin = self.client.get("/")
        self.assertEqual(admin.status_code, 200)
        self.assertIn(b"All campus reports", admin.data)
        self.assertEqual(self.client.get("/admin/users").status_code, 200)
        self.assertEqual(self.client.get("/admin/settings").status_code, 200)
        self.assertEqual(self.client.get("/admin/analytics").status_code, 200)
        self.assertEqual(self.client.get("/admin/locations").status_code, 200)

    def test_admin_can_control_board_and_anonymous_reporting(self):
        self.set_role("admin")
        token = self.csrf_token()
        response = self.client.post(
            "/admin/settings",
            data={"csrf_token": token, "anonymous_reports_enabled": "on"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(campus_app.DEMO_SETTINGS["public_board_enabled"])
        self.assertTrue(campus_app.DEMO_SETTINGS["anonymous_reports_enabled"])

        token = self.csrf_token()
        response = self.client.post(
            "/admin/settings",
            data={"csrf_token": token, "public_board_enabled": "on"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(campus_app.DEMO_SETTINGS["public_board_enabled"])
        self.assertFalse(campus_app.DEMO_SETTINGS["anonymous_reports_enabled"])
        self.set_role("student")
        form = self.client.get("/report")
        self.assertEqual(form.status_code, 200)
        self.assertNotIn(b'name="anonymous"', form.data)

    def test_admin_can_set_response_targets_and_view_overdue_analytics(self):
        self.set_role("admin")
        token = self.csrf_token()
        response = self.client.post(
            "/admin/settings",
            data={"csrf_token": token, "sla_hours_urgent": "1"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        analytics = self.client.get(
            "/admin/analytics?start=2026-11-04&end=2026-11-04"
        )
        self.assertEqual(analytics.status_code, 200)
        self.assertIn(b"response target configured", analytics.data)
        self.assertIn(b"UPS-26-1040", analytics.data)

    def test_database_settings_store_numeric_response_targets_without_boolean_coercion(self):
        with self.client.session_transaction() as session:
            session["user_id"] = 4
            session["auth_version"] = 0
            session["csrf_token"] = "test-csrf"
        with (
            patch.object(campus_app, "DEMO_MODE", False),
            patch.object(
                campus_app,
                "_query",
                return_value={
                    "id": 4,
                    "name": "Facilities Office",
                    "email": "facilities@example.edu",
                    "role": "admin",
                    "session_version": 0,
                },
            ),
            patch.object(campus_app, "_execute") as execute,
        ):
            response = self.client.post(
                "/admin/settings",
                data={
                    "csrf_token": "test-csrf",
                    "public_board_enabled": "on",
                    "anonymous_reports_enabled": "on",
                    "sla_hours_urgent": "4",
                },
            )
        self.assertEqual(response.status_code, 302)
        stored = [call.args[1] for call in execute.call_args_list]
        self.assertIn(("sla_hours_urgent", "4"), stored)
        self.assertIn(("sla_hours_high", ""), stored)

    def test_postgresql_insert_returns_generated_id(self):
        connection = Mock()
        cursor = connection.cursor.return_value
        cursor.description = ("id",)
        cursor.fetchone.return_value = {"id": 45}
        with patch.object(campus_app, "_db", return_value=connection):
            inserted_id = campus_app._execute(
                "INSERT INTO users (...) VALUES (...) RETURNING id"
            )
        self.assertEqual(inserted_id, 45)
        connection.commit.assert_called_once()
        cursor.close.assert_called_once()

    def test_postgresql_statement_without_returning_id_returns_none(self):
        connection = Mock()
        cursor = connection.cursor.return_value
        cursor.description = None
        with patch.object(campus_app, "_db", return_value=connection):
            result = campus_app._execute("UPDATE users SET name = %s", ("Updated",))
        self.assertIsNone(result)
        connection.commit.assert_called_once()

    def test_analytics_includes_feedback_and_resolution_time(self):
        token = self.csrf_token()
        feedback = self.client.post(
            "/report/1039/feedback",
            data={"csrf_token": token, "rating": "5", "note": "Excellent repair."},
            follow_redirects=True,
        )
        self.assertEqual(feedback.status_code, 200)
        self.set_role("admin")
        analytics = self.client.get(
            "/admin/analytics?start=2026-10-29&end=2026-10-29"
        )
        self.assertIn(b"26.5 hours", analytics.data)
        self.assertIn(b"5.0 / 5", analytics.data)

    def test_analytics_are_restricted_to_administrators(self):
        self.assertEqual(self.client.get("/admin/analytics").status_code, 403)
        self.set_role("maintenance")
        self.assertEqual(self.client.get("/admin/analytics").status_code, 403)

    def test_work_logs_are_restricted_and_private(self):
        token = self.csrf_token()
        denied = self.client.post(
            "/report/1042/work-log",
            data={
                "csrf_token": token,
                "labor_minutes": "30",
                "parts_used": "Cable ties",
                "note": "Repaired the cable.",
            },
        )
        self.assertEqual(denied.status_code, 403)

        self.set_role("maintenance")
        token = self.csrf_token()
        saved = self.client.post(
            "/report/1042/work-log",
            data={
                "csrf_token": token,
                "labor_minutes": "30",
                "parts_used": "Cable ties",
                "note": "Secured the projector cable.",
                "follow_up_at": "2026-11-10",
            },
            follow_redirects=True,
        )
        self.assertEqual(saved.status_code, 200)
        self.assertIn(b"Secured the projector cable.", saved.data)

        self.set_role("student")
        private_detail = self.client.get("/report/1042")
        self.assertEqual(private_detail.status_code, 200)
        self.assertNotIn(b"Secured the projector cable.", private_detail.data)
        public_detail = self.client.get("/report/1042?public=1")
        self.assertEqual(public_detail.status_code, 200)
        self.assertNotIn(b"Secured the projector cable.", public_detail.data)

    def test_photo_pruning_obeys_configured_retention(self):
        campus_app.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        filename = "retention-test.png"
        photo_path = campus_app.UPLOAD_DIR / filename
        photo_path.write_bytes(b"test photo")
        report = next(item for item in campus_app.DEMO_REPORTS if item["id"] == 1042)
        report["photo_name"] = filename
        try:
            with patch.object(campus_app, "PHOTO_RETENTION_DAYS", 1):
                result = self.client.application.test_cli_runner().invoke(
                    campus_app.prune_photos
                )
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIsNone(report["photo_name"])
            self.assertFalse(photo_path.exists())
        finally:
            photo_path.unlink(missing_ok=True)

    def test_university_sso_login_redirects_to_configured_provider(self):
        sso = Mock()
        sso.authorize_redirect.return_value = "https://identity.example.edu/authorize"
        with (
            patch.object(campus_app, "DEMO_MODE", False),
            patch.object(campus_app, "university_sso", sso),
        ):
            response = self.client.get("/login")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers["Location"], "https://identity.example.edu/authorize"
        )
        self.assertTrue(
            sso.authorize_redirect.call_args.args[0].endswith(
                "/auth/university/callback"
            )
        )

    def test_university_sso_requires_verified_email_and_provisioned_account(self):
        sso = Mock()
        sso.authorize_access_token.return_value = {
            "userinfo": {
                "sub": "university-user-1",
                "email": "amara@example.edu",
                "email_verified": False,
            }
        }
        with (
            patch.object(campus_app, "DEMO_MODE", False),
            patch.object(campus_app, "university_sso", sso),
            patch.object(campus_app, "_query") as query,
        ):
            response = self.client.get("/auth/university/callback")
        self.assertEqual(response.status_code, 403)
        query.assert_not_called()

    def test_university_sso_links_verified_identity_to_existing_account(self):
        sso = Mock()
        sso.authorize_access_token.return_value = {
            "userinfo": {
                "sub": "university-user-1",
                "email": "amara@example.edu",
                "email_verified": True,
            }
        }
        with (
            patch.object(campus_app, "DEMO_MODE", False),
            patch.object(campus_app, "university_sso", sso),
            patch.object(
                campus_app,
                "_query",
                side_effect=[
                    {"id": 41, "oidc_sub": None, "session_version": 0},
                    {"oidc_sub": "university-user-1"},
                ],
            ),
            patch.object(campus_app, "_execute") as execute,
        ):
            response = self.client.get("/auth/university/callback")
        self.assertEqual(response.status_code, 302)
        execute.assert_called_once_with(
            "UPDATE users SET oidc_sub = %s WHERE id = %s AND oidc_sub IS NULL",
            ("university-user-1", 41),
        )
        with self.client.session_transaction() as session:
            self.assertEqual(session["user_id"], 41)
            self.assertEqual(session["auth_version"], 0)

    def test_invalid_csrf_is_rejected(self):
        response = self.client.post(
            "/report",
            data={
                "csrf_token": "invalid",
                "title": "Broken fan",
                "category": "Electrical",
                "urgency": "Normal",
                "location": "Block A",
                "description": "The fan is broken.",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_login_rate_limit_blocks_before_account_lookup(self):
        with self.client.session_transaction() as session:
            session["csrf_token"] = "test-csrf"
        with (
            patch.object(campus_app, "DEMO_MODE", False),
            patch.object(campus_app, "university_sso", None),
            patch.object(campus_app, "_auth_attempt_allowed", return_value=False),
            patch.object(campus_app, "_query") as query,
        ):
            response = self.client.post(
                "/login",
                data={
                    "csrf_token": "test-csrf",
                    "email": "user@example.edu",
                    "password": "incorrect",
                },
            )
        self.assertEqual(response.status_code, 429)
        query.assert_not_called()

    def test_signup_stores_a_password_hash(self):
        with self.client.session_transaction() as session:
            session["csrf_token"] = "test-csrf"
        with (
            patch.object(campus_app, "DEMO_MODE", False),
            patch.object(campus_app, "university_sso", None),
            patch.object(campus_app, "SMTP_ENABLED", True),
            patch.object(campus_app, "_auth_attempt_allowed", return_value=True),
            patch.object(campus_app, "_execute", side_effect=[45, 45]) as execute,
            patch.object(campus_app, "_send_verification_email") as send_email,
        ):
            response = self.client.post(
                "/signup",
                data={
                    "csrf_token": "test-csrf",
                    "name": "Test Student",
                    "email": "student@example.edu",
                    "role": "student",
                    "password": "a sufficiently long password",
                },
            )
        self.assertEqual(response.status_code, 302)
        stored_hash = execute.call_args_list[0].args[1][2]
        self.assertNotEqual(stored_hash, "a sufficiently long password")
        self.assertTrue(check_password_hash(stored_hash, "a sufficiently long password"))
        send_email.assert_called_once_with(45, "student@example.edu")
        with self.client.session_transaction() as session:
            self.assertNotIn("user_id", session)

    def test_password_login_requires_verified_email(self):
        password_hash = campus_app.generate_password_hash("correct horse battery")
        with self.client.session_transaction() as session:
            session["csrf_token"] = "test-csrf"
        with (
            patch.object(campus_app, "DEMO_MODE", False),
            patch.object(campus_app, "university_sso", None),
            patch.object(campus_app, "SMTP_ENABLED", True),
            patch.object(campus_app, "_auth_attempt_allowed", return_value=True),
            patch.object(
                campus_app,
                "_query",
                return_value={
                    "id": 42,
                    "name": "Student",
                    "email": "student@example.edu",
                    "role": "student",
                    "password_hash": password_hash,
                    "email_verified_at": None,
                    "session_version": 0,
                },
            ),
        ):
            response = self.client.post(
                "/login",
                data={
                    "csrf_token": "test-csrf",
                    "email": "student@example.edu",
                    "password": "correct horse battery",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Verify your email before signing in", response.data)
        with self.client.session_transaction() as session:
            self.assertNotIn("user_id", session)

    def test_verified_password_login_stores_session_version(self):
        password_hash = campus_app.generate_password_hash("correct horse battery")
        with self.client.session_transaction() as session:
            session["csrf_token"] = "test-csrf"
        with (
            patch.object(campus_app, "DEMO_MODE", False),
            patch.object(campus_app, "university_sso", None),
            patch.object(campus_app, "_auth_attempt_allowed", return_value=True),
            patch.object(
                campus_app,
                "_query",
                return_value={
                    "id": 42,
                    "name": "Student",
                    "email": "student@example.edu",
                    "role": "student",
                    "password_hash": password_hash,
                    "email_verified_at": campus_app.datetime.now(),
                    "session_version": 3,
                },
            ),
            patch.object(campus_app, "_execute"),
        ):
            response = self.client.post(
                "/login",
                data={
                    "csrf_token": "test-csrf",
                    "email": "student@example.edu",
                    "password": "correct horse battery",
                },
            )
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertEqual(session["user_id"], 42)
            self.assertEqual(session["auth_version"], 3)

    def test_changed_session_version_invalidates_existing_session(self):
        with campus_app.app.test_request_context("/"):
            campus_app.session["user_id"] = 42
            campus_app.session["auth_version"] = 1
            with (
                patch.object(campus_app, "DEMO_MODE", False),
                patch.object(
                    campus_app,
                    "_query",
                    return_value={
                        "id": 42,
                        "name": "Student",
                        "email": "student@example.edu",
                        "role": "student",
                        "session_version": 2,
                    },
                ),
            ):
                self.assertIsNone(campus_app._current_user())
            self.assertNotIn("user_id", campus_app.session)

    def test_email_verification_token_is_consumed_on_post(self):
        with self.client.session_transaction() as session:
            session["csrf_token"] = "test-csrf"
        with (
            patch.object(campus_app, "DEMO_MODE", False),
            patch.object(campus_app, "university_sso", None),
            patch.object(campus_app, "_execute", return_value=45) as execute,
        ):
            response = self.client.post(
                "/verify-email/test-token",
                data={"csrf_token": "test-csrf", "token": "test-token"},
            )
        self.assertEqual(response.status_code, 302)
        self.assertIn("email_verified_at = CURRENT_TIMESTAMP", execute.call_args.args[0])
        self.assertEqual(
            execute.call_args.args[1],
            (campus_app.hashlib.sha256(b"test-token").hexdigest(),),
        )

    def test_auth_token_persists_only_a_digest(self):
        with (
            patch.object(campus_app.secrets, "token_urlsafe", return_value="raw-token"),
            patch.object(campus_app, "_execute", return_value=45) as execute,
        ):
            token = campus_app._issue_auth_token(45, "verify_email")
        self.assertEqual(token, "raw-token")
        self.assertEqual(
            execute.call_args.args[1][0],
            campus_app.hashlib.sha256(b"raw-token").hexdigest(),
        )
        self.assertNotIn("raw-token", execute.call_args.args[0])

    def test_password_reset_request_uses_generic_response(self):
        with self.client.session_transaction() as session:
            session["csrf_token"] = "test-csrf"
        with (
            patch.object(campus_app, "DEMO_MODE", False),
            patch.object(campus_app, "university_sso", None),
            patch.object(campus_app, "SMTP_ENABLED", True),
            patch.object(campus_app, "_auth_attempt_allowed", return_value=True),
            patch.object(
                campus_app,
                "_query",
                return_value={"id": 45},
            ),
            patch.object(campus_app, "_send_password_reset_email") as send_email,
        ):
            response = self.client.post(
                "/password-reset",
                data={
                    "csrf_token": "test-csrf",
                    "email": "student@example.edu",
                },
                follow_redirects=True,
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"If a verified account uses that address", response.data)
        send_email.assert_called_once_with(45, "student@example.edu")

    def test_password_reset_changes_hash_and_revokes_sessions(self):
        with self.client.session_transaction() as session:
            session["csrf_token"] = "test-csrf"
        with (
            patch.object(campus_app, "DEMO_MODE", False),
            patch.object(campus_app, "university_sso", None),
            patch.object(campus_app, "_execute", side_effect=[45, None]) as execute,
        ):
            response = self.client.post(
                "/password-reset/test-token",
                data={
                    "csrf_token": "test-csrf",
                    "password": "a new sufficiently long password",
                    "password_confirmation": "a new sufficiently long password",
                },
            )
        self.assertEqual(response.status_code, 302)
        self.assertIn("session_version = session_version + 1", execute.call_args_list[0].args[0])
        self.assertTrue(
            check_password_hash(
                execute.call_args_list[0].args[1][1],
                "a new sufficiently long password",
            )
        )
        self.assertIn("DELETE FROM auth_tokens", execute.call_args_list[1].args[0])

    def test_login_attempt_buckets_are_hashed_and_database_backed(self):
        with campus_app.app.test_request_context(
            "/", environ_base={"REMOTE_ADDR": "192.0.2.10"}
        ):
            with (
                patch.object(campus_app, "_execute") as execute,
                patch.object(campus_app, "_query", return_value={"attempts": 11}),
            ):
                self.assertFalse(campus_app._auth_attempt_allowed("login"))
            bucket_hash = execute.call_args.args[1][0]
            self.assertEqual(len(bucket_hash), 64)
            self.assertNotIn("192.0.2.10", bucket_hash)

    def test_demo_admin_cannot_assign_an_unknown_account(self):
        self.set_role("admin")
        token = self.csrf_token()
        response = self.client.post(
            "/report/1042/assign",
            data={"csrf_token": token, "assignee_id": "987"},
        )
        self.assertEqual(response.status_code, 400)
        report = next(item for item in campus_app.DEMO_REPORTS if item["id"] == 1042)
        self.assertEqual(report["assigned_to"], 3)

    def test_production_redirects_insecure_requests_to_canonical_origin(self):
        with (
            patch.object(campus_app, "APP_ENV", "production"),
            patch.object(campus_app, "PUBLIC_BASE_URL", "https://campus.example.edu"),
        ):
            response = self.client.get("/?view=board")
        self.assertEqual(response.status_code, 308)
        self.assertEqual(response.headers["Location"], "https://campus.example.edu/?view=board")

    def test_security_headers_are_present(self):
        response = self.client.get("/")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])

    def test_production_https_responses_include_hsts(self):
        with patch.object(campus_app, "APP_ENV", "production"):
            response = self.client.get("/", base_url="https://campus.example.edu")
        self.assertEqual(
            response.headers["Strict-Transport-Security"], "max-age=31536000"
        )

    def test_feedback_and_staff_status_update(self):
        self.set_role("maintenance")
        token = self.csrf_token()
        response = self.client.post(
            "/report/1042/update",
            data={
                "csrf_token": token,
                "status": "Resolved",
                "note": "The power connection has been repaired.",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Resolved", response.data)

        self.set_role("student")
        token = self.csrf_token()
        response = self.client.post(
            "/report/1042/feedback",
            data={"csrf_token": token, "rating": "5", "note": "Fixed quickly."},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Feedback received", response.data)

    def test_form_has_accessible_photo_and_anonymity_controls(self):
        response = self.client.get("/report")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'name="photo"', response.data)
        self.assertIn(b'accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp"', response.data)
        self.assertIn(b'name="anonymous"', response.data)


if __name__ == "__main__":
    unittest.main()
