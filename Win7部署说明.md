# Win7 64 位离线部署说明

本说明针对你师兄交付的这份项目，以及 64 位、不能联网的 Win7 电脑。

## CF37v2 是什么

`CF37v2` 是 Python 3.7.16 的 64 位 Conda 运行环境。程序的后端要靠它执行，它不是另一个需要打开的软件，也不用把其中的 DLL 逐个复制到系统目录。

师兄提供的原始 `CF37v2` 缺少 OCR、OpenCV、NumPy 等库，单纯复制过去还不能运行。现在项目内的 `CF37v2/` 是单独复制并补齐依赖的版本；项目外、师兄给的原件没有改动。启动脚本优先使用项目内部这份环境，不用安装 Anaconda，也不用激活 Conda。

运行环境不要求放在项目根目录。`start_win7.bat` 会依次查找：根目录 `win7-python.txt` 里写的一行 python.exe 路径、项目内 `CF37v2\python.exe`、项目旁 `..\CF37v2\python.exe`、项目内 `venv\.venv`、常见 Anaconda/Miniconda 的 `envs\CF37v2` 路径。换电脑时复制 `win7-python.example.txt` 为 `win7-python.txt`，把里面一行改成目标机实际路径即可：

```text
E:\Anaconda\envs\CF37v2\python.exe
```

`start_win7.bat` 使用查找到的 Python 3.7 x64 环境和已经构建好的 `frontend/dist/`。目标电脑另外安装的 Python 3.7、Node 12 不参与这条启动流程（PATH 里的 Python 不会被自动采用），不需要为此次部署升级它们。

## 带什么到 Win7

带走 `dist/OCR-Benti-Win7-x64-offline.zip`，在 Win7 上完整解压到一个你有写入权限的目录，例如 `D:\OCR-Benti-Win7`。不要直接在压缩包里双击脚本。

解压后应能看到：

```text
OCR-Benti-Win7/
  start_win7.bat
  Win7部署说明.md
  启动.txt                 一键及手动启动说明
  win7-python.example.txt  指定外部 Python 环境的示例
  CF37v2/                  已补齐的 Python 运行环境及 OCR 模型
  frontend/dist/           已构建的网页文件
  backend/app/             已适配 Python 3.7 的后端
  backend/projects/        随项目交付的项目数据
  backend/uploads/         随项目交付的上传文件
  backend/users.xlsx       登录用户表
  backend/requirements-win7.txt
  scripts/                 启动、检查、离线修复及验证脚本
  wheelhouse-win7/         依赖安装包及 SHA256 校验清单
  prerequisites/           微软 Visual C++ x64 离线运行库安装程序
  test.png                 OCR 验证图片
```

不要使用旧的 `dist/OCR-Benti.exe` 作为当前最新版：它来自今年 5 月的旧构建，和现在的代码、网页不一致。原来的 `start.bat` 是开发启动脚本，会调用 npm/Vite，也不适用于这次离线部署。

## Win7 本机要满足的条件

1. **64 位 Windows 7 SP1**。在“计算机 → 右键 → 属性”查看系统类型和 Service Pack。当前交付的环境不能用于 32 位系统。
2. **可以运行项目网页的浏览器**。不同电脑可以使用不同浏览器，但不能保证任意旧版本都可用。这次网页以 Chrome 109 为构建目标；请提前准备合适、来源可信的离线安装程序，或确认现有浏览器的内核满足要求。不要用系统自带的 IE；有“兼容模式 / 极速模式”的浏览器应使用极速模式。新版页面会检测 ES module、Promise、Proxy、fetch，缺少这些功能时显示提示；检测通过也不代表其他网页功能一定全部兼容，仍需实际验收。浏览器安装程序不在本项目部署包内。
3. **需要可用的 Visual C++ x64 运行库，但不必重复安装**。本包的 `prerequisites/VC_redist.x64.exe` 是从微软官方下载的 VS2019 系列安装程序；ONNX Runtime 需要其中的 `VCRUNTIME140_1.dll` 等依赖。如果系统或环境中已有可用的运行库，可以不再执行安装程序。现场截图中原生依赖已经全部导入、OCR 初始化完成并显示 `Ready`，不能把这次登录错误直接归因于没有执行运行库安装程序。遇到缺少 `VCRUNTIME`/`MSVCP` 等 DLL 或相关加载错误时，再安装包内 x64 运行库，按提示重启；如果提示已有更高版本，不必卸载现有版本。
4. **完整的 Windows 媒体组件**。普通 Win7 通常自带；N/KN 或精简版如果缺 `MF.dll`、`MFPlat.dll`、`MFReadWrite.dll`，需先安装适用于本机版本的微软 Media Feature Pack。该组件未包含在本包中。
5. 项目目录可写。运行时会保存项目和上传文件，不建议放到需要管理员写权限的 `Program Files`。

Google 的官方说明确认 [Chrome 109 是支持 Win7 的最后一个 Chrome 版本](https://support.google.com/chrome/a/answer/7100626?hl=en)；[Vue 3 不支持 IE11](https://vuejs.org/about/faq)。新版 Chrome 安装程序不能代替适用于 Win7 的版本。

## 怎么启动

如果 Python 环境没有放在项目内，先在根目录建 `win7-python.txt` 写入其 python.exe 路径（见上一节）；其余步骤相同。需要完全手动启动（不用 bat）时，见根目录的 `启动.txt`。

1. 先在项目目录的命令提示符执行：

   ```bat
   start_win7.bat --check
   ```

   这个检查会读取依赖、网页资源、用户表，并初始化 OCR 模型；不改项目数据。看到最后的 `[OK] Environment checks passed.` 才表示检查通过。

2. 双击 `start_win7.bat`。首次加载 OCR 可能需要稍等，等窗口显示 `[OK] Ready: http://127.0.0.1:端口/`。
3. 浏览器通常会自动打开。若默认浏览器是 IE，请把窗口里的地址复制到符合上文要求的浏览器，例如适用于 Win7 的 Chrome 109。端口从 8000 开始，有占用就自动换一个，以窗口实际显示为准。
4. 用师兄提供的账号登录。账号数据保存在 `backend/users.xlsx`；不要丢掉这个文件。
5. 保持命令窗口打开。结束使用时在窗口按 `Ctrl+C`，再关闭窗口。

目标电脑不需要 Node.js、npm、Docker，也不需要联网下载 OCR 模型。启动器只监听本机 `127.0.0.1`，网页和接口使用同一个端口。不要通过直接双击 `frontend/dist/index.html` 的方式打开系统。

## 登录提示异常时怎么排查

1. 保持启动 BAT 的命令窗口打开，确认有 `Application startup complete` 和 `[OK] Ready: http://127.0.0.1:端口/`。使用窗口中的实际地址，端口不一定始终是 8000。
2. 在同一浏览器打开该地址下的 `/api/projects`，例如 `http://127.0.0.1:8000/api/projects`。如果能显示 JSON，说明项目 API 可以响应，不能再单凭旧页面上的“网络错误，请确认后端服务已启动”认定后端没有启动。旧提示将连接错误、响应解析错误等合并成了同一句，不能定位最终原因。
3. 更新后的登录页会区分连接失败、HTTP 状态异常、响应不是有效 JSON、返回格式不匹配和浏览器功能缺失。记录实际提示，并观察命令窗口是否出现 `POST /api/auth/login` 及其 HTTP 状态；如有报错，一并保留。普通账号或密码不对会显示“用户名或密码错误”。
4. 打开实际服务地址下的 `/connection-check.html`，点击“运行检测”，再点击“复制报告”，或全选文本报告复制。每台电脑可以分别运行，以便比较浏览器和接口结果。该页面不需要账号密码，不会发送真实账号或创建登录会话；它检查项目接口，并向登录接口发送空对象 `{}`，预期的 HTTP 422 表示参数校验接口能响应，**不表示账号验证或登录已经成功**。
5. 结合具体错误、检测报告和命令窗口日志继续排查。即使项目接口能返回 JSON，登录 POST 请求、浏览器功能或响应解析仍可能单独存在问题；目前没有证据证明所有现场登录故障具有同一个原因。

## 已部署电脑如何应用登录更新补丁

已经完整复制过离线部署包的电脑，可以使用小补丁 `dist/OCR-Benti-Win7-login-update.zip`，不必重新复制整套运行环境。

1. 在旧程序的命令窗口按 `Ctrl+C` 停止服务，再关闭旧窗口。
2. 解压补丁，将其中的 `frontend/dist/` 和 `scripts/win7_launcher.py` 复制到已部署项目的相同位置并覆盖；如附有更新后的部署说明，也一并保留。确认没有多套一层目录。
3. 重新双击原项目中的 `start_win7.bat`，使用新窗口显示的 `Ready` 地址打开网页，按 `Ctrl+F5` 强制刷新，再尝试登录或运行连接检测。

这个补丁更新网页提示、连接检测和启动器日志，不需要重拷 `CF37v2`，也不覆盖 `backend/users.xlsx`、`backend/projects/` 或 `backend/uploads/`。它用于进一步区分错误和收集现场证据，不能据此承诺所有电脑的登录问题已经修复。

## 缺包或拷贝损坏时怎么处理

已经补齐的环境通常不需要安装这一步。如检查提示缺 Python 包，在项目目录的命令提示符执行：

```bat
CF37v2\python.exe scripts\prepare_win7.py --install-offline
```

该命令先验证离线包 SHA256，再只从 `wheelhouse-win7` 安装，随后检查依赖关系和 OCR 初始化；全程不访问网络。若提示文件损坏，重新复制完整部署包，不要执行原来的 `pip install -r backend/requirements.txt`，原清单面向较新 Python。

如果提示 `DLL load failed`、找不到入口点、缺少 `VCRUNTIME`/`MSVCP`，仅补 Python 包不一定能解决。启动器已经处理了 Conda 的 DLL 搜索路径；先确认有可用的 Visual C++ x64 运行库，确实缺少时安装包内版本，再根据具体报错检查目标机的系统补丁、媒体组件。不要把任意来源的 DLL 复制到 `System32`。微软提供[运行库下载与系统要求说明](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist?view=msvc-170)；最新通用版本已经不支持 Win7，因此本次附带 VS2019 系列历史版本。系统补丁与 Media Feature Pack 因目标机版本而异，未放进本包。

## 本次改了什么

- 后端的新式类型注解改为 Python 3.7 可用的写法；`Literal` 使用 `typing_extensions`。
- 上传失败后的清理改为 Python 3.7 支持的文件删除方式。
- 新增 `backend/requirements-win7.txt`，单独固定适合 Python 3.7 的依赖，保留原开发清单。
- 新增 Win7 启动器，自动定位内部环境、设置 DLL 路径、检查依赖和网页资源、选择空闲端口。
- 前端按 Chrome 109 重新构建，移除 Google Fonts 网络字体请求。
- OCR 模型随 Python 包保存在本地，另附离线依赖包及校验清单。
- 登录更新细分错误提示，增加浏览器基础功能提示和无需账号的 `/connection-check.html` 检测页；启动器日志关闭 ANSI 颜色转义，便于在 Win7 命令窗口阅读。

原始代码备份在工作目录 `.win7-original/`，不放进运行部署包。

## 验证范围与需要现场验收的内容

2026-10-27 已在当前电脑的 Python 3.7.16 x64 环境中验证：39 个包完全从离线目录安装成功、依赖关系检查通过、环境及 OCR 模型初始化通过、52 项原有单元测试通过；在独立项目副本上完成网页/静态资源、OpenAPI、登录、实际图片 OCR、项目增改删、JSONL 导入保存及失败上传清理验证，原业务数据 SHA256 保持不变。

同日，本次登录更新已在当前电脑的独立项目副本中通过新网页静态资源、连接检测页、登录空参数返回 HTTP 422、用户表账号登录、实际 OCR、JSONL 导入和项目操作检查；原业务数据哈希保持不变。这些是本机检查结果，不能据此认定现场 Win7 登录问题已经解决。

上述完整验证使用当前电脑上的 Python 3.7.16 x64 环境。后续收到的 Win7 SP1 64 位现场截图表明：该电脑使用包内 Python 3.7.16，原生依赖导入成功，应用完成启动并显示 `Ready`；用户还确认 `/api/projects` 能返回 JSON。**这些证据尚不等于现场完整验收通过**：该电脑仍有登录故障，其他电脑的浏览器也不同，更新后的登录和实际 OCR 操作仍需现场确认。

截图中的 `Unsupported Windows version (7)` 是 ONNX Runtime 的系统支持警告；它没有阻止这次截图所示的启动，但不能据此认为 Win7 得到官方支持。[ONNX Runtime 1.14.1 官方源码](https://raw.githubusercontent.com/microsoft/onnxruntime/v1.14.1/onnxruntime/python/onnxruntime_validation.py)声明支持 Windows 10 及以上；Win7 不在该版本的官方支持范围内。系统补丁、CPU、第三方 DLL 和实际识别功能仍需逐台验收，不能承诺每台 Win7 都可用。

现场至少确认：环境检查通过、能够登录、现有项目能打开、导入一张图片能识别、导入 Excel/JSONL 能保存，再退出重开确认数据保留。

真实达梦数据库连接另需匹配 Python 3.7/Win7 x64 的 `dmPython` 驱动及相应数据库客户端，这次基础离线包未包含、也没有验证外部数据库。文件导入和本地 OCR 不依赖它。

## 后续维护

在能联网的开发电脑上重新收集离线依赖：

```bat
CF37v2\python.exe scripts\prepare_win7.py --download-wheels
```

如果开发电脑的代理不可用，可仅为这次下载指定直连和镜像：

```bat
CF37v2\python.exe scripts\prepare_win7.py --download-wheels --direct --index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

代码、前端和环境准备完成后，用 `CF37v2\python.exe scripts\package_win7.py` 重新生成部署包。已有同名包时，先保留旧包，或明确使用 `--force` 更新。
