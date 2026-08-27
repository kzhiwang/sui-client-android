# -*- coding: utf-8 -*-
"""
S-UI 面板 API 核心客户端（无界面依赖）
对接 s-ui (https://github.com/alireza0/s-ui) 面板 API：
  - 登录（POST api/login, form: user/pass, 会话 Cookie）
  - 入站列表（GET api/inbounds）
  - 用户列表（GET api/clients [?id=]）
  - 添加用户（POST api/save, object=clients&action=new&data=<client json>）
数据结构与官方前端(s-ui-frontend)生成的完全一致。
"""
import base64
import hashlib
import hmac
import json
import os
import random
import string
import sys
import time

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)



SEQ = string.ascii_letters + string.digits


# ---------------- 随机凭据生成（与 s-ui 前端 randomUtil 一致） ----------------

def random_seq(n: int) -> str:
    return "".join(random.choice(SEQ) for _ in range(n))


def random_uuid() -> str:
    b = bytearray(os.urandom(16))
    b[6] = (b[6] & 0x0F) | 0x40
    b[8] = (b[8] & 0x3F) | 0x80
    h = b.hex()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def random_ss_password(n: int) -> str:
    return base64.b64encode(os.urandom(n)).decode()


# ---------------- 密码加密（避免明文落盘，且可随配置迁移到其它设备） ----------------
#
# 落盘策略：账号密码在写入配置时加密，内存中仍为明文便于使用。
# 采用纯 Python 标准库（hashlib + hmac）实现「SHA-256 流加密 + HMAC 完整性校验」，
# 密钥由程序内置固定种子派生 —— 因此配置文件连同本程序一起拷贝到任意设备都能正常解密。
# 为什么不用 cryptography(Fernet)：新版 cryptography 用 Rust 实现，在 Android 交叉编译
# （尤其 32 位 armeabi-v7a）会报 LONG_BIT 错误且无对应 wheel，故改为无依赖的纯 Python 方案。
# 代价：密钥随程序分发，理论上可被反编译提取，故仍非"绝对安全"，但已非明文。
# 兼容：旧明文密码（无前缀）读取时原样返回；fernet:/dpapi:/obf: 前缀密文在本实现下无法解密，返回空（需重新输入密码）。

# 固定种子（随程序分发，保证可移植）。如需更强安全可改为运行时从用户处获取，
# 但那样会失去“拷到别的设备免输密码”的便利性。
_KEY_SEED = b"s-ui-client-portable-static-key-2026"


def _key_material() -> bytes:
    return hashlib.sha256(_KEY_SEED).digest()


def _keystream(key: bytes, iv: bytes, length: int) -> bytes:
    """基于 SHA-256 的计数模式密钥流（CTR），产出与明文等长的伪随机字节。"""
    out = b""
    counter = 0
    while len(out) < length:
        out += hashlib.sha256(key + iv + counter.to_bytes(4, "big")).digest()
        counter += 1
    return out[:length]


def encrypt_secret(plain: str) -> str:
    if not plain:
        return ""
    data = plain.encode("utf-8")
    key = _key_material()
    iv = os.urandom(16)
    enc = bytes(b ^ k for b, k in zip(data, _keystream(key, iv, len(data))))
    mac = hmac.new(key, iv + enc, hashlib.sha256).digest()
    return "pyaes:" + base64.b64encode(iv + enc + mac).decode("ascii")


def decrypt_secret(cipher: str) -> str:
    if not cipher:
        return ""
    if cipher.startswith("pyaes:"):
        try:
            raw = base64.b64decode(cipher[len("pyaes:"):])
            key = _key_material()
            iv, enc, mac = raw[:16], raw[16:-32], raw[-32:]
            if not hmac.compare_digest(hmac.new(key, iv + enc, hashlib.sha256).digest(), mac):
                return ""
            return bytes(b ^ k for b, k in zip(enc, _keystream(key, iv, len(enc)))).decode("utf-8")
        except Exception:
            return ""
    if cipher.startswith(("fernet:", "dpapi:", "obf:")):
        return ""  # 其它加密方案在本实现下无法解密，返回空（需重新输入密码）
    return cipher  # 旧明文配置兼容




def build_client_config(name: str, custom_uuid: str = "", custom_password: str = "") -> dict:
    """生成全协议 client config，结构与 s-ui 前端 randomConfigs 完全一致。
    custom_uuid / custom_password 传入则替代随机值。"""
    pw = custom_password if custom_password else random_seq(10)
    uuid_ = custom_uuid if custom_uuid else random_uuid()
    ss16 = random_ss_password(16)
    ss32 = random_ss_password(32)
    return {
        "mixed": {"username": name, "password": pw},
        "socks": {"username": name, "password": pw},
        "http": {"username": name, "password": pw},
        "shadowsocks": {"name": name, "password": ss32},
        "shadowsocks16": {"name": name, "password": ss16},
        "shadowtls": {"name": name, "password": ss32},
        "vmess": {"name": name, "uuid": uuid_, "alterId": 0},
        "vless": {"name": name, "uuid": uuid_, "flow": "xtls-rprx-vision"},
        "anytls": {"name": name, "password": pw},
        "trojan": {"name": name, "password": pw},
        "naive": {"username": name, "password": pw},
        "hysteria": {"name": name, "auth_str": pw},
        "tuic": {"name": name, "uuid": uuid_, "password": pw},
        "hysteria2": {"name": name, "password": pw},
    }


# ---------------- 异常 ----------------

class SuiApiError(Exception):
    pass


# ---------------- API 客户端 ----------------

class SuiClient:
    def __init__(self, base_url: str):
        # 规范化地址：补协议、补末尾斜杠
        url = base_url.strip()
        if url and "://" not in url:
            url = "http://" + url
        if not url.endswith("/"):
            url += "/"
        self.base_url = url
        self.session = requests.Session()
        self.session.verify = False
        self.session.headers.update({
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "s-ui-client/1.0",
        })

    # ---- 底层请求 ----

    def _get(self, path: str, params: dict | None = None) -> dict:
        try:
            r = self.session.get(self.base_url + path, params=params, timeout=20)
        except requests.RequestException as e:
            raise SuiApiError(f"连接面板失败：{e.__class__.__name__}: {e}")
        return self._parse(r)

    def _post(self, path: str, data: dict) -> dict:
        try:
            r = self.session.post(self.base_url + path, data=data, timeout=30)
        except requests.RequestException as e:
            raise SuiApiError(f"连接面板失败：{e.__class__.__name__}: {e}")
        return self._parse(r)

    @staticmethod
    def _parse(r) -> dict:
        if r.status_code == 404:
            raise SuiApiError("接口返回 404：请检查面板地址是否正确（注意面板路径，新版 s-ui 默认为 /app/）")
        if r.status_code in (301, 302) or r.history:
            raise SuiApiError("面板返回了重定向（可能是登录会话失效或地址路径不对），请重新登录")
        try:
            body = r.json()
        except ValueError:
            snippet = (r.text or "")[:200].replace("\n", " ")
            raise SuiApiError(f"面板返回了非 JSON 内容（HTTP {r.status_code}）：{snippet}…"
                             if snippet else f"面板返回了非 JSON 内容（HTTP {r.status_code}），请确认地址指向 s-ui 面板")
        if not body.get("success", False):
            raise SuiApiError(body.get("msg") or f"操作失败（HTTP {r.status_code}）")
        return body

    # ---- 业务接口 ----

    def login(self, user: str, password: str) -> None:
        self._post("api/login", {"user": user, "pass": password})

    def logout(self) -> None:
        try:
            self._get("api/logout")
        except SuiApiError:
            pass

    def get_inbounds(self) -> list:
        body = self._get("api/inbounds")
        return (body.get("obj") or {}).get("inbounds") or []

    @staticmethod
    def _clients_from(body: dict) -> list:
        """GET api/clients 返回 obj={"clients":[...]}（与官方前端 msg.obj.clients 一致），
        兼容旧版/异常情况下 obj 直接为数组。"""
        obj = body.get("obj")
        if isinstance(obj, dict):
            return obj.get("clients") or []
        if isinstance(obj, list):
            return obj
        return []

    def get_clients(self) -> list:
        body = self._get("api/clients")
        return self._clients_from(body)

    def get_client_detail(self, client_id) -> list:
        body = self._get("api/clients", {"id": str(client_id)})
        return self._clients_from(body)

    def _save_clients(self, action: str, data) -> dict:
        return self._post("api/save", {
            "object": "clients",
            "action": action,
            "data": json.dumps(data, ensure_ascii=False),
            "initUsers": "",
        })

    def add_client(self, name: str, inbound_ids: list, volume_bytes: int = 0,
                   expiry_ts: int = 0, desc: str = "", group: str = "", remark: str = "",
                   enable: bool = True, custom_uuid: str = "", custom_password: str = "") -> dict:
        client = {
            "enable": enable,
            "name": name,
            "config": build_client_config(name, custom_uuid, custom_password),
            "inbounds": sorted(inbound_ids),
            "links": [],
            "volume": volume_bytes,
            "expiry": expiry_ts,
            "up": 0,
            "down": 0,
            "desc": desc,
            "group": group,
            "remark": remark,
            "delayStart": False,
            "autoReset": False,
            "resetDays": 0,
            "nextReset": 0,
            "totalUp": 0,
            "totalDown": 0,
        }
        return self._save_clients("new", client)

    def del_client(self, client_id) -> dict:
        """删除用户：object=clients&action=del&data=<id>（见 service/client.go case "del"）"""
        return self._save_clients("del", int(client_id))

    def update_client(self, client: dict) -> dict:
        """修改用户：object=clients&action=edit&data=<完整 client JSON>。
        client 必须是 get_client_detail 取回的完整对象（含 id/config/links/inbounds 等），
        在其上修改字段后整体回传；服务端会自动同步 config 中的 name/username 并重建链接。"""
        return self._save_clients("edit", client)


# ---------------- 本地配置（记住面板地址/账号） ----------------
# 配置文件放在 SUI-Client.exe 同目录下（便携），开发态则与脚本同目录。
# 文件名不含点前缀，避免和家目录下的隐藏文件混淆。

def _config_dir() -> str:
    if getattr(sys, "frozen", False):
        # PyInstaller 打包后 sys.executable 即 EXE 自身路径
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


# 配置路径可在运行时覆盖（Android 上需指向 app.user_data_dir）。
# 默认：打包态取 EXE 同目录，开发态取脚本同目录。
_config_file = None


def get_config_file() -> str:
    global _config_file
    if _config_file is None:
        _config_file = os.path.join(_config_dir(), "sui_client.json")
    return _config_file


def set_config_file(path: str) -> None:
    """覆盖配置文件路径（如 Kivy 在 Android 上指向 user_data_dir）。"""
    global _config_file
    _config_file = path


# 旧版配置位于用户家目录（隐藏文件），首次启动时迁移到新位置
_OLD_CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".sui_client.json")


def _migrate_old_config() -> None:
    cfg_file = get_config_file()
    if os.path.exists(_OLD_CONFIG_FILE) and not os.path.exists(cfg_file):
        try:
            import shutil
            shutil.copyfile(_OLD_CONFIG_FILE, cfg_file)
        except Exception:
            pass


def load_config() -> dict:
    _migrate_old_config()
    try:
        with open(get_config_file(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    try:
        with open(get_config_file(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ---------------- 多面板账号管理 ----------------

def _host_of(url: str) -> str:
    u = url.split("//", 1)[-1]
    return u.split("/", 1)[0] or url


def load_accounts():
    """返回 (账号列表, 当前选中下标)。兼容旧版单面板 url/user 配置。
    账号结构：{"name": 显示名, "url": 面板地址, "user": 用户名, "pass": 密码}"""
    cfg = load_config()
    accts = cfg.get("accounts")
    if not isinstance(accts, list):
        accts = []
        if cfg.get("url"):
            accts.append({
                "name": cfg.get("user") or _host_of(cfg["url"]),
                "url": cfg["url"],
                "user": cfg.get("user", ""),
                "pass": "",
            })
    accts = [a for a in accts if isinstance(a, dict) and a.get("url")]
    # 落盘密文，读入内存时解密为明文供使用
    for a in accts:
        a["pass"] = decrypt_secret(a.get("pass", ""))
    try:
        cur = int(cfg.get("current", 0) or 0)
    except (TypeError, ValueError):
        cur = 0
    if cur < 0 or cur >= len(accts):
        cur = 0
    return accts, cur


def save_accounts(accounts: list, current: int = 0) -> None:
    # 写入前对密码加密，内存中的明文不落盘
    safe = []
    for a in accounts:
        if not isinstance(a, dict):
            continue
        c = dict(a)
        c["pass"] = encrypt_secret(a.get("pass", ""))
        safe.append(c)
    save_config({"accounts": safe, "current": current})


def upsert_account(accounts: list, account: dict, current: int = -1):
    """新增或更新一个账号（按 url+user 去重），返回 (新列表, 选中下标)"""
    url = account.get("url", "").strip()
    user = account.get("user", "").strip()
    for i, a in enumerate(accounts):
        if a.get("url", "").strip() == url and a.get("user", "").strip() == user:
            accounts[i] = dict(account)
            return accounts, i
    accounts.append(dict(account))
    idx = len(accounts) - 1
    return accounts, (current if current >= 0 else idx)


def find_account_index(accounts: list, url: str, user: str) -> int:
    url = url.strip()
    user = user.strip()
    for i, a in enumerate(accounts):
        if a.get("url", "").strip() == url and a.get("user", "").strip() == user:
            return i
    return -1


# ---------------- 展示工具 ----------------

def fmt_size(n) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return str(n)


def fmt_ts(ts) -> str:
    ts = int(ts or 0)
    if ts <= 0:
        return "不限"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
