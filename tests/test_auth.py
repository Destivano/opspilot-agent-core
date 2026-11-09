import json
from unittest.mock import Mock

import pytest
from conftest import http_event

import app
from auth import ACCOUNTS, DemoAuth
from domain import Problem


@pytest.fixture
def auth(env):
    return DemoAuth(env.table, "test-demo-password", clock=Mock(return_value=1000))


def test_login_returns_server_owned_role_and_stores_only_token_hash(auth, env):
    result = auth.login(
        {"username": "casey.requester", "password": "test-demo-password", "role": "ops_approver"}, "ip"
    )
    event = {"headers": {"Authorization": "Bearer " + result["accessToken"]}}
    assert auth.principal(event) == ACCOUNTS["casey.requester"]
    records = env.table.scan()["Items"]
    assert result["accessToken"] not in json.dumps(records, default=str)
    auth.logout(event)
    with pytest.raises(Problem):
        auth.principal(event)


def test_session_expiry_is_enforced_before_ttl_cleanup(auth):
    result = auth.login({"username": "alex.approver", "password": "test-demo-password"}, "ip")
    event = {"headers": {"authorization": "Bearer " + result["accessToken"]}}
    auth.clock.return_value = 1900
    with pytest.raises(Problem, match="expired"):
        auth.principal(event)


@pytest.mark.parametrize(
    "username,password", [("casey.requester", "wrong"), ("unknown", "test-demo-password")]
)
def test_invalid_credentials(auth, username, password):
    with pytest.raises(Problem) as error:
        auth.login({"username": username, "password": password}, "ip")
    assert error.value.code == 401


def test_brute_force_limit_and_next_window(auth):
    for _ in range(10):
        with pytest.raises(Problem) as error:
            auth.login({"username": "casey.requester", "password": "wrong"}, "ip")
        assert error.value.code == 401
    with pytest.raises(Problem) as error:
        auth.login({"username": "casey.requester", "password": "test-demo-password"}, "ip")
    assert error.value.code == 429
    auth.clock.return_value = 1060
    assert auth.login({"username": "casey.requester", "password": "test-demo-password"}, "ip")["accessToken"]


def test_no_default_password(env):
    with pytest.raises(Problem) as error:
        DemoAuth(env.table, "").login({"username": "casey.requester", "password": "anything"}, "ip")
    assert error.value.code == 503


def test_http_login_authenticated_access_and_logout(auth, env, monkeypatch):
    monkeypatch.setattr(app, "authentication", lambda: auth)
    monkeypatch.setattr(app, "service", lambda: env.service)
    event = http_event({"username": "casey.requester", "password": "test-demo-password"})
    event["rawPath"] = "/login"
    event["headers"] = {}
    response = app.lambda_handler(event, None)
    assert response["statusCode"] == 200
    token = json.loads(response["body"])["accessToken"]
    event = http_event(method="GET")
    event["headers"] = {"authorization": "Bearer " + token}
    assert app.lambda_handler(event, None)["statusCode"] == 200
    event["rawPath"] = "/logout"
    event["requestContext"]["http"]["method"] = "POST"
    assert app.lambda_handler(event, None)["statusCode"] == 200
    event["rawPath"] = "/api"
    assert app.lambda_handler(event, None)["statusCode"] == 401
