import redis.asyncio.connection

from traide.redis.access_kwargs import redis_client_access_kwargs, redis_pool_access_kwargs
from traide.redis.google_iam_credential_provider import GoogleIamCredentialProvider

CA_PATH = "/etc/redis-ca/ca.pem"


def test_a_plain_connection_carries_only_the_client_name() -> None:
    assert redis_client_access_kwargs(tls_ca_path=None, iam_auth=False, client_name="svc") == {"client_name": "svc"}


def test_tls_verifies_the_chain_but_not_the_hostname() -> None:
    kwargs = redis_client_access_kwargs(tls_ca_path=CA_PATH, iam_auth=False, client_name="svc")
    assert kwargs["ssl"] is True
    assert kwargs["ssl_ca_certs"] == CA_PATH
    assert kwargs["ssl_cert_reqs"] == "required"
    assert kwargs["ssl_check_hostname"] is False


def test_iam_auth_supplies_a_google_credential_provider() -> None:
    kwargs = redis_client_access_kwargs(tls_ca_path=None, iam_auth=True, client_name="svc")
    assert isinstance(kwargs["credential_provider"], GoogleIamCredentialProvider)


def test_pool_kwargs_select_the_async_ssl_connection_class() -> None:
    kwargs = redis_pool_access_kwargs(tls_ca_path=CA_PATH, iam_auth=True, client_name="svc")
    assert kwargs["connection_class"] is redis.asyncio.connection.SSLConnection
    assert "ssl" not in kwargs
    assert kwargs["ssl_ca_certs"] == CA_PATH
    assert isinstance(kwargs["credential_provider"], GoogleIamCredentialProvider)


def test_pool_kwargs_without_tls_keep_the_default_connection_class() -> None:
    kwargs = redis_pool_access_kwargs(tls_ca_path=None, iam_auth=False, client_name="svc")
    assert kwargs == {"client_name": "svc"}


def test_an_empty_ca_path_leaves_tls_off() -> None:
    assert redis_client_access_kwargs(tls_ca_path="", iam_auth=False, client_name="svc") == {"client_name": "svc"}
    assert redis_pool_access_kwargs(tls_ca_path="", iam_auth=False, client_name="svc") == {"client_name": "svc"}
