import importlib
import json
import os
import tempfile
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

    def _load_state(self):
        return json.loads(self.data_file.read_text(encoding="utf-8"))

    def _login_session(self):
        with self.client.session_transaction() as sess:
            sess["user"] = {"id": 1, "name": "Vitoria Uardon"}

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
        self.assertEqual(len(state["tarefas"]), 1)
        self.assertEqual(state["tarefas"][0]["origem"], "automacao")

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


if __name__ == "__main__":
    unittest.main()
