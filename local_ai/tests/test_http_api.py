from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request

from local_ai.http_api import create_server

from .helpers import development_settings


class HttpApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = create_server(
            development_settings(host="127.0.0.1", port=0), port=0
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def _post(self, path: str, body: object) -> tuple[dict, object]:
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8")), response.headers

    def test_health(self) -> None:
        with urllib.request.urlopen(self.base_url + "/health", timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
            self.assertIn("ProjetoIC-LocalAI/0.8.0", response.headers["Server"])
        self.assertTrue(body["alive"])
        self.assertTrue(body["decision_ready"])
        self.assertFalse(body["scientific_ready"])
        self.assertEqual(body["service_version"], "0.8.0")

    def test_v9_body_and_provenance_headers(self) -> None:
        body, headers = self._post(
            "/v1/classify",
            {
                "titulo": "Lâmpada queimada",
                "descricao": "Lâmpada queimada na sala 4",
                "localizacao": "Sala 4",
            },
        )
        self.assertEqual(
            set(body),
            {"tipo", "executor", "categoria", "justificativa", "mensagem_solicitante", "confianca", "probabilidades"},
        )
        self.assertEqual(headers["X-Local-AI-Fallback"], "true")
        self.assertEqual(headers["X-Local-AI-Scientific-Eligible"], "false")

    def test_metadata_envelope_is_opt_in(self) -> None:
        body, _ = self._post(
            "/v1/classify?include_metadata=1",
            {
                "titulo": "Portão eletrônico",
                "descricao": "Portão automático não funciona na guarita 1",
                "localizacao": "Guarita 1",
            },
        )
        self.assertEqual(set(body), {"result", "metadata"})
        self.assertIn("trace_id", body["metadata"])
        self.assertEqual(
            body["metadata"]["decision_path"],
            "deterministic_specialized_asset",
        )
        self.assertFalse(body["metadata"]["fallback_used"])
        self.assertFalse(body["metadata"]["candidate_evaluation_eligible"])
        self.assertFalse(body["metadata"]["probabilistic_model_output"])
        self.assertEqual(
            body["metadata"]["probability_semantics"],
            "deterministic_policy_one_hot_not_model_probability",
        )

    def test_invalid_json_is_400(self) -> None:
        request = urllib.request.Request(
            self.base_url + "/v1/classify",
            data=b"{invalid",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(context.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
