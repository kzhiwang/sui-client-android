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

# (list) 应用依赖。kivy 负责界面；requests/urllib3 负责 HTTP；
#        cryptography 负责密码加密（与桌面版相同的 Fernet 方案）。
requirements = python3==3.11.9, kivy==2.3.1, requests, urllib3, cryptography

# (str) 应用版本
version = 1.0

# (list) 需要的 Android 权限（仅联网即可，配置写在 app 私有目录无需存储权限）
android.permissions = INTERNET, ACCESS_NETWORK_STATE

# (int) Android API / NDK / SDK 版本（buildozer 会自动下载对应版本）
android.api = 34
android.minapi = 24
android.ndk = 25b
android.sdk = 34

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
