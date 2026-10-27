import httpx
import pytest
import respx

from gatewayctl.client import ApiError, GatewayUnavailable, LiteLLMClient, redact

BASE = "http://litellm.test"
MASTER = "sk-master-0123456789abcdef"


@pytest.fixture
def router():
    with respx.mock(base_url=BASE, assert_all_called=False) as r:
        yield r


@pytest.fixture
def client():
    c = LiteLLMClient(BASE, MASTER)
    yield c
    c.close()


def _page(page, total_pages, count):
    keys = [{"token": f"tok-{page}-{i}", "key_alias": f"k-{page}-{i}"} for i in range(count)]
    return httpx.Response(
        200,
        json={"keys": keys, "total_count": 237, "current_page": page, "total_pages": total_pages},
    )


def test_list_keys_follows_pagination(router, client):
    # Review Focus 3: a missed key would survive offboarding.
    route = router.get("/key/list")
    route.side_effect = [_page(1, 3, 100), _page(2, 3, 100), _page(3, 3, 37)]
    keys = client.list_keys()
    assert len(keys) == 237
    assert len({k["token"] for k in keys}) == 237
    pages = [r.request.url.params["page"] for r in route.calls]
    assert pages == ["1", "2", "3"]
    for call in route.calls:
        assert call.request.url.params["size"] == "100"
        assert call.request.url.params["return_full_object"] == "true"


def test_list_keys_single_page(router, client):
    router.get("/key/list").mock(return_value=_page(1, 1, 5))
    assert len(client.list_keys()) == 5


def test_list_keys_empty(router, client):
    router.get("/key/list").mock(
        return_value=httpx.Response(200, json={"keys": [], "total_count": 0, "current_page": 1, "total_pages": 0})
    )
    assert client.list_keys() == []


def test_list_keys_without_total_pages_stops_on_short_page(router, client):
    route = router.get("/key/list")
    route.side_effect = [
        httpx.Response(200, json={"keys": [{"token": f"a{i}"} for i in range(100)]}),
        httpx.Response(200, json={"keys": [{"token": f"b{i}"} for i in range(3)]}),
    ]
    assert len(client.list_keys()) == 103


def test_check_ok(router, client):
    route = router.get("/key/list").mock(return_value=_page(1, 1, 1))
    client.check()
    assert route.calls[0].request.url.params["size"] == "1"


def test_check_raises_unavailable_on_connect_error(router, client):
    router.get("/key/list").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(GatewayUnavailable):
        client.check()


@pytest.mark.parametrize("status", [401, 403])
def test_check_raises_unavailable_on_401(router, client, status):
    router.get("/key/list").mock(return_value=httpx.Response(status, json={"error": "nope"}))
    with pytest.raises(GatewayUnavailable):
        client.check()


def test_unavailable_message_has_no_secret(router, client):
    router.get("/key/list").mock(
        return_value=httpx.Response(401, text=f"bad key {MASTER} Bearer sk-abcdef123456")
    )
    with pytest.raises(GatewayUnavailable) as exc:
        client.check()
    assert MASTER not in str(exc.value)
    assert "sk-abcdef123456" not in str(exc.value)


def test_api_error_detail_redacted(router, client):
    body = f"invalid key {MASTER}; header was Bearer sk-abcdef123456"
    router.post("/team/new").mock(return_value=httpx.Response(400, text=body))
    with pytest.raises(ApiError) as exc:
        client.team_new({"team_id": "dev"})
    err = exc.value
    assert err.status == 400
    assert err.path == "/team/new"
    assert MASTER not in err.detail
    assert "sk-abcdef123456" not in err.detail
    assert "sk-***" in err.detail
    assert MASTER not in str(err)


def test_authorization_header_sent(router, client):
    route = router.get("/team/list").mock(return_value=httpx.Response(200, json=[]))
    client.list_teams()
    assert route.calls[0].request.headers["Authorization"] == f"Bearer {MASTER}"


def test_redact_secrets_and_pattern():
    out = redact("a MYSECRET b sk-abcdef123456 c sk-short", ["MYSECRET", ""])
    assert "MYSECRET" not in out
    assert "sk-abcdef123456" not in out
    assert out == "a sk-*** b sk-*** c sk-short"


def test_team_delete_payload(router, client):
    route = router.post("/team/delete").mock(return_value=httpx.Response(200, json={}))
    assert client.team_delete("dev") is None
    assert route.calls[0].request.read() == b'{"team_ids":["dev"]}'


def test_key_block_payload(router, client):
    route = router.post("/key/block").mock(return_value=httpx.Response(200, json={}))
    client.key_block("hashed-token")
    assert httpx.Response(200, content=route.calls[0].request.read()).json() == {"key": "hashed-token"}


def test_key_generate_returns_key_and_token(router, client):
    router.post("/key/generate").mock(
        return_value=httpx.Response(200, json={"key": "sk-rawrawraw1", "token": "hashed"})
    )
    out = client.key_generate({"key_alias": "budi-laptop"})
    assert out["key"] == "sk-rawrawraw1"
    assert out["token"] == "hashed"


def test_member_calls(router, client):
    add = router.post("/team/member_add").mock(return_value=httpx.Response(200, json={}))
    upd = router.post("/team/member_update").mock(return_value=httpx.Response(200, json={}))
    dele = router.post("/team/member_delete").mock(return_value=httpx.Response(200, json={}))
    client.member_add("dev", "budi@x.com", 100.0)
    client.member_update("dev", "budi@x.com", 150.0)
    client.member_delete("dev", "budi@x.com")
    body = lambda r: httpx.Response(200, content=r.calls[0].request.read()).json()  # noqa: E731
    assert body(add) == {
        "team_id": "dev",
        "member": {"user_id": "budi@x.com", "role": "user"},
        "max_budget_in_team": 100.0,
    }
    assert body(upd) == {"team_id": "dev", "user_id": "budi@x.com", "max_budget_in_team": 150.0}
    assert body(dele) == {"team_id": "dev", "user_id": "budi@x.com"}


def test_get_endpoints_pass_params(router, client):
    ti = router.get("/team/info").mock(return_value=httpx.Response(200, json={"team_id": "dev"}))
    ki = router.get("/key/info").mock(return_value=httpx.Response(200, json={"info": {}}))
    client.team_info("dev")
    client.key_info("tok")
    assert ti.calls[0].request.url.params["team_id"] == "dev"
    assert ki.calls[0].request.url.params["key"] == "tok"


def test_transport_error_on_other_calls_is_unavailable(router, client):
    router.get("/team/list").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(GatewayUnavailable):
        client.list_teams()
