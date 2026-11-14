# CellGame 发布说明

项目当前构建为一个 Python 分发包，包含服务器、客户端、内置规则与网页界面。`cellgame` 是暂定的 PyPI 名称，首次上传前请在 PyPI 核实该名称是否可用、是否已有其他项目，以及你是否有发布权限。版本当前为 `0.2.0`。没有获得用户确定的开源许可前，不要自行声明许可证。

## 构建与检查

在项目目录中：

```bash
python -m pip install --upgrade build twine
python -m build --outdir dist
python -m twine check dist/cellgame-0.2.0-py3-none-any.whl dist/cellgame-0.2.0.tar.gz
```

确认目录中仅有本次版本的文件，不要把旧版本的构建产物一并上传。构建包括 `.whl` 和 `.tar.gz`。可在已有 NumPy、websockets 的环境运行 `python tests/packaging_test.py dist/cellgame-0.2.0-py3-none-any.whl`；测试会在临时环境中安装并启动真实服务端与客户端。

## 安装本地构建

```bash
python -m pip install dist/cellgame-0.2.0-py3-none-any.whl
cellgame-server --host 127.0.0.1
# 另开一个终端
cellgame-client
```

如果系统提示找不到 `cellgame-server`，使用 `python -m cellgame server --host 127.0.0.1` 和 `python -m cellgame client`。切勿在终端之间切换到不同的 Python 环境。

## 上传

1. 在 TestPyPI / PyPI 分别准备账户和令牌；两者的账户和令牌相互独立。初次可以先用 TestPyPI 验证。请在自己的终端使用交互式密码输入或凭据管理器，不要把令牌写进代码、命令历史或聊天记录。
2. 在项目目录运行 `python -m twine upload --repository testpypi dist/cellgame-0.2.0-py3-none-any.whl dist/cellgame-0.2.0.tar.gz`，用户名输入 `__token__`，密码提示时输入 TestPyPI 令牌。
3. 在新的 Python 环境验证 TestPyPI 中的包。为避免从测试源解析正式依赖，可先从正式 PyPI 安装 `numpy` 和 `websockets`，再运行 `python -m pip install --index-url https://test.pypi.org/simple/ --no-deps cellgame==0.2.0`。
4. 验证通过、名称和发布内容确定后，运行 `python -m twine upload dist/cellgame-0.2.0-py3-none-any.whl dist/cellgame-0.2.0.tar.gz` 并输入 PyPI 令牌。正式 PyPI 发布的版本号不可重复上传；修改后应更新版本并重新构建。

如果将项目托管到支持的代码平台，也可以按 PyPI 官方说明配置 Trusted Publishing，以免在自动化环境中保存长期令牌。
