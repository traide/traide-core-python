import threading
from typing import Any

import redis.asyncio.connection
from traide.redis.google_iam_credential_provider import GoogleIamCredentialProvider

_shared_provider: GoogleIamCredentialProvider | None = None
_shared_provider_lock = threading.Lock()


def redis_client_access_kwargs(tls_ca_path: str | None, iam_auth: bool, client_name: str) -> dict[str, Any]:
    kwargs = _access_kwargs(tls_ca_path=tls_ca_path, iam_auth=iam_auth, client_name=client_name)
    if tls_ca_path:
        kwargs["ssl"] = True
    return kwargs


def redis_pool_access_kwargs(tls_ca_path: str | None, iam_auth: bool, client_name: str) -> dict[str, Any]:
    kwargs = _access_kwargs(tls_ca_path=tls_ca_path, iam_auth=iam_auth, client_name=client_name)
    if tls_ca_path:
        kwargs["connection_class"] = redis.asyncio.connection.SSLConnection
    return kwargs


def _access_kwargs(tls_ca_path: str | None, iam_auth: bool, client_name: str) -> dict[str, Any]:
    if iam_auth and not tls_ca_path:
        raise ValueError("Redis IAM auth requires TLS: set REDIS_TLS_CA_PATH")
    kwargs: dict[str, Any] = {"client_name": client_name}
    if tls_ca_path:
        kwargs.update(ssl_ca_certs=tls_ca_path, ssl_cert_reqs="required", ssl_check_hostname=False)
    if iam_auth:
        kwargs["credential_provider"] = _shared_credential_provider()
    return kwargs


def _shared_credential_provider() -> GoogleIamCredentialProvider:
    global _shared_provider
    with _shared_provider_lock:
        if _shared_provider is None:
            _shared_provider = GoogleIamCredentialProvider()
        return _shared_provider
