[app]

# (str) 应用标题（手机上显示的名字）
title = s-ui 客户端

# (str) 包名：域名倒写 + 应用名，必须唯一
package.name = suiclient
package.domain = com.workbuddy

# (str) 入口源码目录（在本目录下执行 buildozer）
source.dir = .

# (list) 需要打包进 APK 的文件类型
source.include_exts = py,png,jpg,kv,json

# (str) 主程序入口
source.main = main.py

# (list) 应用依赖。kivy 负责界面；requests/urllib3 负责 HTTP。
#        密码加密改用纯 Python 标准库（hashlib+hmac），不再依赖 cryptography
#        （新版 cryptography 用 Rust 实现，无法在 Android 交叉编译）。
#        注意：不要写死 python3/kivy 版本 —— 当前 p4a 的 hostpython3 默认是 3.14.2，
#        若只写 python3==3.11.9 而不写 hostpython3==3.11.9 会报版本不匹配；
#        直接不指定版本，让 p4a 用默认兼容组合最稳。
requirements = python3, kivy, requests, urllib3

# (str) 应用版本
version = 1.0

# (list) 需要的 Android 权限（仅联网即可，配置写在 app 私有目录无需存储权限）
android.permissions = INTERNET, ACCESS_NETWORK_STATE

# (int) Android API / NDK / SDK 版本（buildozer 会自动下载对应版本）
android.api = 34
android.minapi = 24
android.ndk = 25b

# (bool) 是否打包为 AAB（Google Play 需要）；直接装手机选 False 出 APK
android.archs = arm64-v8a, armeabi-v7a
android.release = False

# (str) 屏幕方向：手机竖屏
orientation = portrait

# (list) 额外要拷贝到应用目录的文件（无则留空）
# android.add_src = 

# (str) 应用图标。已提供 1024x1024 的 icon.png，取消下行注释即可启用。
android.icon.filename = icon.png

# (str) 启动图。已提供 1024x1024 的 presplash.png，取消下行注释即可启用。
android.presplash.filename = presplash.png

[buildozer]

# (int) 日志等级
log_level = 2

# (str) 临时构建目录（默认 .buildozer）
build_dir = .buildozer

# (bool) 是否自动接受 SDK  license
android.accept_sdk_license = True

# 固定 python-for-android 到稳定 release v2024.01.21（重要）：
# master 分支自 2025-04 起把 pyjnius/kivy 从「源码交叉编译(CythonRecipe)」改成
# 「下载 PyPI 的 android wheel(PyProjectRecipe)」，但 pyjnius 1.7.0 尚未发布 android wheel，
# 且默认 hostpython3 升到 3.14.2 太新，导致 pip 找不到匹配的 wheel（--platform=android_24_*）。
# v2024.01.21 用源码交叉编译：pyjnius 1.6.1 / kivy 2.3.0 / python3 与 hostpython3 均为 3.11.5，
# 稳定可用。该版本推荐的 NDK 正是 25b（与上方 android.ndk 一致）。
p4a.branch = v2024.01.21
