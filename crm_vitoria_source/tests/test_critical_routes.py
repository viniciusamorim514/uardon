import importlib
import hashlib
import hmac
import json
import os
import re
import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path


BASE_DATA = {
    "users": [
        {
            "id": 1,
            "username": "vitoria",
            "email": "vit.cs99@gmail.com",
            "password": "123456",
            "name": "Vitoria Uardon",
            "role": "admin",
        }
    ],
    "config": {"nomeArquiteta": "Vitoria Uardon", "estudio": "Studio Arq. & Int."},
    "leads": [],
    "clientes": [],
    "projetos": [],
    "tarefas": [],
    "eventos": [],
    "despesas": [],
    "feedbacks": [],
    "dismissed_notifications": [],
    "audit_logs": [],
}


class CriticalRoutesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        base_path = Path(cls.tmpdir.name)
        cls.data_file = base_path / "test_data.json"
        cls.upload_dir = base_path / "uploads"
        cls.upload_dir.mkdir(parents=True, exist_ok=True)
        cls.data_file.write_text(json.dumps(BASE_DATA), encoding="utf-8")

        os.environ["CRM_DATA_FILE"] = str(cls.data_file)
        os.environ["CRM_UPLOAD_DIR"] = str(cls.upload_dir)
        os.environ["TURNSTILE_FAIL_OPEN"] = "true"
        os.environ["TURNSTILE_SECRET_KEY"] = ""
        os.environ["PUBLIC_LEAD_HMAC_SECRET"] = ""
        os.environ["DATABASE_URL"] = ""

        cls.crm = importlib.import_module("crm_vitoria_source.app")
        cls.app = cls.crm.app
        cls.app.config.update(TESTING=True)
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()

    def setUp(self):
        self.crm.save_data(deepcopy(BASE_DATA))
        self.crm.PUBLIC_LEAD_RATE_LIMIT.clear()
        self.crm.PUBLIC_LEAD_CONTACT_RATE_LIMIT.clear()
        os.environ["PUBLIC_LEAD_HMAC_SECRET"] = ""

    def _load_state(self):
        return json.loads(self.data_file.read_text(encoding="utf-8"))

    def _login_session(self):
        with self.client.session_transaction() as sess:
            sess["user"] = {"id": 1, "name": "Vitoria Uardon", "role": "admin"}

    def _login_as(self, role):
        with self.client.session_transaction() as sess:
            sess["user"] = {"id": 2, "name": "Teste", "role": role}

    def test_public_lead_creation_creates_lead_and_task(self):
        payload = {
            "name": "Maria Silva",
            "phone": "(47) 99999-1111",
            "project_type": "Residencial",
            "city": "Balneario Camboriu",
            "message": "Quero reforma completa",
            "metadata": {
                "current_url": "https://uardon.com.br",
                "referrer": "https://instagram.com",
                "utm_source": "instagram",
            },
        }
        response = self.client.post("/v1/leads", json=payload)
        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        self.assertTrue(data["ok"])

        state = self._load_state()
        self.assertEqual(len(state["leads"]), 1)
        self.assertEqual(state["leads"][0]["nome"], "Maria Silva")
        self.assertEqual(state["leads"][0]["status"], "Novo")
        self.assertEqual(state["leads"][0]["origem"], "Landing Page")
        self.assertTrue(state["leads"][0]["public_fingerprint"])
        self.assertEqual(len(state["tarefas"]), 1)
        self.assertEqual(state["tarefas"][0]["origem"], "automacao")
        self.assertEqual(
            [item["event"] for item in state["audit_logs"]],
            ["landing_submit", "api_accept", "db_write", "crm_visible"],
        )

    def test_public_lead_duplicate_replay_is_idempotent(self):
        payload = {
            "name": "Maria Silva",
            "phone": "(47) 99999-1111",
            "project_type": "Residencial",
        }
        first = self.client.post("/v1/leads", json=payload)
        second = self.client.post("/v1/leads", json=payload)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.get_json()["duplicate"])

        state = self._load_state()
        self.assertEqual(len(state["leads"]), 1)
        self.assertEqual(len(state["tarefas"]), 1)

    def test_public_lead_requires_signature_when_secret_is_configured(self):
        os.environ["PUBLIC_LEAD_HMAC_SECRET"] = "test-secret"
        payload = {
            "name": "Maria Silva",
            "phone": "(47) 99999-1111",
            "project_type": "Residencial",
        }
        unsigned = self.client.post("/v1/leads", json=payload)
        self.assertEqual(unsigned.status_code, 401)

        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        timestamp = str(int(time.time()))
        signature = hmac.new(
            os.environ["PUBLIC_LEAD_HMAC_SECRET"].encode("utf-8"),
            timestamp.encode("utf-8") + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        signed = self.client.post(
            "/v1/leads",
            data=body,
            content_type="application/json",
            headers={"X-Uardon-Timestamp": timestamp, "X-Uardon-Signature": f"sha256={signature}"},
        )
        self.assertEqual(signed.status_code, 201)

    def test_public_lead_requires_hmac_in_production(self):
        original_env = self.crm.CRM_ENV
        try:
            self.crm.CRM_ENV = "production"
            os.environ["PUBLIC_LEAD_HMAC_SECRET"] = ""
            payload = {
                "name": "Maria Silva",
                "phone": "(47) 99999-1111",
                "project_type": "Residencial",
            }
            response = self.client.post("/v1/leads", json=payload)
            self.assertEqual(response.status_code, 401)
            body = response.get_json()
            self.assertFalse(body["ok"])
            self.assertEqual(body["code"], "invalid_signature")
        finally:
            self.crm.CRM_ENV = original_env

    def test_all_templates_have_no_mojibake_tokens(self):
        templates_dir = Path(__file__).resolve().parents[1] / "templates"
        pattern = re.compile(r"(Ã.|Â.|\ufffd)")
        for template_path in templates_dir.rglob("*.html"):
            content = template_path.read_text(encoding="utf-8")
            self.assertIsNone(pattern.search(content), f"Mojibake token found in template: {template_path.name}")

    def test_dashboard_response_has_no_mojibake_tokens(self):
        self._login_session()
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        pattern = re.compile(r"(Ã.|Â.|\ufffd)")
        self.assertIsNone(pattern.search(body), "Mojibake token found in dashboard response")

    def test_fix_mojibake_text_normalizes_common_broken_tokens(self):
        self.assertEqual(self.crm.fix_mojibake_text("Ol, Maria! Tudo bem por a?"), "Olá, Maria! Tudo bem por aí?")
        self.assertEqual(self.crm.fix_mojibake_text("vocę e duas opçőes"), "você e duas opções")
        self.assertEqual(self.crm.fix_mojibake_text("Fico ŕ disposiçăo"), "Fico à disposição")

    def test_build_technical_health_aggregates_audit_logs(self):
        sample = {
            "audit_logs": [
                {"created_at": "2026-05-23T10:00:00", "event": "landing_submit", "status": "ok", "code": "", "lead_id": 11},
                {"created_at": "2026-05-23T10:00:01", "event": "crm_visible", "status": "ok", "code": "", "lead_id": 11},
                {"created_at": "2026-05-23T10:02:00", "event": "landing_submit", "status": "blocked", "code": "turnstile_failed"},
                {"created_at": "2026-05-23T10:03:00", "event": "api_accept", "status": "duplicate", "code": "idempotent_replay"},
                {"created_at": "2026-05-23T10:04:00", "event": "smoke_check", "status": "ok", "code": "smoke_ok"},
                {"created_at": "2026-05-23T10:05:00", "event": "smoke_check", "status": "failed", "code": "smoke_failed"},
            ]
        }
        report = self.crm.build_technical_health(sample, window_hours=99999)
        self.assertEqual(report["totals"]["events"], 6)
        self.assertEqual(report["totals"]["status_4xx"], 1)
        self.assertEqual(report["totals"]["turnstile_failed"], 1)
        self.assertEqual(report["totals"]["duplicate_replay"], 1)
        self.assertEqual(report["totals"]["lead_ingestion_fail"], 1)
        self.assertEqual(report["totals"]["avg_latency_seconds"], 1.0)
        self.assertEqual(report["totals"]["smoke_total"], 2)
        self.assertEqual(report["totals"]["smoke_failed"], 1)

    def test_public_lead_invalid_phone_returns_400(self):
        payload = {
            "name": "Maria Silva",
            "phone": "1234",
            "project_type": "Residencial",
        }
        response = self.client.post("/v1/leads", json=payload)
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["code"], "invalid_phone")

        state = self._load_state()
        self.assertEqual(len(state["leads"]), 0)

    def test_mark_lead_contacted_updates_stage(self):
        state = deepcopy(BASE_DATA)
        state["leads"] = [
            {
                "id": 1,
                "nome": "Lead Teste",
                "tel": "47999991111",
                "origem": "Landing Page",
                "status": "Novo",
                "etapa": "Novo",
                "ultima_interacao": "",
            }
        ]
        self.crm.save_data(state)
        self._login_session()

        response = self.client.post("/leads/1/contato")
        self.assertEqual(response.status_code, 302)

        updated = self._load_state()
        self.assertEqual(updated["leads"][0]["status"], "Em contato")
        self.assertEqual(updated["leads"][0]["etapa"], "Contato feito")

    def test_create_expense_and_mark_paid(self):
        self._login_session()
        response = self.client.post(
            "/financeiro/despesas/novo",
            data={
                "descricao": "Assinatura software",
                "categoria": "Software",
                "valor": "199.90",
                "vencimento": "2026-05-30",
                "status": "Pendente",
            },
        )
        self.assertEqual(response.status_code, 302)

        state = self._load_state()
        self.assertEqual(len(state["despesas"]), 1)
        expense_id = state["despesas"][0]["id"]
        self.assertEqual(state["despesas"][0]["status"], "Pendente")

        response = self.client.post(f"/financeiro/despesas/{expense_id}/pago")
        self.assertEqual(response.status_code, 302)
        updated = self._load_state()
        self.assertEqual(updated["despesas"][0]["status"], "Pago")
        self.assertTrue(updated["despesas"][0]["pago"])

    def test_mark_project_payment_paid(self):
        state = deepcopy(BASE_DATA)
        state["clientes"] = [{"id": 1, "nome": "Cliente A", "tel": "47999991111"}]
        state["projetos"] = [
            {
                "id": 1,
                "nome": "Projeto A",
                "cliente_id": 1,
                "status": "Planejamento",
                "pagamentos": [
                    {"id": 1, "descricao": "Parcela 1", "valor": "1500", "vencimento": "2026-05-20", "status": "Pendente", "pago": False, "pago_em": ""}
                ],
            }
        ]
        self.crm.save_data(state)
        self._login_session()

        response = self.client.post("/projetos/1/pagamentos/1/pago")
        self.assertEqual(response.status_code, 302)

        updated = self._load_state()
        payment = updated["projetos"][0]["pagamentos"][0]
        self.assertEqual(payment["status"], "Pago")
        self.assertTrue(payment["pago"])

    def test_leitura_cannot_create_lead(self):
        self._login_as("leitura")
        response = self.client.post(
            "/leads/novo",
            data={"nome": "Lead Teste", "tel": "47999990000", "etapa": "Novo"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/", response.headers.get("Location", ""))
        state = self._load_state()
        self.assertEqual(len(state["leads"]), 0)

    def test_comercial_cannot_edit_finance(self):
        self._login_as("comercial")
        response = self.client.post(
            "/financeiro/despesas/novo",
            data={
                "descricao": "Teste bloqueio",
                "categoria": "Software",
                "valor": "10",
                "vencimento": "2026-05-31",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        state = self._load_state()
        self.assertEqual(len(state["despesas"]), 0)


if __name__ == "__main__":
    unittest.main()

