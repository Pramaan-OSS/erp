"""Real database smoke checks. Run only on a disposable fake-only site."""
import json
import os
import subprocess
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid


def main():
    if os.environ.get("PRAMAAN_FAKE") != "1" or os.environ.get("PRAMAAN_API_KEY"):
        raise SystemExit("Use a disposable fake-only site with an empty key.")
    root = Path(os.environ.get("ERP_APP_ROOT", "/app"))
    os.chdir(root / ".runtime/bench/sites")
    import frappe
    from erpnext.pramaan import PramaanClient
    from erpnext.erp_integrations.pramaan import api, bank_transfer, pramaan_mail, signing
    from erpnext.erp_integrations.pramaan.configuration import configure_site

    frappe.init(site=os.environ["ERP_SITE_NAME"])
    frappe.connect()
    frappe.set_user("Administrator")

    class DatabaseChecks(unittest.TestCase):
        def tearDown(self):
            frappe.db.rollback()

        def test_database_engine(self):
            self.assertEqual(frappe.db.db_type, os.environ.get("ERP_DB", "mariadb"))

        def test_database_backup(self):
            host = os.environ.get("ERP_DB_HOST", "database")
            user = frappe.conf.db_user or frappe.conf.db_name
            env = os.environ.copy()
            if frappe.db.db_type == "postgres":
                env["PGPASSWORD"] = frappe.conf.db_password
                command = ["pg_dump", "--schema-only", "--no-owner", "--no-privileges", "-h", host,
                           "-U", user, frappe.conf.db_name]
            else:
                env["MYSQL_PWD"] = frappe.conf.db_password
                command = ["mariadb-dump", "--no-data", "--no-tablespaces", "--single-transaction",
                           "--skip-lock-tables", "-h", host, "-u", user, frappe.conf.db_name]
            result = subprocess.run(command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                    text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr)

        def test_site_configuration(self):
            configure_site()
            self.assertEqual(frappe.db.get_single_value("System Settings", "enable_telemetry"), 0)

        def test_customer_persistence(self):
            for doctype, field, name in [("Customer Group", "customer_group_name", "All Customer Groups"),
                                          ("Territory", "territory_name", "All Territories")]:
                if not frappe.db.exists(doctype, name):
                    frappe.get_doc({"doctype": doctype, field: name, "is_group": 1}).insert()
            group = "Database smoke " + uuid.uuid4().hex
            frappe.get_doc({"doctype": "Customer Group", "customer_group_name": group,
                            "parent_customer_group": "All Customer Groups", "is_group": 0}).insert()
            customer = frappe.get_doc({"doctype": "Customer", "customer_name": "Database smoke " + uuid.uuid4().hex,
                                       "customer_type": "Company", "customer_group": group,
                                       "territory": "All Territories"}).insert()
            self.assertEqual(frappe.get_doc("Customer", customer.name).customer_name, customer.customer_name)
            # Read the saved party through the permission-checked lookup endpoint.
            # The empty deployment key must stop the outside lookup after the read.
            self.assertIsNone(api.lookup_company("Customer", customer.name))

        def test_sign_in_settings(self):
            frappe.db.set_single_value("Sign-In Settings", "enabled", 0)
            self.assertEqual(signing.status(), {"enabled": False})
            self.assertFalse(signing._config()[0])

        def test_transfer_lock_and_persistence(self):
            request = frappe.get_doc({"doctype": "Payment Request", "name": "DB-" + uuid.uuid4().hex,
                                      "docstatus": 1, "payment_request_type": "Inward", "status": "Requested",
                                      "grand_total": 10.75, "outstanding_amount": 10.75, "currency": "GBP"})
            request.db_insert()
            self.assertEqual(bank_transfer.transfer(request.name), {"status": "not_created"})
            # Exercise the endpoint's real row lock and JSON write with a pending transfer.
            body = {"amount": 1075, "currency": "GBP"}
            request.db_set("bank_transfer_data", json.dumps({"ref": "fixture-transfer", "body": body}))
            service = PramaanClient(api_key="fixture-only", transport=lambda *a: (200, {
                "status": "awaiting_payment", "amount": 1075, "currency": "GBP"}))
            with patch.object(bank_transfer, "get_client", return_value=service):
                result = bank_transfer.transfer(request.name)
            self.assertEqual(result["status"], "awaiting_payment")
            self.assertIn("fixture-transfer", frappe.db.get_value("Payment Request", request.name, "bank_transfer_data"))

        def test_mail_delivery_persistence(self):
            communication = frappe.get_doc({"doctype": "Communication", "communication_type": "Communication",
                "communication_medium": "Email", "sent_or_received": "Sent", "sender": "sender@fixture.test",
                "recipients": "recipient@fixture.test", "subject": "Database smoke", "content": "Fixture"}).insert()
            outbox = frappe.get_doc({"doctype": "Pramaan Outbox", "capability": "email.send", "payload": "{}",
                "idempotency_key": str(uuid.uuid4()), "state": "Pending", "communication": communication.name,
                "requested_by": "Administrator"}).insert(ignore_permissions=True)
            service = PramaanClient(api_key="fixture-only", transport=lambda *a: (200, {
                "messageId": "fixture-message", "ref": "fixture-ref", "trackable": True}))
            try:
                with patch.object(pramaan_mail, "client", return_value=service):
                    pramaan_mail.deliver(outbox.name)
                self.assertEqual(frappe.db.get_value("Pramaan Outbox", outbox.name, "state"), "Accepted")
                self.assertEqual(frappe.db.get_value("Communication", communication.name, "pramaan_trackable"), 1)
            finally:
                frappe.db.rollback()
                # deliver commits its intent; remove only this check's fixture rows.
                frappe.db.delete("Pramaan Outbox", {"name": outbox.name})
                frappe.db.delete("Communication", {"name": communication.name})
                frappe.db.commit()

    try:
        with patch.object(PramaanClient, "_http", side_effect=AssertionError("Live calls forbidden")):
            result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(DatabaseChecks))
    finally:
        frappe.db.rollback()
        frappe.destroy()
    raise SystemExit(not result.wasSuccessful())


if __name__ == "__main__":
    main()
