"""Slice G5: every server message shown to people has Tamil, with the same placeholders."""

# ruff: noqa: F811  (pytest fixtures are imported and then used as parameters)

import ast
import pathlib
import string

from test_orders import data  # noqa: F401
from test_risk import scene  # noqa: F401

from app.core.i18n import FIELD_NAMES, VALIDATION, current_language, set_language, tr
from app.core.ta import TA

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


def literals(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value] if node.value else []
    if isinstance(node, ast.IfExp):
        return literals(node.body) + literals(node.orelse)
    return []


def messages() -> set[str]:
    found: set[str] = set()
    for path in APP.rglob("*.py"):
        if path.name == "ta.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in ("tr", "N_")
                and node.args
            ):
                found.update(literals(node.args[0]))
    return found


def fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_every_message_has_tamil_with_the_same_placeholders() -> None:
    keys = messages()
    assert {*VALIDATION.values(), *FIELD_NAMES.values()} <= keys
    missing = sorted(keys - TA.keys())
    assert not missing, f"{len(missing)} messages without Tamil, e.g. {missing[:5]}"
    unused = sorted(TA.keys() - keys)
    assert not unused, f"Tamil entries no message uses: {unused[:5]}"
    wrong = [k for k in keys if fields(k) != fields(TA[k])]
    assert not wrong, f"placeholders differ: {wrong[:5]}"


def test_tr_follows_the_request_language() -> None:
    before = current_language()
    try:
        set_language("ta")
        assert tr("Site not found") == TA["Site not found"]
        assert "7" in tr("Code {code} is already in use", code=7)
        set_language("en")
        assert tr("Code {code} is already in use", code="X1") == "Code X1 is already in use"
        set_language("fr")  # unsupported languages fall back to English
        assert current_language() == "en"
    finally:
        set_language(before)


async def test_messages_follow_the_screen_language(client, workspace_records) -> None:
    from conftest import csrf_headers, sign_in_as

    await sign_in_as(client, "owner@example.com")
    path = "/api/v1/orders/00000000-0000-0000-0000-000000000000"
    english = await client.get(path)
    tamil = await client.get(path, headers={"Accept-Language": "ta-IN,en;q=0.8"})
    assert english.json()["detail"] == "Order not found"
    assert tamil.json()["detail"] == TA["Order not found"]
    # Request validation: the message and the field name are translated too.
    bad = await client.post(
        "/api/v1/master-data/customers",
        headers={**csrf_headers(client), "Accept-Language": "ta"},
        json={"code": "AC", "name": ""},
    )
    assert bad.status_code == 422
    error = bad.json()["detail"][0]
    assert error["loc"][-1] == TA["Name"]
    expected = {
        TA[VALIDATION[kind]].format(min_length=1) for kind in ("string_too_short", "too_short")
    }
    assert error["msg"] in expected
    # The next request without the header is English again.
    assert (await client.get(path)).json()["detail"] == "Order not found"


async def test_delivery_risk_explains_itself_in_tamil(client, scene) -> None:
    from test_risk import calendar, put, supplier_says

    await calendar(client, scene["site"])
    await put(client, "/fulfillment/settings", {"supplier_update_stale_hours": 1})
    await supplier_says(client, scene, "60", "0", "40", hours_ago=3)  # stale after 1 hour
    path = f"/api/v1/orders/{scene['early']['id']}/risk"
    english = (await client.get(path)).json()["lines"][0]
    tamil = (await client.get(path, headers={"Accept-Language": "ta"})).json()["lines"][0]
    assert english["headline"] == tamil["headline"] == "unknown"  # the rules do not change
    assert "Its status is unknown, not late." in english["issues"][0]["message"]
    assert "அதன் நிலை தெரியாது; தாமதம் அல்ல." in tamil["issues"][0]["message"]
    assert tamil["suggestions"][0]["title"] != english["suggestions"][0]["title"]


async def test_report_definitions_follow_the_screen_language(client, workspace_records) -> None:
    from conftest import sign_in_as

    await sign_in_as(client, "owner@example.com")
    path = "/api/v1/reports/fulfillment"
    english = (await client.get(path)).json()["definitions"]
    tamil = (await client.get(path, headers={"Accept-Language": "ta"})).json()["definitions"]
    assert english.keys() == tamil.keys()
    assert all(tamil[key] == TA[english[key]] for key in english)
