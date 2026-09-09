#!/usr/bin/env python3
"""
Batch sign-in helper for Skland and KuroBBS.

This tool only uses credentials that the user has already obtained from the
official web/app session. It does not implement password login, captcha bypass,
or any anti-bot workaround.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from datetime import datetime
from dataclasses import dataclass
from getpass import getpass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


CONFIG_PATH = Path("accounts.json")
SKLAND_APP_CODE = "4ca99fa6b56cc2ba"
SKLAND_UA = "Skland/1.32.1 (com.hypergryph.skland; build:103201004; Android 33; ) Okhttp/4.11.0"
KURO_UA = "okhttp/3.11.0"
SKLAND_GAME_PRESETS = {
    "arknights": {"label": "明日方舟", "app_code": "arknights", "game_id": 1, "game_ids": [1]},
    "endfield": {"label": "明日方舟：终末地", "app_code": "endfield", "game_id": 2, "game_ids": [2, 4]},
}
DEFAULT_SKLAND_GAMES = ["arknights", "endfield"]


class SignInError(RuntimeError):
    pass


class SignInHttpError(SignInError):
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body
        super().__init__(f"HTTP {status}: {body[:500]}")


@dataclass
class SignResult:
    provider: str
    account: str
    ok: bool
    message: str


def compact_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def requests_style_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def mask(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def read_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SignInError(f"配置文件不存在：{path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_config(path: Path, config: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write("\n")


def json_response(req: Request, timeout: int = 20) -> dict[str, Any]:
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            text = raw.decode("utf-8")
            return json.loads(text)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SignInHttpError(exc.code, body) from exc
    except URLError as exc:
        raise SignInError(f"网络请求失败：{exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise SignInError(f"返回内容不是 JSON：{exc}") from exc


def make_json_request(
    method: str,
    url: str,
    payload: dict[str, Any] | None,
    headers: dict[str, str],
    *,
    body_text: str | None = None,
) -> Request:
    data = None
    final_headers = {"Content-Type": "application/json", **headers}
    if payload is not None:
        body = body_text if body_text is not None else compact_json(payload)
        data = body.encode("utf-8")
    return Request(url, data=data, headers=final_headers, method=method.upper())


def make_form_request(
    method: str,
    url: str,
    payload: dict[str, Any] | None,
    headers: dict[str, str],
) -> Request:
    data = None
    final_headers = {"Content-Type": "application/x-www-form-urlencoded", **headers}
    if payload is not None:
        data = urlencode(payload).encode("utf-8")
    return Request(url, data=data, headers=final_headers, method=method.upper())


def ok_response(resp: dict[str, Any]) -> bool:
    code = resp.get("code", resp.get("status"))
    return code in (0, 200, "0", "200") or resp.get("success") is True


def response_message(resp: dict[str, Any]) -> str:
    return str(resp.get("message") or resp.get("msg") or resp.get("error") or resp)


def is_already_signed_message(text: str) -> bool:
    return any(keyword in text for keyword in ("重复签到", "已签到", "已经签到"))


def is_kuro_already_signed(resp: dict[str, Any]) -> bool:
    code = resp.get("code", resp.get("status"))
    return code in (1511, "1511") or is_already_signed_message(response_message(resp))


def http_error_message(exc: SignInHttpError) -> str:
    try:
        data = json.loads(exc.body)
    except json.JSONDecodeError:
        return exc.body
    return response_message(data)


def normalize_skland_games(value: Any = None) -> list[dict[str, Any]]:
    if not value:
        value = DEFAULT_SKLAND_GAMES
    if isinstance(value, str):
        value = [item.strip() for item in value.split(",") if item.strip()]

    games: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, str):
            if ":" in item:
                parts = [part.strip() for part in item.split(":", 2)]
                if len(parts) >= 2 and parts[0] and parts[1].isdigit():
                    games.append(
                        {
                            "key": parts[0],
                            "label": parts[2] if len(parts) == 3 and parts[2] else parts[0],
                            "app_code": parts[0],
                            "game_id": int(parts[1]),
                            "game_ids": [int(parts[1])],
                        }
                    )
                continue
            preset = SKLAND_GAME_PRESETS.get(item)
            if preset:
                games.append({"key": item, **preset})
            continue
        if isinstance(item, dict):
            key = item.get("key") or item.get("app_code") or item.get("appCode")
            preset = SKLAND_GAME_PRESETS.get(str(key), {})
            app_code = item.get("app_code") or item.get("appCode") or preset.get("app_code")
            game_id = item.get("game_id") or item.get("gameId") or preset.get("game_id")
            label = item.get("label") or item.get("name") or preset.get("label") or app_code
            if app_code and game_id:
                game_ids = item.get("game_ids") or item.get("gameIds") or preset.get("game_ids") or [game_id]
                if isinstance(game_ids, str):
                    game_ids = [int(x.strip()) for x in game_ids.split(",") if x.strip()]
                games.append(
                    {
                        "key": str(key or app_code),
                        "label": str(label),
                        "app_code": str(app_code),
                        "game_id": int(game_id),
                        "game_ids": [int(x) for x in game_ids],
                    }
                )
    return games


class SklandClient:
    grant_code_url = "https://as.hypergryph.com/user/oauth2/v2/grant"
    cred_code_url = "https://zonai.skland.com/api/v1/user/auth/generate_cred_by_code"
    refresh_token_url = "https://zonai.skland.com/api/v1/auth/refresh"
    binding_url = "https://zonai.skland.com/api/v1/game/player/binding"
    attendance_url = "https://zonai.skland.com/api/v1/game/attendance"
    endfield_attendance_url = "https://zonai.skland.com/web/v1/game/endfield/attendance"

    def __init__(self, account: dict[str, Any], dry_run: bool = False) -> None:
        self.account = account
        self.dry_run = dry_run
        self.name = account.get("name") or "skland"
        self.device_id = account.get("device_id") or uuid.uuid4().hex
        self.cred = account.get("cred")
        self.cred_token = account.get("cred_token")
        self.games = normalize_skland_games(account.get("skland_games"))

    def base_headers(self) -> dict[str, str]:
        return {
            "User-Agent": SKLAND_UA,
            "Connection": "close",
            "dId": self.device_id,
        }

    def signed_headers(self, url: str, method: str, body_text: str = "") -> dict[str, str]:
        if not self.cred or not self.cred_token:
            raise SignInError("森空岛账号缺少 cred 或 cred_token")

        parsed = urlparse(url)
        body_or_query = parsed.query if method.lower() == "get" else body_text
        timestamp = str(int(time.time()) - 2)
        header_ca = {"platform": "", "timestamp": timestamp, "dId": "", "vName": ""}
        header_ca_text = compact_json(header_ca)
        raw = f"{parsed.path}{body_or_query}{timestamp}{header_ca_text}"
        hex_digest = hmac.new(
            self.cred_token.encode("utf-8"),
            raw.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        sign = hashlib.md5(hex_digest.encode("utf-8")).hexdigest()

        headers = {
            "User-Agent": SKLAND_UA,
            "Connection": "close",
            "cred": self.cred,
            "sign": sign,
            **header_ca,
        }
        return headers

    def ensure_cred(self, force_refresh: bool = False) -> None:
        if self.cred and self.cred_token and not force_refresh:
            return
        self.refresh_cred()

    def refresh_cred(self) -> None:
        token = self.account.get("token")
        if not token:
            raise SignInError("森空岛账号需要 token，或同时提供 cred 和 cred_token")

        grant_payload = {"appCode": SKLAND_APP_CODE, "token": token, "type": 0}
        grant_resp = json_response(
            make_json_request("POST", self.grant_code_url, grant_payload, self.base_headers())
        )
        if not ok_response(grant_resp):
            raise SignInError(f"获取森空岛 grant code 失败：{response_message(grant_resp)}")
        grant_code = grant_resp.get("data", {}).get("code")
        if not grant_code:
            raise SignInError(f"森空岛 grant code 响应缺少 data.code：{grant_resp}")

        cred_payload = {"code": grant_code, "kind": 1}
        cred_resp = json_response(
            make_json_request("POST", self.cred_code_url, cred_payload, self.base_headers())
        )
        if not ok_response(cred_resp):
            raise SignInError(f"获取森空岛 cred 失败：{response_message(cred_resp)}")
        data = cred_resp.get("data") or {}
        self.cred = data.get("cred")
        self.cred_token = data.get("token")
        if not self.cred or not self.cred_token:
            raise SignInError(f"森空岛 cred 响应缺少 cred/token：{cred_resp}")
        self.account["cred"] = self.cred
        self.account["cred_token"] = self.cred_token

    def refresh_cred_token(self) -> None:
        if not self.cred:
            raise SignInError("森空岛账号缺少 cred，无法自动刷新 cred_token")
        resp = json_response(
            make_json_request("GET", self.refresh_token_url, None, {**self.base_headers(), "cred": self.cred})
        )
        if not ok_response(resp):
            raise SignInError(f"刷新森空岛 cred_token 失败：{response_message(resp)}")
        token = (resp.get("data") or {}).get("token")
        if not token:
            raise SignInError(f"刷新森空岛 cred_token 失败：响应缺少 data.token：{resp}")
        self.cred_token = token
        self.account["cred_token"] = token

    def is_refreshable_auth_error(self, exc: SignInHttpError) -> bool:
        if exc.status != 401:
            return False
        try:
            data = json.loads(exc.body)
        except json.JSONDecodeError:
            return False
        return data.get("code") in (10000, "10000")

    def signed_json_response(
        self,
        method: str,
        url: str,
        payload: dict[str, Any] | None = None,
        *,
        body_text: str = "",
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        body_for_sign = body_text if payload is not None else ""
        headers = self.signed_headers(url, method, body_for_sign)
        if extra_headers:
            headers.update(extra_headers)
        try:
            return json_response(make_json_request(method, url, payload, headers, body_text=body_text or None))
        except SignInHttpError as exc:
            if not self.is_refreshable_auth_error(exc):
                raise
            self.refresh_cred_token()
            headers = self.signed_headers(url, method, body_for_sign)
            if extra_headers:
                headers.update(extra_headers)
            return json_response(make_json_request(method, url, payload, headers, body_text=body_text or None))

    def binding_list(self) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        try:
            resp = self.signed_json_response("GET", self.binding_url)
        except SignInHttpError as exc:
            if exc.status == 403:
                raise SignInError(
                    "获取森空岛绑定角色时鉴权失败。请重新获取森空岛 token，"
                    "或清空 cred/cred_token 后只保留 token。原始返回："
                    f"{exc.body[:300]}"
                ) from exc
            raise
        if not ok_response(resp):
            raise SignInError(f"获取森空岛角色失败：{response_message(resp)}")

        roles: list[tuple[dict[str, Any], dict[str, Any]]] = []
        games_by_app_code = {item["app_code"]: item for item in self.games}
        for game in resp.get("data", {}).get("list", []):
            game_config = games_by_app_code.get(game.get("appCode"))
            if not game_config:
                continue
            game_config = dict(game_config)
            if game.get("gameId") or game.get("game_id"):
                binding_game_id = int(game.get("gameId") or game.get("game_id"))
                existing_ids = [int(x) for x in game_config.get("game_ids", [])]
                game_config["game_id"] = binding_game_id
                game_config["game_ids"] = [binding_game_id] + [
                    game_id for game_id in existing_ids if game_id != binding_game_id
                ]
            for role in game.get("bindingList") or []:
                roles.append((game_config, role))
        return roles

    def sign_endfield_role(self, game_name: str, binding: dict[str, Any], role: dict[str, Any]) -> SignResult:
        nickname = role.get("nickname") or role.get("roleName") or binding.get("nickName") or role.get("roleId")
        role_id = role.get("roleId")
        server_id = role.get("serverId")
        if not role_id or not server_id:
            return SignResult("skland", self.name, False, f"{game_name}/{nickname}：缺少 roleId 或 serverId")

        try:
            resp = self.signed_json_response(
                "POST",
                self.endfield_attendance_url,
                extra_headers={"sk-game-role": f"3_{role_id}_{server_id}"},
            )
        except SignInHttpError as exc:
            message = http_error_message(exc)
            if is_already_signed_message(message):
                return SignResult("skland", self.name, True, f"{game_name}/{nickname}：今日已签到")
            if exc.status == 403:
                return SignResult(
                    "skland",
                    self.name,
                    False,
                    f"{game_name}/{nickname}：终末地签到请求鉴权失败。"
                    "请重新刷新森空岛凭据后再试。"
                    f"原始返回：{exc.body[:300]}",
                )
            raise

        if not ok_response(resp):
            message = response_message(resp)
            if is_already_signed_message(message):
                return SignResult("skland", self.name, True, f"{game_name}/{nickname}：今日已签到")
            return SignResult("skland", self.name, False, f"{game_name}/{nickname}：{message}")
        return SignResult("skland", self.name, True, f"{game_name}/{nickname}：{format_endfield_awards(resp)}")

    def sign_arknights_role(self, game_config: dict[str, Any], role: dict[str, Any]) -> SignResult:
        role_name = role.get("nickName") or role.get("uid") or "unknown"
        game_name = game_config["label"]
        game_ids = game_config.get("game_ids") or [game_config["game_id"]]
        game_ids = list(dict.fromkeys(int(game_id) for game_id in game_ids))
        last_auth_error = ""

        for game_id in game_ids:
            payload = {"gameId": game_id, "uid": role.get("uid")}
            body_text = requests_style_json(payload)
            try:
                resp = self.signed_json_response("POST", self.attendance_url, payload, body_text=body_text)
            except SignInHttpError as exc:
                message = http_error_message(exc)
                if is_already_signed_message(message):
                    return SignResult("skland", self.name, True, f"{game_name}/{role_name}：今日已签到，gameId={game_id}")
                if exc.status == 403:
                    last_auth_error = exc.body[:300]
                    continue
                raise
            if not ok_response(resp):
                message = response_message(resp)
                if is_already_signed_message(message):
                    return SignResult("skland", self.name, True, f"{game_name}/{role_name}：今日已签到，gameId={game_id}")
                return SignResult("skland", self.name, False, f"{game_name}/{role_name}：{message}，gameId={game_id}")

            awards = resp.get("data", {}).get("awards") or []
            award_text = format_skland_awards(awards)
            return SignResult("skland", self.name, True, f"{game_name}/{role_name}：{award_text}，gameId={game_id}")

        return SignResult(
            "skland",
            self.name,
            False,
            f"{game_name}/{role_name}：签到请求鉴权失败，已尝试 gameId={game_ids}。"
            "请确认该 token 对这个游戏有权限，并重新获取 token。"
            f"原始返回：{last_auth_error}",
        )

    def sign(self) -> list[SignResult]:
        if self.dry_run:
            shown = self.account.get("token") or self.cred
            game_names = "、".join(item["label"] for item in self.games)
            return [SignResult("skland", self.name, True, f"dry-run，游戏 {game_names}，凭据 {mask(shown)}")]

        self.ensure_cred()
        roles = self.binding_list()
        if not roles:
            game_names = "、".join(item["label"] for item in self.games)
            return [SignResult("skland", self.name, False, f"没有找到已绑定的森空岛角色：{game_names}")]

        results: list[SignResult] = []
        for game_config, role in roles:
            if game_config["app_code"] == "endfield":
                endfield_roles = role.get("roles") or []
                if role.get("defaultRole"):
                    endfield_roles = [role["defaultRole"]]
                if not endfield_roles:
                    results.append(
                        SignResult("skland", self.name, False, f"{game_config['label']}/{role.get('nickName') or role.get('uid')}：没有找到终末地 roleId/serverId")
                    )
                    continue
                for endfield_role in endfield_roles:
                    results.append(self.sign_endfield_role(game_config["label"], role, endfield_role))
            else:
                results.append(self.sign_arknights_role(game_config, role))
        return results


def format_skland_awards(awards: list[dict[str, Any]]) -> str:
    if not awards:
        return "签到成功"
    parts = []
    for item in awards:
        resource = item.get("resource") or {}
        name = resource.get("name") or item.get("name") or "奖励"
        count = item.get("count") or 1
        parts.append(f"{name}x{count}")
    return "签到成功，获得 " + "、".join(parts)


def format_endfield_awards(resp: dict[str, Any]) -> str:
    data = resp.get("data") or {}
    resource_map = data.get("resourceInfoMap") or {}
    award_ids = data.get("awardIds") or []
    parts: list[str] = []
    for award in award_ids:
        award_id = str(award.get("id") or "")
        resource = resource_map.get(award_id) or {}
        name = resource.get("name") or award_id or "奖励"
        count = resource.get("count") or 1
        parts.append(f"{name}x{count}")
    if parts:
        return "签到成功，获得 " + "、".join(parts)
    return "签到成功"


class KuroClient:
    base_url = "https://api.kurobbs.com"

    def __init__(self, account: dict[str, Any], dry_run: bool = False) -> None:
        self.account = account
        self.dry_run = dry_run
        self.name = account.get("name") or "kuro"
        self.token = account.get("token")
        self.device_code = account.get("device_code") or account.get("token_did")
        self.bat = account.get("bat")
        self.extra_headers = account.get("extra_headers") or {}

    def headers(self) -> dict[str, str]:
        if not self.token:
            raise SignInError("库街区账号缺少 token")

        headers = {
            "User-Agent": KURO_UA,
            "X-Requested-With": "com.kurogame.kjq",
            "Source": str(self.account.get("source") or "h5"),
            "Version": str(self.account.get("version") or "2.2.0"),
            "DevCode": self.device_code or "",
            "Token": self.token,
            "CountryCode": "CN",
            "Accept-Encoding": "gzip",
        }
        if self.bat:
            headers["b-at"] = self.bat
        headers.update({str(k): str(v) for k, v in self.extra_headers.items()})
        return headers

    def post_form(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return json_response(
            make_form_request("POST", self.base_url + path, payload, self.headers())
        )

    def get_roles(self, game_id: int) -> list[dict[str, Any]]:
        resp = self.post_form("/gamer/role/list", {"gameId": game_id})
        if not ok_response(resp):
            raise SignInError(f"获取库街区角色失败：{response_message(resp)}")
        return find_role_items(resp, expected_game_id=game_id)

    def sign_role(self, role: dict[str, Any]) -> SignResult:
        role_name = role.get("roleName") or role.get("roleId") or "unknown"
        game_id = role.get("gameId")
        payload = {
            "gameId": game_id,
            "serverId": role.get("serverId"),
            "roleId": role.get("roleId"),
            "userId": role.get("userId"),
        }
        payload = {k: v for k, v in payload.items() if v is not None}

        init_resp = self.post_form("/encourage/signIn/initSignInV2", payload)
        if ok_response(init_resp):
            if find_truthy_key(init_resp, {"isSigIn", "isSignIn", "hasSignIn"}):
                return SignResult("kuro", self.name, True, f"{role_name}：今日已签到")
        elif is_kuro_already_signed(init_resp):
            return SignResult("kuro", self.name, True, f"{role_name}：今日已签到")

        sign_payload = dict(payload)
        sign_payload["reqMonth"] = datetime.now().strftime("%m")
        sign_resp = self.post_form("/encourage/signIn/v2", sign_payload)
        if not ok_response(sign_resp):
            if is_kuro_already_signed(sign_resp):
                return SignResult("kuro", self.name, True, f"{role_name}：今日已签到")
            init_message = response_message(init_resp)
            sign_message = response_message(sign_resp)
            if not ok_response(init_resp):
                return SignResult("kuro", self.name, False, f"{role_name}：初始化返回 {init_message}；签到返回 {sign_message}")
            return SignResult("kuro", self.name, False, f"{role_name}：{sign_message}")
        return SignResult("kuro", self.name, True, f"{role_name}：{format_kuro_reward(sign_resp)}")

    def sign(self) -> list[SignResult]:
        if self.dry_run:
            return [SignResult("kuro", self.name, True, f"dry-run，token {mask(self.token)}")]

        direct_roles = self.account.get("roles") or []
        if direct_roles:
            roles = [copy.deepcopy(item) for item in direct_roles]
        else:
            roles = []
            for game_id in self.account.get("game_ids") or [3]:
                roles.extend(self.get_roles(int(game_id)))

        if not roles:
            return [SignResult("kuro", self.name, False, "没有找到库街区游戏角色")]
        return [self.sign_role(role) for role in roles]


def find_role_items(data: Any, expected_game_id: int | None = None) -> list[dict[str, Any]]:
    roles: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            has_role = {"roleId", "serverId"}.issubset(value.keys())
            if has_role:
                if expected_game_id is None or str(value.get("gameId")) == str(expected_game_id):
                    roles.append(value)
                return
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(data)
    return roles


def find_truthy_key(data: Any, keys: set[str]) -> bool:
    if isinstance(data, dict):
        for key, value in data.items():
            if key in keys and value is True:
                return True
            if find_truthy_key(value, keys):
                return True
    elif isinstance(data, list):
        return any(find_truthy_key(item, keys) for item in data)
    return False


def format_kuro_reward(resp: dict[str, Any]) -> str:
    names: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            name = value.get("goodsName") or value.get("name") or value.get("itemName")
            count = value.get("goodsNum") or value.get("num") or value.get("count")
            if name:
                names.append(f"{name}x{count or 1}")
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(resp.get("data", resp))
    if names:
        return "签到成功，获得 " + "、".join(dict.fromkeys(names))
    return "签到成功"


def active_accounts(config: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in config.get("accounts", []) if item.get("enabled", True)]


def run_sign(config_path: Path, dry_run: bool = False) -> int:
    config = read_config(config_path)
    before_config = compact_json(config)
    accounts = active_accounts(config)
    if not accounts:
        print("没有启用的账号。")
        return 1

    all_results: list[SignResult] = []
    for account in accounts:
        provider = str(account.get("provider") or "").lower()
        try:
            if provider == "skland":
                all_results.extend(SklandClient(account, dry_run=dry_run).sign())
            elif provider == "kuro":
                all_results.extend(KuroClient(account, dry_run=dry_run).sign())
            else:
                all_results.append(
                    SignResult(provider or "unknown", account.get("name") or "", False, "未知平台")
                )
        except SignInError as exc:
            all_results.append(
                SignResult(provider or "unknown", account.get("name") or "", False, str(exc))
            )

    for result in all_results:
        mark = "OK" if result.ok else "FAIL"
        print(f"[{mark}] {result.provider}/{result.account} - {result.message}")
    if not dry_run and compact_json(config) != before_config:
        write_config(config_path, config)
        print(f"[OK] 已保存更新后的账号凭据：{config_path}")
    return 0 if all(item.ok for item in all_results) else 2


def command_init(config_path: Path) -> int:
    if config_path.exists():
        print(f"配置文件已存在：{config_path}")
        return 0
    write_config(config_path, {"accounts": []})
    print(f"已创建空配置：{config_path}")
    return 0


def command_list(config_path: Path) -> int:
    config = read_config(config_path)
    accounts = config.get("accounts", [])
    if not accounts:
        print("配置里还没有账号。")
        return 0
    for index, account in enumerate(accounts, start=1):
        state = "启用" if account.get("enabled", True) else "停用"
        provider = account.get("provider", "unknown")
        name = account.get("name", "")
        print(f"{index}. {provider}/{name} - {state}")
    return 0


def command_add(config_path: Path, provider: str) -> int:
    config = {"accounts": []}
    if config_path.exists():
        config = read_config(config_path)
    config.setdefault("accounts", [])

    name = input("账号备注：").strip() or provider
    if provider == "skland":
        print("森空岛可填 token，或填 cred+cred_token。留空的项会跳过。")
        token = getpass("token：").strip()
        cred = getpass("cred：").strip()
        cred_token = getpass("cred_token：").strip()
        item = {
            "provider": "skland",
            "name": name,
            "enabled": True,
            "token": token,
            "cred": cred,
            "cred_token": cred_token,
            "device_id": uuid.uuid4().hex,
            "skland_games": DEFAULT_SKLAND_GAMES,
        }
        item = {k: v for k, v in item.items() if v != ""}
    elif provider == "kuro":
        print("库街区至少需要 token。默认签到鸣潮 gameId=3，device_code/devCode 可以留空。")
        token = getpass("token：").strip()
        device_code = input("device_code/devCode（可选）：").strip()
        game_ids = input("game_ids（默认 3，多个用逗号）：").strip()
        item = {
            "provider": "kuro",
            "name": name,
            "enabled": True,
            "token": token,
            "device_code": device_code,
            "game_ids": [int(x.strip()) for x in game_ids.split(",") if x.strip()] or [3],
        }
    else:
        raise SignInError(f"不支持的平台：{provider}")

    config["accounts"].append(item)
    write_config(config_path, config)
    print(f"已保存账号到：{config_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="森空岛/库街区一键批量签到工具")
    parser.add_argument("-c", "--config", default=str(CONFIG_PATH), help="配置文件路径")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="创建空配置文件")
    sub.add_parser("list", help="列出已保存账号")

    sign = sub.add_parser("sign", help="执行批量签到")
    sign.add_argument("--dry-run", action="store_true", help="只检查配置，不发送签到请求")

    add_skland = sub.add_parser("add-skland", help="交互式添加森空岛账号")
    add_skland.set_defaults(add_provider="skland")
    add_kuro = sub.add_parser("add-kuro", help="交互式添加库街区账号")
    add_kuro.set_defaults(add_provider="kuro")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config_path = Path(args.config)
    try:
        if args.command == "init":
            return command_init(config_path)
        if args.command == "list":
            return command_list(config_path)
        if args.command == "sign":
            return run_sign(config_path, dry_run=args.dry_run)
        if args.command in {"add-skland", "add-kuro"}:
            return command_add(config_path, args.add_provider)
        parser.print_help()
        return 1
    except SignInError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
