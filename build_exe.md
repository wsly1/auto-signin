# 打包 exe 说明

这一步暂时不用打包，后续需要时可以用 PyInstaller。

## 安装依赖

```powershell
python -m pip install pyinstaller
```

如果系统没有 `python` 命令，可以用 Codex 当前自带的 Python 路径替换：

```powershell
C:\Users\wsly\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pip install pyinstaller
```

## 打包命令

```powershell
python -m PyInstaller --noconsole --onefile --name auto-signin gui_app.py
```

生成的程序在 `dist\auto-signin.exe`。

## 配置位置

exe 运行后会优先读取 exe 同目录下的 `accounts.json`。如果没有这个文件，界面会先创建一份空配置，添加账号后点保存即可。

真实 token、cred、device_code 不要打包进 exe，也不要提交到代码仓库。
