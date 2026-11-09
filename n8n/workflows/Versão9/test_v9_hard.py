"""Testes locais dos contratos de runtime da V9.

Esta bateria e deliberadamente estatica/mocada: importar ou executar o arquivo
nao cria chamados, nao escreve no PostgreSQL e nao chama webhooks reais. O E2E
opt-in fica em ``test_v9_runtime.py``.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import test_v9_runtime as runtime  # noqa: E402


WF04_PATH = SCRIPT_DIR / "V9-WF04-Decisao-Fiscal.json"
WF06_PATH = SCRIPT_DIR / "V9-WF06-Fila-IA.json"


def load_workflow(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def node(workflow: dict, name: str) -> dict:
    matches = [item for item in workflow["nodes"] if item.get("name") == name]
    if len(matches) != 1:
        raise AssertionError(f"Esperado exatamente um no {name!r}; obtido {len(matches)}")
    return matches[0]


def successors(workflow: dict, name: str, output: int = 0) -> list[str]:
    main = workflow.get("connections", {}).get(name, {}).get("main", [])
    if output >= len(main):
        return []
    return [connection["node"] for connection in main[output]]


def parameters_text(workflow: dict, name: str) -> str:
    return json.dumps(
        node(workflow, name).get("parameters", {}),
        ensure_ascii=False,
        sort_keys=True,
    )


class V9ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.wf04 = load_workflow(WF04_PATH)
        cls.wf06 = load_workflow(WF06_PATH)

    def test_wf06_usa_endpoint_atual_e_autenticacao_por_ambiente(self) -> None:
        webhook = node(self.wf06, "Webhook GLPI Fila")
        self.assertEqual(webhook["parameters"]["httpMethod"], "POST")
        self.assertEqual(
            webhook["parameters"]["path"], "glpi-ticket-fila-ia-v9"
        )
        preparar = parameters_text(self.wf06, "Preparar Entrada GLPI")
        self.assertIn("gateway n8n-gateway valida X-Webhook-Key", preparar)
        self.assertNotIn("GLPI_WEBHOOK_KEY", preparar)
        gateway = (SCRIPT_DIR.parents[2] / "n8n" / "proxies" / "n8n-gateway.conf.template").read_text(
            encoding="utf-8"
        )
        self.assertIn("location = /webhook/glpi-ticket-fila-ia-v9", gateway)
        self.assertIn('$http_x_webhook_key != "${GLPI_WEBHOOK_KEY}"', gateway)
        self.assertNotIn("glpi-ticket-novo-glpi-n8n-ic-2026", preparar)

    def test_wf04_get_renderiza_preview_sem_alcancar_nos_de_mutacao(self) -> None:
        webhook = node(self.wf04, "Webhook Fiscal Confirmação")
        self.assertEqual(webhook["parameters"]["httpMethod"], "GET")
        self.assertEqual(webhook["parameters"]["path"], "fiscal-confirmacao-v9")
        self.assertEqual(
            successors(self.wf04, "Webhook Fiscal Confirmação"),
            ["Renderizar Confirmação Fiscal"],
        )
        self.assertEqual(
            successors(self.wf04, "Renderizar Confirmação Fiscal"),
            ["Resp: Confirmação Fiscal"],
        )
        render = parameters_text(self.wf04, "Renderizar Confirmação Fiscal")
        self.assertIn('method=\\"post\\"', render)
        self.assertIn("/webhook/fiscal-decisao-fiscal-ic-2026", render)
        self.assertNotIn("UPDATE tickets_processados", render)
        self.assertNotIn("helpers.httpRequest", render)

    def test_wf04_post_exige_decisao_ticket_e_token(self) -> None:
        webhook = node(self.wf04, "Webhook Fiscal")
        self.assertEqual(webhook["parameters"]["httpMethod"], "POST")
        self.assertEqual(
            webhook["parameters"]["path"],
            "fiscal-decisao-fiscal-ic-2026",
        )
        extrair = parameters_text(self.wf04, "Extrair Decisão")
        for fragment in (
            "['confirmar','nao_duplicado'].includes(dec)",
            "/^[a-f0-9]{32,128}$/i.test(token)",
            "temChamado && decisaoValida && tokenValidoFormato",
        ):
            self.assertIn(fragment, extrair)

    def test_reserva_fiscal_e_atomica_contra_token_invalido_expirado_e_corrida(self) -> None:
        sql = parameters_text(self.wf04, "PG: Buscar Chamado")
        fragments = (
            "WITH alvo AS",
            "reservado AS",
            "UPDATE tickets_processados",
            "COALESCE(em_aprovacao_fiscal,FALSE)=TRUE",
            "COALESCE(decisao_fiscal,'')=''",
            "fiscal_decision_token='${token}'",
            "fiscal_token_expira_em > NOW()",
            "RETURNING",
            "NOT EXISTS (SELECT 1 FROM reservado)",
        )
        for fragment in fragments:
            self.assertIn(fragment, sql)
        self.assertNotIn("SELECT pg_sleep", sql)

    def test_validacao_distingue_expirado_invalido_replay_e_confirmacao(self) -> None:
        validar = parameters_text(self.wf04, "Validar Fiscal")
        for fragment in (
            "TOKEN_INVALIDO",
            "TOKEN_EXPIRADO",
            "CLIQUE_DUPLO",
            "JA_REGISTRADO",
            "DECISAO_CONFIRMAR",
            "DECISAO_REJEITAR",
        ):
            self.assertIn(fragment, validar)
        self.assertEqual(
            node(self.wf04, "Resp: Decisão Já Registrada")["parameters"][
                "options"
            ]["responseCode"],
            200,
        )
        self.assertEqual(
            node(self.wf04, "Resp: Inválido")["parameters"]["options"][
                "responseCode"
            ],
            409,
        )

    def test_nao_duplicado_limpa_match_e_retorna_a_fila_de_classificacao(self) -> None:
        validar = parameters_text(self.wf04, "Validar Fiscal")
        self.assertIn("d.decisao === 'nao_duplicado'", validar)
        self.assertIn("acao = 'REJEITAR'", validar)
        self.assertEqual(
            successors(self.wf04, "Switch Ação Fiscal", output=1),
            ["Resp: Rejeitado"],
        )
        self.assertEqual(
            successors(self.wf04, "Resp: Rejeitado"),
            ["PG: Limpar Duplicidade"],
        )
        limpar = parameters_text(self.wf04, "PG: Limpar Duplicidade")
        for fragment in (
            "decisao_fiscal='REJEITOU_DUP'",
            "fiscal_decision_token=NULL",
            "fiscal_token_expira_em=NULL",
            "classificacao_final=NULL",
            "duplicado_de_id=NULL",
            "triagem_status='AGUARDANDO_FILA_CLASSIFICACAO'",
            "fila_etapa='CLASSIFICACAO'",
        ):
            self.assertIn(fragment, limpar)
        self.assertEqual(
            successors(self.wf04, "GLPI: Encerrar Sessão Fiscal Rejeição"),
            ["PG: Enfileirar Classificação"],
        )
        enfileirar = parameters_text(self.wf04, "PG: Enfileirar Classificação")
        self.assertIn("triagem_status='PENDENTE_FILA_IA'", enfileirar)
        self.assertIn("fila_etapa='CLASSIFICACAO'", enfileirar)

    def test_wf06_serializa_reserva_e_evitar_duplo_consumo(self) -> None:
        sql = parameters_text(self.wf06, "PG: Reservar Fila IA")
        for fragment in (
            "pg_advisory_xact_lock(9062026)",
            "FROM bloqueio",
            "FROM bloqueio base",
            "FOR UPDATE SKIP LOCKED",
            "GREATEST((SELECT tamanho FROM lote_efetivo) - COUNT(*)::int,0)",
            "fila_elegivel AS MATERIALIZED",
            "e.status IN ('EXECUTANDO','CALIBRANDO')",
            "triagem_status='EXPERIMENTO_ENCERRADO'",
            "WF06_QUARENTENA_EXPERIMENTO_ENCERRADO",
            "fila_reservada_em=NOW()",
            "Reserva expirada; reenfileirado pelo WF06",
        ):
            self.assertIn(fragment, sql)
        self.assertGreaterEqual(
            sql.count("JOIN fila_elegivel e ON e.id=t.id"),
            5,
            "capacidade, reserva e métricas devem usar o mesmo escopo elegível",
        )

    def test_helpers_runtime_usam_metodos_e_endpoints_corretos(self) -> None:
        config = runtime.RuntimeConfig("http://127.0.0.1:5678", 7)
        case = runtime.PreparedFiscalCase(
            ticket_id=321,
            token="a" * 64,
            decision="nao_duplicado",
            reference_id=123,
            synthetic_prefix="[TESTE_AUTOMATIZADO_E2E_",
        )
        client = Mock()
        response = Mock()
        client.get.return_value = response
        client.post.return_value = response

        self.assertIs(runtime.fiscal_preview(client, config, case), response)
        client.get.assert_called_once_with(
            "http://127.0.0.1:5678/webhook/fiscal-confirmacao-v9",
            params=case.parameters,
            timeout=7,
        )

        self.assertIs(runtime.fiscal_decision(client, config, case), response)
        client.post.assert_called_once_with(
            "http://127.0.0.1:5678/webhook/fiscal-decisao-fiscal-ic-2026",
            data=case.parameters,
            timeout=7,
        )

        client.post.reset_mock()
        self.assertIs(
            runtime.wf06_ingress(
                client, config, {"ticket_id": 321}, "segredo-do-ambiente"
            ),
            response,
        )
        client.post.assert_called_once_with(
            "http://127.0.0.1:5678/webhook/glpi-ticket-fila-ia-v9",
            headers={"X-Webhook-Key": "segredo-do-ambiente"},
            json={"ticket_id": 321},
            timeout=7,
        )

    def test_scripts_nao_contem_credenciais_literais_legadas(self) -> None:
        runtime_text = (SCRIPT_DIR / "test_v9_runtime.py").read_text(
            encoding="utf-8"
        )
        combined = runtime_text + "\n" + (SCRIPT_DIR / "test_v9_hard.py").read_text(
            encoding="utf-8"
        )
        forbidden = (
            "SeedToken" + "2024CampusRP",
            "GLPI_" + 'PASSWORD = "',
            "GLPI_" + 'USER = "',
            "APP_" + 'TOKEN = "',
        )
        for fragment in forbidden:
            self.assertNotIn(fragment, combined)
        self.assertNotIn("?key=glpi-" + "n8n-ic-2026", runtime_text)
        self.assertNotIn(
            "glpi-ticket-novo-" + "glpi-n8n-ic-2026", runtime_text
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
