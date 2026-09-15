"""
Тонкий защищённый гейтвей к Ollama.

Аутентификация: mTLS через gateway-tls (nginx) + X-Gateway-Token.
Python верифицирует подпись сертификата через `cryptography`, а не
доверяет `X-Client-CN`. Скомпрометированный nginx не может подделать
CN без `ca.key`. Токен — вторая линия.

X-Client-Verify (defense-in-depth): nginx выставляет заголовок
`$ssl_client_verify`. Гейтвей требует значение `SUCCESS` до
верификации подписи. Это отсекает обход nginx (прямое подключение к
model-gateway из соседнего контейнера в internal-net): без nginx
заголовок отсутствует, запрос отвергается с 403.

Профили:
  * `_apply_profile_chat` и `_apply_profile_generate` — разделены.
  * `/api/generate` НИКОГДА не получает поле `messages`.
  * tools вычищаются полностью.

Concurrency:
  * `_SemHolder` держит семафоры до конца стрима.
  * Per-IP rate limit применяется ДО аутентификации.

Аудит:
  * HMAC-SHA256 для `prompt_hash` (length-prefix).
  * fsync для критичных событий.
  * Ни промптов, ни ответов.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx
import yaml
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from cert_verify import CertVerifier, check_server_cert


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s gateway %(message)s",
)
log = logging.getLogger("gateway")


MAX_REQUEST_BYTES = 1_048_576
MAX_KEEP_ALIVE_SECONDS = 1800
MIN_NUM_CTX = 512
CHUNK_READ_TIMEOUT = 10.0

# fsync только для критичных событий. auth_fail НЕ в списке:
# спам неверными токенами не должен бить по диску.
DURABLE_EVENTS = frozenset({
    "gateway_start", "gateway_stop",
    "request_rejected", "rate_limited", "upstream_error",
})


# ============================================================================
# Config
# ============================================================================

class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ClientProfile:
    name: str
    token_sha256: str
    tools_enabled: bool
    allowed_tools: frozenset[str] | None
    forced_system_prompt: str | None
    requests_per_minute: int
    max_concurrent: int
    allow_stream: bool
    audit_label: str


@dataclass(frozen=True)
class ServerCertPolicy:
    cert_path: Path
    required: bool
    required_san: str
    allowed_extra_sans: frozenset[str]
    allowed_ips: frozenset[
        ipaddress.IPv4Address | ipaddress.IPv6Address
    ]


@dataclass(frozen=True)
class GatewayConfig:
    upstream_base_url: str
    request_timeout_seconds: float
    connect_timeout_seconds: float
    model_allowlist: frozenset[str]
    default_model: str
    max_prompt_bytes: int
    max_num_predict: int
    max_num_ctx: int
    max_messages: int
    global_max_concurrent: int
    global_auth_fail_per_minute: int
    prompt_hash_hmac_key: bytes
    ca_cert_path: Path
    server_cert: ServerCertPolicy
    clients: tuple[ClientProfile, ...]
    audit_path: Path


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ConfigError(msg)


def _valid_cn(cn: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9._-]{1,64}", cn))


def load_config(path: str) -> GatewayConfig:
    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(f"GATEWAY_CONFIG file not found: {path}")

    with config_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    _require(isinstance(raw, dict), "config must be a mapping")

    up = raw.get("upstream") or {}
    _require(isinstance(up, dict), "upstream must be a mapping")
    base_url = up.get("base_url")
    _require(
        isinstance(base_url, str) and base_url.startswith("http://"),
        "upstream.base_url must be http://",
    )
    request_timeout = float(up.get("request_timeout_seconds", 180))
    connect_timeout = float(up.get("connect_timeout_seconds", 5))
    _require(request_timeout > 0 and connect_timeout > 0,
             "upstream timeouts must be > 0")

    allowlist_raw = up.get("model_allowlist") or []
    _require(isinstance(allowlist_raw, list) and allowlist_raw,
             "model_allowlist must be a non-empty list")
    for model_name in allowlist_raw:
        _require(
            isinstance(model_name, str) and model_name
            and len(model_name) <= 128,
            f"invalid model name: {model_name!r}",
        )
    model_allowlist = frozenset(allowlist_raw)
    default_model = up.get("default_model") or ""
    if default_model:
        _require(default_model in model_allowlist,
                 f"default_model {default_model!r} not in allowlist")

    lim = raw.get("limits") or {}
    _require(isinstance(lim, dict), "limits must be a mapping")
    max_prompt_bytes = int(lim.get("max_prompt_bytes", 200_000))
    max_num_predict = int(lim.get("max_num_predict", 4096))
    max_num_ctx = int(lim.get("max_num_ctx", 8192))
    max_messages = int(lim.get("max_messages", 200))
    global_max_concurrent = int(lim.get("global_max_concurrent", 4))
    global_auth_fail_per_minute = int(
        lim.get("global_auth_fail_per_minute", 10)
    )
    _require(max_prompt_bytes > 0, "max_prompt_bytes must be > 0")
    _require(max_num_predict > 0, "max_num_predict must be > 0")
    _require(max_num_ctx >= MIN_NUM_CTX,
             f"max_num_ctx must be >= {MIN_NUM_CTX}")
    _require(max_messages > 0, "max_messages must be > 0")
    _require(global_max_concurrent > 0,
             "global_max_concurrent must be > 0")
    _require(global_auth_fail_per_minute > 0,
             "global_auth_fail_per_minute must be > 0")

    hmac_key = os.environ.get("GATEWAY_HMAC_KEY", "")
    _require(len(hmac_key) >= 32,
             "GATEWAY_HMAC_KEY must be at least 32 chars")

    ca_cert_path = Path(os.environ.get("GATEWAY_CA_CERT", "/certs/ca.crt"))
    _require(ca_cert_path.is_file(),
             f"CA cert not found at {ca_cert_path}")

    server_cert_path = Path(os.environ.get(
        "GATEWAY_SERVER_CERT", "/certs/server.crt"
    ))
    required_san = os.environ.get(
        "GATEWAY_SERVER_SAN", "gateway-tls"
    ).strip()
    _require(bool(required_san), "GATEWAY_SERVER_SAN must be non-empty")
    extra_sans = frozenset(
        s.strip() for s in os.environ.get(
            "GATEWAY_SERVER_EXTRA_SANS", "localhost"
        ).split(",") if s.strip()
    )
    _require(
        required_san not in extra_sans,
        f"GATEWAY_SERVER_SAN={required_san!r} must not also appear "
        f"in GATEWAY_SERVER_EXTRA_SANS",
    )
    allowed_ips: frozenset[
        ipaddress.IPv4Address | ipaddress.IPv6Address
    ] = frozenset(
        ipaddress.ip_address(s.strip())
        for s in os.environ.get(
            "GATEWAY_SERVER_IPS", "127.0.0.1"
        ).split(",")
        if s.strip()
    )
    require_cert = os.environ.get(
        "GATEWAY_REQUIRE_SERVER_CERT", "1"
    ) == "1"

    server_cert_policy = ServerCertPolicy(
        cert_path=server_cert_path,
        required=require_cert,
        required_san=required_san,
        allowed_extra_sans=extra_sans,
        allowed_ips=allowed_ips,
    )

    clients_raw = raw.get("clients") or []
    _require(isinstance(clients_raw, list) and clients_raw,
             "clients must be a non-empty list")

    clients: list[ClientProfile] = []
    seen_hashes: set[str] = set()
    seen_names: set[str] = set()
    for client_spec in clients_raw:
        _require(isinstance(client_spec, dict),
                 "each client entry must be a mapping")
        name = str(client_spec["name"])
        _require(_valid_cn(name), f"client name {name!r} invalid")
        _require(name not in seen_names,
                 f"duplicate client name {name!r}")
        seen_names.add(name)

        token_hash = str(
            client_spec.get("token_sha256", "")
        ).lower().strip()
        _require(
            len(token_hash) == 64
            and all(ch in "0123456789abcdef" for ch in token_hash),
            f"client {name!r}: token_sha256 must be 64 hex chars",
        )
        _require(token_hash not in seen_hashes,
                 f"client {name!r}: duplicate token_sha256")
        seen_hashes.add(token_hash)

        allowed = client_spec.get("allowed_tools")
        if allowed is not None:
            _require(isinstance(allowed, list),
                     f"client {name!r}: allowed_tools must be list or null")
            for tool_name in allowed:
                _require(
                    isinstance(tool_name, str)
                    and re.fullmatch(r"[a-z_]+", tool_name),
                    f"client {name!r}: invalid tool name {tool_name!r}",
                )
            allowed_set: frozenset[str] | None = frozenset(allowed)
        else:
            allowed_set = None

        forced_prompt = client_spec.get("forced_system_prompt")
        if forced_prompt is not None:
            _require(isinstance(forced_prompt, str),
                     "forced_system_prompt must be str")
            _require(len(forced_prompt) <= 8_000,
                     f"client {name!r}: forced_system_prompt too long")

        rpm = int(client_spec.get("requests_per_minute", 60))
        mc = int(client_spec.get("max_concurrent", 1))
        _require(rpm > 0,
                 f"client {name!r}: requests_per_minute must be > 0")
        _require(mc > 0,
                 f"client {name!r}: max_concurrent must be > 0")
        _require(mc <= global_max_concurrent,
                 f"client {name!r}: max_concurrent > global_max_concurrent")

        clients.append(ClientProfile(
            name=name,
            token_sha256=token_hash,
            tools_enabled=bool(client_spec.get("tools_enabled", False)),
            allowed_tools=allowed_set,
            forced_system_prompt=forced_prompt,
            requests_per_minute=rpm,
            max_concurrent=mc,
            allow_stream=bool(client_spec.get("allow_stream", False)),
            audit_label=str(client_spec.get("audit_label", name)),
        ))

    return GatewayConfig(
        upstream_base_url=base_url.rstrip("/"),
        request_timeout_seconds=request_timeout,
        connect_timeout_seconds=connect_timeout,
        model_allowlist=model_allowlist,
        default_model=default_model,
        max_prompt_bytes=max_prompt_bytes,
        max_num_predict=max_num_predict,
        max_num_ctx=max_num_ctx,
        max_messages=max_messages,
        global_max_concurrent=global_max_concurrent,
        global_auth_fail_per_minute=global_auth_fail_per_minute,
        prompt_hash_hmac_key=hmac_key.encode("utf-8"),
        ca_cert_path=ca_cert_path,
        server_cert=server_cert_policy,
        clients=tuple(clients),
        audit_path=Path(
            os.environ.get("GATEWAY_AUDIT_PATH", "/logs/gateway.jsonl")
        ),
    )


# ============================================================================
# Client state
# ============================================================================

class ClientState:
    def __init__(self, profile: ClientProfile):
        self.profile = profile
        self.sem = asyncio.Semaphore(profile.max_concurrent)
        self._recent: deque[float] = deque()

    def take_rate_token(self) -> bool:
        now = time.monotonic()
        cutoff = now - 60.0
        while self._recent and self._recent[0] < cutoff:
            self._recent.popleft()
        if len(self._recent) >= self.profile.requests_per_minute:
            return False
        self._recent.append(now)
        return True


class PerIpRateLimiter:
    """Sliding window на IP с LRU-вытеснением при переполнении.

    OrderedDict: при каждом обращении ключ перемещается в конец;
    при переполнении сначала чистятся stale bucket'ы, затем — самый
    старый по последнему обращению.
    """
    MAX_BUCKETS = 512
    PURGE_EVERY = 128

    def __init__(self, max_per_minute: int):
        self.max = max_per_minute
        self._buckets: OrderedDict[str, deque[float]] = OrderedDict()
        self._adds_since_purge = 0

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - 60.0

        bucket = self._buckets.get(key)
        if bucket is None:
            if len(self._buckets) >= self.MAX_BUCKETS:
                self._make_room(cutoff)
            bucket = deque()
            self._buckets[key] = bucket
            self._adds_since_purge += 1
            if self._adds_since_purge >= self.PURGE_EVERY:
                self._purge_stale(cutoff)
                self._adds_since_purge = 0
        else:
            self._buckets.move_to_end(key)

        while bucket and bucket[0] < cutoff:
            bucket.popleft()

        if len(bucket) >= self.max:
            return False
        bucket.append(now)
        return True

    def _make_room(self, cutoff: float) -> None:
        self._purge_stale(cutoff)
        while len(self._buckets) >= self.MAX_BUCKETS:
            self._buckets.popitem(last=False)

    def _purge_stale(self, cutoff: float) -> None:
        stale = [
            k for k, v in self._buckets.items()
            if not v or v[-1] < cutoff
        ]
        for k in stale:
            del self._buckets[k]


# ============================================================================
# Audit
# ============================================================================

class AuditWriter:
    def __init__(self, path: Path):
        # Fail-closed: если аудит не открывается — не стартуем.
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8"):
            pass
        self.path = path

    def write(self, event: str, **fields: Any) -> None:
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": event,
            **fields,
        }
        durable = event in DURABLE_EVENTS
        try:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                fh.flush()
                if durable:
                    os.fsync(fh.fileno())
        except OSError as e:
            log.error("audit write failed: %s", e)


# ============================================================================
# App
# ============================================================================

CONFIG_PATH = os.environ.get(
    "GATEWAY_CONFIG", "/config/gateway_clients.yaml"
)
config = load_config(CONFIG_PATH)
audit = AuditWriter(config.audit_path)
verifier = CertVerifier(config.ca_cert_path)

_client_states_by_name: dict[str, ClientState] = {
    p.name: ClientState(p) for p in config.clients
}
_global_sem = asyncio.Semaphore(config.global_max_concurrent)
_auth_fail_limiter = PerIpRateLimiter(config.global_auth_fail_per_minute)
_http: httpx.AsyncClient | None = None


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


# ---------------------------------------------------------------------------
# Middleware: ограничение Content-Length (первый барьер).
# Реальная защита — в _read_json_limited (stream-based).
# ---------------------------------------------------------------------------

@app.middleware("http")
async def _content_length_guard(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    cl = request.headers.get("content-length")
    if cl is not None:
        try:
            n = int(cl)
        except ValueError:
            return JSONResponse(
                {"detail": "invalid Content-Length"}, status_code=400
            )
        if n > MAX_REQUEST_BYTES:
            return JSONResponse(
                {"detail": f"request body too large ({n} bytes)"},
                status_code=413,
            )
    return await call_next(request)


@app.on_event("startup")
async def _startup() -> None:
    global _http
    scp = config.server_cert
    check_server_cert(
        scp.cert_path,
        required=scp.required,
        required_san=scp.required_san,
        allowed_extra_sans=scp.allowed_extra_sans,
        allowed_ips=scp.allowed_ips,
    )
    _http = httpx.AsyncClient(
        base_url=config.upstream_base_url,
        timeout=httpx.Timeout(
            config.request_timeout_seconds,
            connect=config.connect_timeout_seconds,
        ),
        follow_redirects=False,
        limits=httpx.Limits(
            max_keepalive_connections=16,
            max_connections=32,
        ),
    )
    audit.write("gateway_start",
                clients=sorted(p.name for p in config.clients),
                models=sorted(config.model_allowlist))


@app.on_event("shutdown")
async def _shutdown() -> None:
    if _http is not None:
        await _http.aclose()
    audit.write("gateway_stop")


# ============================================================================
# Helpers
# ============================================================================

def _try_client_ip(request: Request) -> str:
    """X-Real-IP от nginx. Не raise: пустая строка — сигнал о
    нарушении trust boundary, обрабатывается в _authenticate."""
    rip = request.headers.get("x-real-ip", "").strip()
    if rip and len(rip) <= 45:
        return rip
    return ""


def _extract_token(x_gateway_token: str, request: Request) -> str:
    """Достаёт токен из X-Gateway-Token или Authorization: Bearer.

    ВАЖНО: `gateway_tls/nginx.conf` выставляет
    `proxy_set_header Authorization ""` — заголовок Authorization,
    отправленный клиентом, до Python не доходит. Fallback на Bearer
    оставлен на случай прямого подключения к model-gateway
    (отладочная конфигурация без nginx); в production-развёртывании
    он недостижим.
    """
    if x_gateway_token:
        return x_gateway_token
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def _authenticate(request: Request, x_gateway_token: str) -> ClientState:
    ip = _try_client_ip(request)
    if not ip:
        # Запрос пришёл не от nginx — нарушение routing.
        raise HTTPException(500, "routing error: missing X-Real-IP")

    if not _auth_fail_limiter.allow(ip):
        audit.write("rate_limited", stage="auth", ip=ip)
        raise HTTPException(429, "too many attempts")

    # Defense-in-depth: nginx выставляет X-Client-Verify = $ssl_client_verify
    # (значение SUCCESS только при успешном TLS-handshake с валидным
    # клиентским сертификатом). При обходе nginx (прямое подключение
    # к model-gateway из соседнего контейнера в internal-net) заголовок
    # отсутствует или имеет другое значение — отсекаем запрос до
    # верификации подписи сертификата.
    verify_status = request.headers.get("x-client-verify", "").strip()
    if verify_status != "SUCCESS":
        audit.write("auth_fail", reason="mtls_not_verified",
                    ip=ip, header_value=verify_status[:32])
        raise HTTPException(403, "client cert not verified by TLS terminator")

    # mTLS: nginx пробрасывает сертификат в X-Client-Cert; Python
    # верифицирует подпись и извлекает SAN DNS как имя клиента.
    client_cert = request.headers.get("x-client-cert", "")
    cn = verifier.verify(client_cert)
    if cn is None:
        audit.write("auth_fail", reason="invalid_client_cert", ip=ip)
        raise HTTPException(403, "client cert invalid")

    state = _client_states_by_name.get(cn)
    if state is None:
        audit.write("auth_fail", reason="unknown_client", cn=cn, ip=ip)
        raise HTTPException(403, "unknown client")

    token = _extract_token(x_gateway_token, request)
    if not token:
        audit.write("auth_fail", reason="missing_token",
                    client=state.profile.audit_label, ip=ip)
        raise HTTPException(403, "missing token")

    token_hash = _sha256_hex(token)
    if not hmac.compare_digest(state.profile.token_sha256, token_hash):
        audit.write("auth_fail", reason="bad_token",
                    client=state.profile.audit_label, ip=ip)
        raise HTTPException(403, "invalid token")

    return state


# ============================================================================
# Tool field stripping
# ============================================================================

_TOOL_MSG_ROLES = {"tool", "function"}
_TOOL_TOP_FIELDS = ("tools", "functions", "tool_choice")
_TOOL_MSG_FIELDS = ("tool_calls", "function_call", "tool_call_id", "name")


def _tool_name(t: Any) -> str | None:
    if not isinstance(t, dict):
        return None
    fn = t.get("function")
    if not isinstance(fn, dict):
        return None
    name = fn.get("name")
    return name if isinstance(name, str) else None


def _strip_all_tool_fields(body: dict) -> None:
    """Удаляет ВСЕ tool-поля из chat-body, включая вложенные в
    сообщения. Применяется, когда клиенту tools не положены."""
    for k in _TOOL_TOP_FIELDS:
        body.pop(k, None)
    msgs = body.get("messages") or []
    if not isinstance(msgs, list):
        return
    cleaned: list[dict] = []
    for m in msgs:
        if not isinstance(m, dict):
            continue
        if m.get("role") in _TOOL_MSG_ROLES:
            continue
        for f in _TOOL_MSG_FIELDS:
            m.pop(f, None)
        cleaned.append(m)
    body["messages"] = cleaned


def _filter_allowed_tools(body: dict, allowed: frozenset[str]) -> None:
    """Оставляет только разрешённые tools; чистит tool_calls в истории."""
    tools = body.get("tools")
    if isinstance(tools, list):
        body["tools"] = [t for t in tools if _tool_name(t) in allowed]
    body.pop("functions", None)
    body.pop("tool_choice", None)

    msgs = body.get("messages") or []
    if not isinstance(msgs, list):
        return
    for m in msgs:
        if not isinstance(m, dict):
            continue
        tcs = m.get("tool_calls")
        if isinstance(tcs, list):
            filtered = [tc for tc in tcs if _tool_name(tc) in allowed]
            if filtered:
                m["tool_calls"] = filtered
            else:
                m.pop("tool_calls", None)
        fc = m.get("function_call")
        if isinstance(fc, dict) and fc.get("name") not in allowed:
            m.pop("function_call", None)


# ============================================================================
# Clamps
# ============================================================================

def _clamp_num_predict(value: Any) -> int:
    if value is None:
        return config.max_num_predict
    try:
        n = int(value)
    except (TypeError, ValueError):
        return config.max_num_predict
    return max(1, min(n, config.max_num_predict))


def _clamp_num_ctx(value: Any) -> int:
    if value is None:
        return config.max_num_ctx
    try:
        n = int(value)
    except (TypeError, ValueError):
        return config.max_num_ctx
    return max(MIN_NUM_CTX, min(n, config.max_num_ctx))


def _clamp_keep_alive(value: Any) -> str:
    if isinstance(value, bool):
        return f"{MAX_KEEP_ALIVE_SECONDS}s"
    if isinstance(value, (int, float)):
        n = int(value)
        if n < 0:
            return f"{MAX_KEEP_ALIVE_SECONDS}s"
        return f"{min(n, MAX_KEEP_ALIVE_SECONDS)}s"
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("-1", "0", "forever", "infinite", "infinity"):
            return f"{MAX_KEEP_ALIVE_SECONDS}s"
        m = re.fullmatch(r"(\d+)\s*([smh]?)", s)
        if not m:
            return f"{MAX_KEEP_ALIVE_SECONDS}s"
        n = int(m.group(1))
        factor = {"s": 1, "m": 60, "h": 3600}[m.group(2) or "s"]
        return f"{min(n * factor, MAX_KEEP_ALIVE_SECONDS)}s"
    return f"{MAX_KEEP_ALIVE_SECONDS}s"


def _apply_options(body: dict) -> None:
    opts = body.get("options")
    if not isinstance(opts, dict):
        opts = {}
    opts["num_predict"] = _clamp_num_predict(opts.get("num_predict"))
    opts["num_ctx"] = _clamp_num_ctx(opts.get("num_ctx"))
    body["options"] = opts
    if "keep_alive" in body:
        body["keep_alive"] = _clamp_keep_alive(body["keep_alive"])


def _apply_model(body: dict) -> None:
    model = body.get("model") or config.default_model
    if model not in config.model_allowlist:
        raise HTTPException(400, f"model not allowed: {model!r}")
    body["model"] = model


# ============================================================================
# Profile application (chat и generate разделены)
# ============================================================================

def _apply_profile_chat(body: dict, state: ClientState) -> None:
    _apply_model(body)

    p = state.profile
    if not p.tools_enabled:
        _strip_all_tool_fields(body)
    elif p.allowed_tools is not None:
        _filter_allowed_tools(body, p.allowed_tools)

    if p.forced_system_prompt is not None:
        msgs = body.get("messages") or []
        if not isinstance(msgs, list):
            msgs = []
        msgs = [m for m in msgs
                if not (isinstance(m, dict) and m.get("role") == "system")]
        msgs.insert(0, {"role": "system",
                        "content": p.forced_system_prompt})
        body["messages"] = msgs

    _apply_options(body)


def _apply_profile_generate(body: dict, state: ClientState) -> None:
    """НЕ трогаем body['messages'] — в /api/generate его нет."""
    _apply_model(body)

    for k in _TOOL_TOP_FIELDS:
        body.pop(k, None)

    if state.profile.forced_system_prompt is not None:
        body["system"] = state.profile.forced_system_prompt

    _apply_options(body)


# ============================================================================
# Body reading
# ============================================================================

async def _read_json_limited(request: Request, limit: int) -> dict:
    """Stream-based чтение тела с лимитом. Chunked-aware: Content-Length
    может отсутствовать; считаем байты по мере чтения."""
    cl = request.headers.get("content-length")
    if cl is not None:
        try:
            n = int(cl)
        except ValueError:
            raise HTTPException(400, "invalid Content-Length")
        if n > limit:
            raise HTTPException(413, f"body too large ({n} bytes)")

    total = 0
    chunks: list[bytes] = []
    stream = request.stream()
    while True:
        try:
            chunk = await asyncio.wait_for(
                stream.__anext__(), timeout=CHUNK_READ_TIMEOUT,
            )
        except StopAsyncIteration:
            break
        except asyncio.TimeoutError:
            raise HTTPException(408, "chunk read timeout")
        total += len(chunk)
        if total > limit:
            raise HTTPException(413, "body too large")
        chunks.append(chunk)

    if not chunks:
        raise HTTPException(400, "empty body")
    try:
        data = json.loads(b"".join(chunks))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(400, "invalid JSON body")
    if not isinstance(data, dict):
        raise HTTPException(400, "body must be an object")
    return data


def _enforce_chat_limits(body: dict) -> None:
    msgs = body.get("messages")
    if not isinstance(msgs, list):
        raise HTTPException(400, "messages must be a list")
    if len(msgs) > config.max_messages:
        raise HTTPException(
            413, f"too many messages ({len(msgs)} > {config.max_messages})"
        )
    total = 0
    for m in msgs:
        if not isinstance(m, dict):
            raise HTTPException(400, "each message must be an object")
        c = m.get("content", "")
        if isinstance(c, str):
            total += len(c.encode("utf-8"))
        elif isinstance(c, list):
            total += len(json.dumps(c, ensure_ascii=False).encode("utf-8"))
        elif c is not None:
            raise HTTPException(
                400, "message.content must be string/list/null"
            )
    if total > config.max_prompt_bytes:
        raise HTTPException(413, f"prompt too large ({total} bytes)")


# ============================================================================
# Semaphore holder
# ============================================================================

class _SemHolder:
    """Удерживает per-client и global семафоры до вызова release().

    В asyncio single-threaded race между проверкой _released и её
    установкой невозможен: между ними нет await.
    """
    def __init__(self, state: ClientState):
        self._state = state
        self._released = False
        self._global_held = False

    async def acquire(self) -> None:
        await self._state.sem.acquire()
        try:
            await _global_sem.acquire()
            self._global_held = True
        except BaseException:
            self._state.sem.release()
            raise

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        if self._global_held:
            _global_sem.release()
        self._state.sem.release()


# ============================================================================
# Prompt hash
# ============================================================================

def _prompt_hash_entries(entries: list[tuple[str, str]]) -> str:
    """HMAC-SHA256 от потока (role, content) с length-prefix.

    Разделители (\\x1f/\\x1e) дают коллизии, если content содержит
    эти символы. Length-prefix (4 байта длины + данные) однозначен
    при любом content.
    """
    h = hmac.new(config.prompt_hash_hmac_key, digestmod=hashlib.sha256)
    for role, content in entries:
        rb = role.encode("utf-8")
        cb = content.encode("utf-8")
        h.update(len(rb).to_bytes(4, "big"))
        h.update(rb)
        h.update(len(cb).to_bytes(4, "big"))
        h.update(cb)
    return h.hexdigest()[:16]


def _content_to_str(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, ensure_ascii=False,
                          sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return "<unhashable>"


def _prompt_hash_chat(msgs: list[dict]) -> str:
    entries: list[tuple[str, str]] = []
    for m in msgs:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "")
        content = _content_to_str(m.get("content", ""))
        entries.append((role, content))
    return _prompt_hash_entries(entries)


def _prompt_hash_generate(prompt: str, system: str) -> str:
    entries: list[tuple[str, str]] = []
    if system:
        entries.append(("system", system))
    entries.append(("user", prompt))
    return _prompt_hash_entries(entries)


# ============================================================================
# Proxying
# ============================================================================

async def _passthrough_json(method: str, url: str, *,
                            json_body: dict) -> Response:
    assert _http is not None
    try:
        resp = await _http.request(method, url, json=json_body)
    except httpx.RequestError as e:
        raise HTTPException(502, f"upstream error: {e}")
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/json"),
    )


async def _stream_passthrough(
    method: str, url: str, *, json_body: dict,
    on_done: Callable[[], Awaitable[None]],
) -> StreamingResponse:
    """Семафоры отпускаются ТОЛЬКО когда стрим полностью пройдёт
    (или клиент отвалится). on_done вызывается из finally генератора.

    Покрытие исключений: `build_request` и `send` обёрнуты в
    try/except BaseException. `_SemHolder.acquire()` уже выполнен
    вызывающим кодом, поэтому любое исключение — не только
    httpx.RequestError, но и, например, ValueError при некорректном
    URL или CancelledError при отмене — должно освободить
    удерживаемые семафоры. Иначе следующий запрос того же клиента
    или общий global-семафор повиснут.

    `on_done` (== `_SemHolder.release`) идемпотентен: повторный
    вызов безопасен.
    """
    assert _http is not None
    try:
        req = _http.build_request(method, url, json=json_body)
        upstream = await _http.send(req, stream=True)
    except httpx.RequestError as e:
        await on_done()
        raise HTTPException(502, f"upstream error: {e}")
    except BaseException:
        await on_done()
        raise

    async def gen():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            try:
                await upstream.aclose()
            finally:
                await on_done()

    return StreamingResponse(
        gen(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type",
                                        "application/x-ndjson"),
    )


def _rate_limit_or_429(state: ClientState) -> None:
    if not state.take_rate_token():
        audit.write("rate_limited", client=state.profile.audit_label)
        raise HTTPException(429, "rate limit exceeded")


def _check_stream_allowed(state: ClientState, body: dict,
                          request: Request) -> bool:
    stream = bool(body.get("stream", False))
    if stream and not state.profile.allow_stream:
        audit.write("request_rejected",
                    client=state.profile.audit_label,
                    reason="stream_not_allowed",
                    ip=_try_client_ip(request) or "unknown")
        raise HTTPException(403, "streaming not allowed for this client")
    return stream


# ============================================================================
# Endpoints
# ============================================================================

@app.get("/health")
async def health() -> dict:
    """Liveness. Без аутентификации, без upstream."""
    return {"ok": True}


@app.get("/ready")
async def ready(
    request: Request,
    x_gateway_token: str = Header(default=""),
) -> Response:
    """Readiness требует аутентификации."""
    state = _authenticate(request, x_gateway_token)
    _rate_limit_or_429(state)
    assert _http is not None
    try:
        r = await _http.get("/api/tags", timeout=5.0)
    except httpx.RequestError as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]},
                            status_code=503)
    return JSONResponse(
        {"ok": r.status_code == 200},
        status_code=200 if r.status_code == 200 else 503,
    )


@app.get("/api/tags")
async def api_tags(
    request: Request,
    x_gateway_token: str = Header(default=""),
) -> Response:
    state = _authenticate(request, x_gateway_token)
    _rate_limit_or_429(state)
    holder = _SemHolder(state)
    await holder.acquire()
    try:
        assert _http is not None
        resp = await _http.get("/api/tags")
    except httpx.RequestError as e:
        raise HTTPException(502, f"upstream error: {e}")
    finally:
        await holder.release()

    try:
        data = resp.json()
    except Exception:
        return Response(content=resp.content, status_code=resp.status_code)
    models = data.get("models") or []
    data["models"] = [m for m in models
                      if isinstance(m, dict)
                      and m.get("name") in config.model_allowlist]
    audit.write("tags", client=state.profile.audit_label,
                ip=_try_client_ip(request) or "unknown",
                count=len(data["models"]))
    return JSONResponse(data)


@app.post("/api/show")
async def api_show(
    request: Request,
    x_gateway_token: str = Header(default=""),
) -> Response:
    state = _authenticate(request, x_gateway_token)
    _rate_limit_or_429(state)
    body = await _read_json_limited(request, MAX_REQUEST_BYTES)
    model = body.get("model") or body.get("name")
    if model not in config.model_allowlist:
        raise HTTPException(400, f"model not allowed: {model!r}")
    audit.write("show", client=state.profile.audit_label,
                ip=_try_client_ip(request) or "unknown", model=model)
    holder = _SemHolder(state)
    await holder.acquire()
    try:
        return await _passthrough_json("POST", "/api/show",
                                       json_body=body)
    finally:
        await holder.release()


@app.post("/api/chat")
async def api_chat(
    request: Request,
    x_gateway_token: str = Header(default=""),
) -> Response:
    state = _authenticate(request, x_gateway_token)
    body = await _read_json_limited(request, MAX_REQUEST_BYTES)
    _enforce_chat_limits(body)
    _apply_profile_chat(body, state)
    _rate_limit_or_429(state)

    stream = _check_stream_allowed(state, body, request)

    msgs = body.get("messages") or []
    prompt_hash = _prompt_hash_chat(msgs)
    prompt_bytes = sum(
        len(m.get("content", "").encode("utf-8"))
        for m in msgs if isinstance(m, dict)
        and isinstance(m.get("content"), str)
    )
    audit.write(
        "request",
        client=state.profile.audit_label,
        ip=_try_client_ip(request) or "unknown",
        model=body.get("model"),
        messages=len(msgs),
        prompt_bytes=prompt_bytes,
        prompt_hash=prompt_hash,
        tools=bool(body.get("tools")),
        stream=stream,
    )

    t0 = time.monotonic()
    holder = _SemHolder(state)
    await holder.acquire()

    if stream:
        # Семафоры отпустит finally генератора.
        return await _stream_passthrough(
            "POST", "/api/chat",
            json_body=body,
            on_done=holder.release,
        )

    try:
        resp = await _passthrough_json("POST", "/api/chat", json_body=body)
    except HTTPException as e:
        audit.write("upstream_error",
                    client=state.profile.audit_label,
                    status=e.status_code,
                    duration_ms=int((time.monotonic() - t0) * 1000))
        raise
    finally:
        await holder.release()

    audit.write("response",
                client=state.profile.audit_label,
                status=getattr(resp, "status_code", 0),
                duration_ms=int((time.monotonic() - t0) * 1000),
                prompt_hash=prompt_hash)
    return resp


@app.post("/api/generate")
async def api_generate(
    request: Request,
    x_gateway_token: str = Header(default=""),
) -> Response:
    state = _authenticate(request, x_gateway_token)
    body = await _read_json_limited(request, MAX_REQUEST_BYTES)

    prompt = body.get("prompt", "")
    if isinstance(prompt, str) and \
            len(prompt.encode("utf-8")) > config.max_prompt_bytes:
        raise HTTPException(413, "prompt too large")

    _apply_profile_generate(body, state)
    _rate_limit_or_429(state)

    stream = _check_stream_allowed(state, body, request)

    system = body.get("system", "") or ""
    prompt_bytes = (
        len(prompt.encode("utf-8")) if isinstance(prompt, str) else 0
    )
    system_bytes = (
        len(system.encode("utf-8")) if isinstance(system, str) else 0
    )
    prompt_hash = _prompt_hash_generate(
        prompt if isinstance(prompt, str) else "",
        system if isinstance(system, str) else "",
    )
    audit.write(
        "request",
        client=state.profile.audit_label,
        ip=_try_client_ip(request) or "unknown",
        model=body.get("model"),
        endpoint="generate",
        prompt_bytes=prompt_bytes,
        system_bytes=system_bytes,
        prompt_hash=prompt_hash,
        stream=stream,
    )

    t0 = time.monotonic()
    holder = _SemHolder(state)
    await holder.acquire()

    if stream:
        return await _stream_passthrough(
            "POST", "/api/generate",
            json_body=body,
            on_done=holder.release,
        )

    try:
        resp = await _passthrough_json("POST", "/api/generate",
                                       json_body=body)
    finally:
        await holder.release()

    audit.write("response",
                client=state.profile.audit_label,
                endpoint="generate",
                status=getattr(resp, "status_code", 0),
                duration_ms=int((time.monotonic() - t0) * 1000))
    return resp
