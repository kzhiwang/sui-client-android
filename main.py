# -*- coding: utf-8 -*-
"""
s-ui 面板客户端 —— Android 版（Kivy）
复用同目录下的 suicore.py（纯 Python 的 s-ui API 客户端）。
功能：多面板账号管理、登录、用户列表、添加/编辑/删除（批量）用户。
"""

import os
import sys
import time
import threading

from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.spinner import Spinner
from kivy.uix.modalview import ModalView
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp

# 让本文件能 import 同目录的 suicore
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import suicore
from suicore import (
    SuiClient, SuiApiError,
    load_accounts, save_accounts, upsert_account, find_account_index,
)

# 手机端输入法不被输入框遮挡
try:
    Window.softinput_mode = "below_target"
except Exception:
    pass


# ---------------- 通用工具 ----------------

def run_in_thread(work, on_done, on_error):
    """在后台线程执行 work，结果/异常回到主线程回调。"""
    def target():
        try:
            res = work()
            Clock.schedule_once(lambda dt: on_done(res), 0)
        except Exception as e:  # noqa: BLE001
            Clock.schedule_once(lambda dt: on_error(e), 0)
    threading.Thread(target=target, daemon=True).start()


def show_error(title, msg):
    pv = ModalView(size_hint=(0.85, 0.45))
    bl = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))
    bl.add_widget(Label(
        text="[b]%s[/b]\n\n%s" % (title, str(msg)),
        markup=True, halign="center", valign="middle",
        text_size=(dp(300), None)))
    btn = Button(text="确定", size_hint_y=None, height=dp(44))
    btn.bind(on_release=pv.dismiss)
    bl.add_widget(btn)
    pv.add_widget(bl)
    pv.open()


def show_info(title, msg):
    show_error(title, msg)


class Field(BoxLayout):
    """一行：左侧标签 + 右侧输入控件。"""

    def __init__(self, label, widget, **kw):
        super().__init__(orientation="horizontal", size_hint_y=None,
                         height=dp(48), spacing=dp(8), **kw)
        lab = Label(text=label, size_hint_x=None, width=dp(92),
                    halign="right", valign="center",
                    text_size=(dp(88), None))
        self.add_widget(lab)
        self.add_widget(widget)


def make_button(text, on_release=None, height=dp(46), **kw):
    kw.setdefault("size_hint_y", None)
    kw.setdefault("height", height)
    b = Button(text=text, **kw)
    if on_release:
        b.bind(on_release=on_release)
    return b


# ---------------- 账号管理弹窗 ----------------

class AccountManagerPopup(ModalView):
    def __init__(self, accounts, on_close, **kw):
        super().__init__(size_hint=(0.92, 0.9), **kw)
        self.accounts = [dict(a) for a in accounts]
        self.on_close = on_close
        self._build()

    def _build(self):
        root = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))
        root.add_widget(Label(text="管理面板账号", font_size=dp(20),
                              size_hint_y=None, height=dp(40)))

        # 列表
        self.list_box = BoxLayout(orientation="vertical", size_hint_y=None)
        self.list_box.bind(minimum_height=self.list_box.setter("height"))
        sv = ScrollView(size_hint=(1, 0.5))
        sv.add_widget(self.list_box)
        root.add_widget(sv)

        # 内联表单
        self.edit_box = BoxLayout(orientation="vertical", spacing=dp(8),
                                  size_hint_y=None)
        self.e_name = TextInput(hint_text="显示名", size_hint_y=None, height=dp(40))
        self.e_url = TextInput(hint_text="面板地址，如 http://1.2.3.4:2095/app/",
                               size_hint_y=None, height=dp(40))
        self.e_user = TextInput(hint_text="用户名", size_hint_y=None, height=dp(40))
        self.e_pass = TextInput(hint_text="密码", password=True,
                                size_hint_y=None, height=dp(40))
        for w in (self.e_name, self.e_url, self.e_user, self.e_pass):
            self.edit_box.add_widget(w)
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        self.btn_save = make_button("保存", self._save, size_hint_x=0.5)
        btn_cancel = make_button("取消", self._cancel_edit, size_hint_x=0.5)
        row.add_widget(self.btn_save)
        row.add_widget(btn_cancel)
        self.edit_box.add_widget(row)
        self.edit_box.add_widget(Label(text="", size_hint_y=None, height=dp(6)))
        root.add_widget(self.edit_box)

        # 底部按钮
        bottom = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        btn_add = make_button("新增账号", self._start_add, size_hint_x=0.5)
        btn_done = make_button("完成", self.dismiss, size_hint_x=0.5)
        bottom.add_widget(btn_add)
        bottom.add_widget(btn_done)
        root.add_widget(bottom)

        self.add_widget(root)
        self._editing_index = -1
        self._refresh_list()

    def _refresh_list(self):
        self.list_box.clear_widgets()
        if not self.accounts:
            self.list_box.add_widget(Label(text="（暂无已存账号）",
                                           size_hint_y=None, height=dp(36)))
        for i, a in enumerate(self.accounts):
            row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
            row.add_widget(Label(text=a.get("name") or a.get("url", ""),
                                 halign="left", valign="center",
                                 text_size=(dp(160), None),
                                 size_hint_x=0.5))
            b_edit = make_button("编辑", lambda inst, idx=i: self._start_edit(idx),
                                 size_hint_x=0.25)
            b_del = make_button("删除", lambda inst, idx=i: self._del(idx),
                                size_hint_x=0.25)
            row.add_widget(b_edit)
            row.add_widget(b_del)
            self.list_box.add_widget(row)

    def _clear_form(self):
        for w in (self.e_name, self.e_url, self.e_user, self.e_pass):
            w.text = ""

    def _start_add(self, *a):
        self._editing_index = -1
        self._clear_form()
        self.btn_save.text = "保存"

    def _start_edit(self, idx):
        self._editing_index = idx
        a = self.accounts[idx]
        self.e_name.text = a.get("name", "")
        self.e_url.text = a.get("url", "")
        self.e_user.text = a.get("user", "")
        self.e_pass.text = a.get("pass", "")
        self.btn_save.text = "更新"

    def _cancel_edit(self, *a):
        self._editing_index = -1
        self._clear_form()

    def _save(self, *a):
        name = self.e_name.text.strip()
        url = self.e_url.text.strip()
        user = self.e_user.text.strip()
        pwd = self.e_pass.text
        if not url:
            show_error("缺少地址", "请填写面板地址。")
            return
        if self._editing_index >= 0:
            self.accounts[self._editing_index] = {
                "name": name or url, "url": url, "user": user, "pass": pwd}
        else:
            self.accounts.append({
                "name": name or url, "url": url, "user": user, "pass": pwd})
        save_accounts(self.accounts, 0)
        self._editing_index = -1
        self._clear_form()
        self._refresh_list()

    def _del(self, idx):
        a = self.accounts.pop(idx)
        save_accounts(self.accounts, 0)
        self._editing_index = -1
        self._clear_form()
        self._refresh_list()

    def dismiss(self, *a):
        if self.on_close:
            self.on_close(self.accounts)
        super().dismiss(*a)


# ---------------- 登录页 ----------------

class LoginScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.accounts = []
        self.current = 0
        self._build_ui()

    def _build_ui(self):
        root = BoxLayout(orientation="vertical", padding=dp(18), spacing=dp(12))
        root.add_widget(Label(text="s-ui 面板客户端", font_size=dp(24),
                              size_hint_y=None, height=dp(52)))

        self.spinner = Spinner(text="（手动输入）", size_hint_y=None, height=dp(46))
        self.spinner.bind(text=self.on_spinner)
        root.add_widget(self.spinner)

        self.url = TextInput(hint_text="面板地址", size_hint_y=None, height=dp(46))
        self.user = TextInput(hint_text="用户名", size_hint_y=None, height=dp(46))
        self.pwd = TextInput(hint_text="密码", password=True,
                             size_hint_y=None, height=dp(46))
        root.add_widget(Field("面板地址：", self.url))
        root.add_widget(Field("用户名：", self.user))
        root.add_widget(Field("密码：", self.pwd))

        self.remember = CheckBox(active=True)
        rrow = BoxLayout(size_hint_y=None, height=dp(40))
        rrow.add_widget(self.remember)
        rrow.add_widget(Label(text="记住此账号", halign="left"))
        root.add_widget(rrow)

        btn_manage = make_button("管理账号", self.open_manager, size_hint_y=None,
                                 height=dp(46))
        root.add_widget(btn_manage)

        btn_login = make_button("登 录", self.do_login, size_hint_y=None,
                                height=dp(52))
        btn_login.background_color = (0.2, 0.6, 1.0, 1)
        root.add_widget(btn_login)

        self.add_widget(root)
        self.refresh_accounts()

    def refresh_accounts(self):
        self.accounts, self.current = load_accounts()
        names = [a.get("name") or a.get("url", "") for a in self.accounts]
        names.append("（手动输入）")
        self.spinner.values = names
        if self.accounts:
            self.current = min(self.current, len(self.accounts) - 1)
            self.spinner.text = names[self.current]
            self._fill(self.accounts[self.current])
        else:
            self.spinner.text = "（手动输入）"

    def on_spinner(self, spinner, text):
        if text == "（手动输入）":
            return
        for a in self.accounts:
            if (a.get("name") or a.get("url", "")) == text:
                self._fill(a)
                break

    def _fill(self, a):
        self.url.text = a.get("url", "")
        self.user.text = a.get("user", "")
        self.pwd.text = a.get("pass", "")

    def open_manager(self, *a):
        def on_close(accounts):
            self.refresh_accounts()
        pv = AccountManagerPopup(self.accounts, on_close)
        pv.open()

    def do_login(self, *a):
        url = self.url.text.strip()
        user = self.user.text.strip()
        pwd = self.pwd.text
        if not url or not user or not pwd:
            show_error("信息不全", "请填写面板地址、用户名和密码。")
            return
        def work():
            api = SuiClient(url)
            api.login(user, pwd)
            inbounds = api.get_inbounds()
            return api, inbounds
        run_in_thread(work, self._on_login_ok, self._on_login_err)

    def _on_login_ok(self, res):
        api, inbounds = res
        # 记住账号
        if self.remember.active:
            new_acct = {"name": (self.user.text.strip() or
                                 suicore._host_of(self.url.text.strip())),
                        "url": self.url.text.strip(),
                        "user": self.user.text.strip(),
                        "pass": self.pwd.text}
            self.accounts = upsert_account(self.accounts, new_acct)
            save_accounts(self.accounts, max(0, find_account_index(
                self.accounts, self.url.text.strip(), self.user.text.strip())))
        # 跳到主界面
        main = self.manager.get_screen("main")
        main.setup(api, inbounds, self.accounts,
                   max(0, find_account_index(self.accounts,
                                             self.url.text.strip(),
                                             self.user.text.strip())))
        self.manager.current = "main"

    def _on_login_err(self, e):
        show_error("登录失败", str(e))


# ---------------- 添加/编辑 用户弹窗 ----------------

class ClientEditPopup(ModalView):
    """添加或编辑用户。编辑时传入 client 对象。"""

    def __init__(self, api, inbounds, client=None, on_done=None, **kw):
        super().__init__(size_hint=(0.95, 0.92), **kw)
        self.api = api
        self.inbounds = inbounds or []
        self.client = client
        self.on_done = on_done
        self._ib_checks = []
        self._build()

    def _build(self):
        root = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        is_edit = self.client is not None
        root.add_widget(Label(text="编辑用户" if is_edit else "添加用户",
                              font_size=dp(20), size_hint_y=None, height=dp(38)))

        self.e_name = TextInput(hint_text="用户名（必填）", size_hint_y=None,
                                height=dp(44))
        root.add_widget(Field("用户名：", self.e_name))

        self.e_desc = TextInput(hint_text="备注（可选）", size_hint_y=None,
                                height=dp(44))
        root.add_widget(Field("备注：", self.e_desc))

        self.e_vol = TextInput(hint_text="如 100，0 表示不限制",
                               input_filter="int", size_hint_y=None, height=dp(44))
        self.e_days = TextInput(hint_text="如 30，0 表示不限制",
                                input_filter="int", size_hint_y=None, height=dp(44))
        root.add_widget(Field("流量(GiB)：", self.e_vol))
        root.add_widget(Field("有效期(天)：", self.e_days))

        # 入站多选
        root.add_widget(Label(text="入站（可多选）：", size_hint_y=None,
                              height=dp(28), halign="left"))
        sv = ScrollView(size_hint=(1, 0.32))
        ib_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(4))
        ib_box.bind(minimum_height=ib_box.setter("height"))
        for ib in self.inbounds:
            iid = ib.get("id")
            remark = ib.get("remark") or ""
            proto = (ib.get("type") or ib.get("protocol") or "")
            cb = CheckBox(size_hint_x=None, width=dp(40))
            cb.ib_id = iid
            row = BoxLayout(size_hint_y=None, height=dp(38))
            row.add_widget(cb)
            row.add_widget(Label(text="%s  #%s %s" % (proto, iid, remark),
                                 halign="left"))
            ib_box.add_widget(row)
            self._ib_checks.append(cb)
        sv.add_widget(ib_box)
        root.add_widget(sv)

        # 填充编辑值
        if is_edit:
            c = self.client
            self.e_name.text = c.get("username") or c.get("name") or ""
            self.e_desc.text = c.get("description") or c.get("desc") or ""
            vb = c.get("volume") or c.get("totalGB") or 0
            ed = c.get("expiry") or c.get("expire") or 0
            self.e_vol.text = str(int(vb / (1024 ** 3))) if vb else "0"
            self.e_days.text = "0"
            if ed:
                import time as _t
                self.e_days.text = str(max(0, int((ed - _t.time()) / 86400)))
            sel = set(c.get("inbounds") or c.get("inboundIds") or [])
            for cb in self._ib_checks:
                cb.active = cb.ib_id in sel

        # 按钮
        bottom = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        btn_ok = make_button("保存", self._save)
        btn_cancel = make_button("取消", self.dismiss)
        bottom.add_widget(btn_ok)
        bottom.add_widget(btn_cancel)
        root.add_widget(bottom)
        self.add_widget(root)

    def _selected_inbounds(self):
        return [cb.ib_id for cb in self._ib_checks if cb.active]

    def _save(self, *a):
        name = self.e_name.text.strip()
        if not name:
            show_error("缺少用户名", "请填写用户名。")
            return
        try:
            vol_gib = int(self.e_vol.text or "0")
        except ValueError:
            vol_gib = 0
        try:
            days = int(self.e_days.text or "0")
        except ValueError:
            days = 0
        inbound_ids = self._selected_inbounds()
        if not inbound_ids:
            show_error("未选入站", "请至少选择一个入站。")
            return
        desc = self.e_desc.text.strip()
        volume = int(vol_gib * 1024 ** 3) if vol_gib > 0 else 0
        expiry = int(time.time()) + days * 86400 if days > 0 else 0

        def work():
            if self.client is not None:
                # 编辑：在取回的完整对象上改字段后整体回传
                c = dict(self.client)
                c["name"] = name
                c["desc"] = desc
                c["volume"] = volume
                c["expiry"] = expiry
                c["inbounds"] = sorted(inbound_ids)
                cfg = dict(c.get("config") or {})
                cfg["username"] = name
                c["config"] = cfg
                self.api.update_client(c)
            else:
                self.api.add_client(name=name, inbound_ids=inbound_ids,
                                    volume_bytes=volume, expiry_ts=expiry,
                                    desc=desc)
            return True

        run_in_thread(work, self._on_ok, self._on_err)

    def _on_ok(self, *_):
        if self.on_done:
            self.on_done()
        self.dismiss()

    def _on_err(self, e):
        show_error("保存失败", str(e))


# ---------------- 主界面：用户列表 ----------------

class MainScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.api = None
        self.inbounds = []
        self.accounts = []
        self.current = 0
        self.clients = []
        self.rows = []
        self._build_ui()

    def _build_ui(self):
        root = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))

        # 顶部：面板切换 + 操作
        top = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        self.panel_spinner = Spinner(text="面板", size_hint_x=0.45)
        self.panel_spinner.bind(text=self.on_panel)
        top.add_widget(self.panel_spinner)
        top.add_widget(make_button("刷新", self.load_clients, size_hint_x=0.27))
        top.add_widget(make_button("添加", self.on_add, size_hint_x=0.28))
        root.add_widget(top)

        # 批量操作条
        bar = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
        bar.add_widget(make_button("全选", self.on_select_all, size_hint_x=0.25))
        bar.add_widget(make_button("取消", self.on_clear, size_hint_x=0.25))
        bar.add_widget(make_button("删除", self.on_delete, size_hint_x=0.25))
        bar.add_widget(make_button("编辑", self.on_edit, size_hint_x=0.25))
        root.add_widget(bar)

        self.status = Label(text="", size_hint_y=None, height=dp(26),
                            color=(0.5, 0.5, 0.5, 1), halign="left")
        root.add_widget(self.status)

        # 列表
        sv = ScrollView()
        self.list_box = BoxLayout(orientation="vertical", size_hint_y=None,
                                  spacing=dp(4))
        self.list_box.bind(minimum_height=self.list_box.setter("height"))
        sv.add_widget(self.list_box)
        root.add_widget(sv)

        # 底部：退出
        root.add_widget(make_button("退出登录", self.on_logout, size_hint_y=None,
                                    height=dp(44)))
        self.add_widget(root)

    def setup(self, api, inbounds, accounts, current):
        self.api = api
        self.inbounds = inbounds or []
        self.accounts = accounts or []
        self.current = current
        names = [(a.get("name") or a.get("url", "")) for a in self.accounts] or ["面板"]
        self.panel_spinner.values = names
        self.panel_spinner.text = names[current] if names else "面板"
        self.load_clients()

    def load_clients(self, *a):
        if not self.api:
            return
        self.status.text = "加载中…"

        def work():
            return self.api.get_clients()

        run_in_thread(work, self._on_clients, self._on_clients_err)

    def _on_clients(self, clients):
        self.clients = clients or []
        self._render()
        self.status.text = "共 %d 个用户" % len(self.clients)

    def _on_clients_err(self, e):
        self.status.text = "加载失败"
        show_error("获取用户失败", str(e))

    def _render(self):
        self.list_box.clear_widgets()
        self.rows = []
        for c in self.clients:
            cb = CheckBox(size_hint_x=None, width=dp(40))
            name = c.get("username") or c.get("name") or "(未命名)"
            desc = c.get("description") or c.get("desc") or ""
            sub = desc
            row = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(4))
            row.add_widget(cb)
            row.add_widget(Label(text=name + ("\n" + sub if sub else ""),
                                 halign="left", valign="center",
                                 text_size=(dp(260), None)))
            self.list_box.add_widget(row)
            self.rows.append((cb, c))

    def selected_clients(self):
        return [c for cb, c in self.rows if cb.active]

    def on_select_all(self, *a):
        for cb, _ in self.rows:
            cb.active = True

    def on_clear(self, *a):
        for cb, _ in self.rows:
            cb.active = False

    def on_delete(self, *a):
        sel = self.selected_clients()
        if not sel:
            show_info("提示", "请先勾选要删除的用户。")
            return

        def work():
            for c in sel:
                self.api.del_client(c)
            return len(sel)

        run_in_thread(work, lambda n: (self.load_clients(),
                                       show_info("已删除", "成功删除 %d 个用户。" % n)),
                      lambda e: show_error("删除失败", str(e)))

    def on_edit(self, *a):
        sel = self.selected_clients()
        if len(sel) != 1:
            show_info("提示", "请只勾选一个用户进行编辑。")
            return
        pv = ClientEditPopup(self.api, self.inbounds, client=sel[0],
                             on_done=self.load_clients)
        pv.open()

    def on_add(self, *a):
        pv = ClientEditPopup(self.api, self.inbounds, client=None,
                             on_done=self.load_clients)
        pv.open()

    def on_panel(self, spinner, text):
        if not self.accounts:
            return
        for i, a in enumerate(self.accounts):
            if (a.get("name") or a.get("url", "")) == text:
                if i == self.current:
                    return
                self._switch_panel(i)
                break

    def _switch_panel(self, idx):
        self.status.text = "切换面板中…"
        a = self.accounts[idx]
        url = a.get("url", "")
        user = a.get("user", "")
        pwd = a.get("pass", "")

        def work():
            if not pwd:
                # 需要密码，回调到主线程询问
                raise SuiApiError("该面板未保存密码，请到登录页重新登录。")
            api = SuiClient(url)
            api.login(user, pwd)
            inbounds = api.get_inbounds()
            return api, inbounds

        def ok(res):
            api, inbounds = res
            self.current = idx
            self.setup(api, inbounds, self.accounts, idx)

        run_in_thread(work, ok, lambda e: show_error("切换失败", str(e)))

    def on_logout(self, *a):
        self.api = None
        self.clients = []
        self.list_box.clear_widgets()
        login = self.manager.get_screen("login")
        login.refresh_accounts()
        self.manager.current = "login"


# ---------------- App ----------------

class SuiApp(App):
    def build(self):
        self.title = "s-ui 客户端"
        # Android 上把配置写到应用私有目录，避免权限问题
        try:
            cfg = os.path.join(self.user_data_dir, "sui_client.json")
            suicore.set_config_file(cfg)
        except Exception:
            pass
        sm = ScreenManager()
        sm.add_widget(LoginScreen(name="login"))
        sm.add_widget(MainScreen(name="main"))
        return sm


if __name__ == "__main__":
    SuiApp().run()
