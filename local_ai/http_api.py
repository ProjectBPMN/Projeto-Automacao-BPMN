from __future__ import annotations

import hmac
import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .backends import BackendUnavailable
from .config import Settings
from .inference import InferenceResult, LocalAIService, SERVICE_VERSION


class LocalAIHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], service: LocalAIService) -> None:
        super().__init__(address, LocalAIRequestHandler)
        self.service = service
        self.request_slots = threading.BoundedSemaphore(service.settings.max_concurrent_requests)


class LocalAIRequestHandler(BaseHTTPRequestHandler):
    server: LocalAIHTTPServer
    protocol_version = "HTTP/1.1"
    server_version = f"ProjetoIC-LocalAI/{SERVICE_VERSION}"

    def log_message(self, format_string: str, *args: Any) -> None:
        # Nunca registra payload/texto do chamado.
        print(f"[local-ai] {self.client_address[0]} {format_string % args}")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/health":
            self._error(HTTPStatus.NOT_FOUND, "not_found", "Endpoint não encontrado")
            return
        if not self._authorized():
            return
        self._json(HTTPStatus.OK, self.server.service.health())

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            return
        parsed = urlparse(self.path)
        routes = {
            "/v1/embed": self.server.service.embed,
            "/v1/deduplicate": self.server.service.deduplicate,
            "/v1/classify": self.server.service.classify,
            "/v1/extract": self.server.service.extract,
        }
        handler = routes.get(parsed.path)
        if handler is None:
            self._error(HTTPStatus.NOT_FOUND, "not_found", "Endpoint não encontrado")
            return
        if not self.server.request_slots.acquire(blocking=False):
            self._error(
                HTTPStatus.TOO_MANY_REQUESTS,
                "busy",
                "Limite de inferências simultâneas atingido",
                extra_headers={"Retry-After": "1"},
            )
            return
        try:
            payload = self._read_payload()
            result = handler(payload)
            query = parse_qs(parsed.query)
            envelope = query.get("include_metadata", ["0"])[0].lower() in {
                "1",
                "true",
                "yes",
                "sim",
            }
            body = {"result": result.result, "metadata": result.metadata} if envelope else result.result
            headers = self._provenance_headers(result)
            self._json(HTTPStatus.OK, body, extra_headers=headers)
        except json.JSONDecodeError:
            self._error(HTTPStatus.BAD_REQUEST, "invalid_json", "Corpo não contém JSON válido")
        except (ValueError, UnicodeDecodeError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, "invalid_request", str(exc))
        except BackendUnavailable as exc:
            self._error(HTTPStatus.SERVICE_UNAVAILABLE, "backend_unavailable", str(exc))
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", str(exc))
        finally:
            self.server.request_slots.release()

    def _authorized(self) -> bool:
        expected = self.server.service.settings.api_token
        if not expected:
            return True
        provided = self.headers.get("Authorization", "")
        if provided.startswith("Bearer "):
            provided = provided[7:]
        if hmac.compare_digest(provided, expected):
            return True
        self._error(HTTPStatus.UNAUTHORIZED, "unauthorized", "Token local inválido")
        return False

    def _read_payload(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise ValueError("Content-Length obrigatório")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("Content-Length inválido") from exc
        if length <= 0:
            raise ValueError("Corpo JSON obrigatório")
        if length > self.server.service.settings.max_body_bytes:
            raise ValueError("Corpo excede o limite configurado")
        body = self.rfile.read(length)
        value = json.loads(body.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("O corpo JSON deve ser um objeto")
        return value

    @staticmethod
    def _provenance_headers(result: InferenceResult) -> dict[str, str]:
        embedding = result.metadata.get("embedding") or {}
        artifact = result.metadata.get("artifact") or {}
        return {
            "X-Local-AI-Trace-Id": str(result.metadata.get("trace_id", "")),
            "X-Local-AI-Backend": str(embedding.get("backend", "deterministic_gate")),
            "X-Local-AI-Fallback": "true" if result.metadata.get("fallback_used") else "false",
            "X-Local-AI-Candidate-Evaluation-Eligible": "true"
            if result.metadata.get("candidate_evaluation_eligible")
            else "false",
            "X-Local-AI-Pipeline-Evaluation-Eligible": "true"
            if result.metadata.get("pipeline_evaluation_eligible")
            else "false",
            "X-Local-AI-Scientific-Eligible": "true" if result.metadata.get("scientific_eligible") else "false",
            "X-Local-AI-Artifact-Version": str(artifact.get("version") or "unavailable"),
        }

    def _error(
        self,
        status: HTTPStatus,
        code: str,
        message: str,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self._json(status, {"error": {"code": code, "message": message}}, extra_headers=extra_headers)

    def _json(
        self,
        status: HTTPStatus,
        body: dict[str, Any],
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)


def create_server(settings: Settings | None = None, port: int | None = None) -> LocalAIHTTPServer:
    final_settings = settings or Settings.from_env()
    if port is not None:
        final_settings = final_settings.with_network(host=final_settings.host, port=port)
    service = LocalAIService(final_settings)
    return LocalAIHTTPServer((final_settings.host, final_settings.port), service)


def serve(settings: Settings | None = None) -> None:
    server = create_server(settings)
    host, port = server.server_address[:2]
    print(f"[local-ai] ouvindo em http://{host}:{port} mode={server.service.settings.mode}")
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
