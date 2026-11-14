"""Local HTTP controller using the same observation/action schema as stdio."""
import json
import urllib.request
from urllib.parse import urlsplit

from cellgame.shared.observation import observation_to_json
from cellgame.shared.contract import CONTRACT_VERSION

from .executor import to_intentions, world_size


def controller_message(batch):
    """JSON request shared by the HTTP service and stdio agents."""
    message = {
        "version": 1, "contract_version": CONTRACT_VERSION, "tick": int(batch["tick"]),
        "cells": batch["cells"].tolist(),
        "neighborhood": batch["neighborhood"].tolist(),
        "env": batch["env"].tolist(),
        "constraints": batch["constraints"],
    }
    if batch.get("observation") is not None:
        message["observation"] = observation_to_json(batch["observation"])
    return message


def response_actions(reply, batch):
    """Shared HTTP/stdio controller response validation (local interface v1)."""
    if not isinstance(reply, dict) or type(reply.get("tick")) is not int or reply["tick"] != batch["tick"]:
        raise ValueError("controller response tick 不匹配")
    actions = reply.get("actions")
    if not isinstance(actions, list) or len(actions) > len(batch["cells"]):
        raise ValueError("controller 返回了无效或过多的动作")
    return to_intentions(actions, batch["cells"], *world_size(batch))


def validate_service_url(url):
    if not isinstance(url, str) or len(url) > 2048:
        raise ValueError("请输入有效的本地服务地址")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("服务端口无效") from exc
    if (parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
            or parsed.username is not None or parsed.password is not None or parsed.fragment):
        raise ValueError("服务地址必须是本机 HTTP 地址，例如 http://127.0.0.1:9000/decide")
    if port is None:
        raise ValueError("请填写本地服务的端口")
    return url


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("本地服务不允许重定向")


def call_service(url, batch, timeout):
    payload = controller_message(batch)
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(validate_service_url(url), data=data,
                                     headers={"Content-Type": "application/json"}, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        raw = response.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError("本地服务响应过大")
    reply = json.loads(raw)
    return response_actions(reply, batch)
