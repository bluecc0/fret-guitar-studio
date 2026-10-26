# Fret 吉他练习室

面向 Mac 的浏览器应用与本地识谱服务。PDF / 图片 → Audiveris → MusicXML → 人工校对 → 音符与节奏时间轴。VLM 预留 OpenAI Chat Completions 兼容接口，默认不配置、不调用。

## 在 Mac 启动

1. 安装 Python 3.11 或更新版本。
2. 从 [Audiveris 5.11.0 官方 Releases](https://github.com/Audiveris/audiveris/releases/tag/5.11.0) 下载适合芯片的 macOS DMG（Apple Silicon 选 arm64，Intel 选 x86_64），安装到 Applications。遵循官方安装说明；软件及其许可证由上游提供。本项目不捆绑 Audiveris。
3. 将 `.env.example` 复制为 `.env.local`，设置 `AUDIVERIS_BIN` 为实际启动文件路径。默认建议 `/Applications/Audiveris.app/Contents/MacOS/Audiveris`，安装位置不同请调整。先运行该文件的 `-help` 检查启动与命令行参数。
4. 在 Terminal 进入本项目目录，运行：

```sh
bash scripts/start-mac.command
```

启动脚本建立 Python 虚拟环境并安装依赖。也可手动启动：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn backend.server:app --host 127.0.0.1 --port 8765
```

5. 打开 **http://127.0.0.1:8765**。从“导入乐谱”上传 PDF / PNG / JPG / WebP，选择 Audiveris。首次运行 Audiveris 可能需要按官方说明完成 OCR 语言数据安装。

这仍是浏览器应用与本地伴随服务，不是签名、公证后的原生 macOS 安装包。Mac 安装流程未在真实 Mac 上验证；Java 识谱流程已在 Linux 上用官方 5.11.0 运行包验证。

## VLM 占位接口

服务端 `.env.local`：

```dotenv
VLM_BASE_URL=https://api.openai.com/v1
VLM_MODEL=
VLM_API_KEY=
```

后续填写支持图像输入的模型名与 Key，重启服务即可。Base URL 应包含协议的版本前缀，程序在末尾追加 `/chat/completions`。兼容的服务需支持 `messages`、图像 data URL 与 `response_format: {type: "json_object"}`。不会自动创建 Key，不在浏览器存储 Key，不在未配置时调用接口，不会自动把 Audiveris 输入发送给 VLM。用户必须主动选择 VLM；启用后会把所选谱面图片发送给配置的服务商。

PDF 输入在 VLM 模式下先在本机转成 PNG，需另装 `pdftoppm`：

```sh
brew install poppler
```

VLM 输出契约是 JSON 对象 `{ "musicxml": "<score-partwise ...>", "warnings": [...] }`，仍须经过同一个 MusicXML 解析器与人工校对，不直接执行模型生成的内容。当前没有真实 VLM 调用或准确率验证，只验证兼容协议与缺少配置时的行为。

## 校对与练习

- 支持标准 `score-partwise` MusicXML，以及含 `META-INF/container.xml` 的压缩 MXL。可绕过模型直接导入。
- 保留 divisions 定义的精确时值，包括附点与三连音；保留休止、同起点音组、多声部、TAB 弦号品位、和弦标记、弱起、拍号与速度变化；延音线连接的相邻音符合并为一次起音。
- 所有时间以四分音符为 1 拍记录，用谱中速度标记分段计算秒数。6/8 与附点节拍器标记转换成等价四分音符 BPM。
- 未识别到起始 BPM 时必须填写；缺少拍号也必须补充。不会拿默认速度冒充识别结果。
- 导入后选择练习声部，可对照原始 PDF / 图片，修改起点、时值和 MIDI 音高并试听。保存前必须确认校对。事件修改不自动重排后续音符。
- “原谱练习”按识别时间轴滚动，显示小节线、音符时值与 TAB 标记。引导音按原谱起音与音高播放。游戏只评估键盘起音时机，不评价真实吉他弹奏音高与持续长度。
- 当前反复、房子、D.C./D.S. 跳转尚不自动展开；有检测到时展示警告，按谱面书写顺序练习。装饰音、移调、swing 等需要人工核对。Audiveris 不保证支持吉他六线谱，VLM 也尚未配置；不能承诺任意吉他谱自动识别准确。
- 现有精选曲目仍为和弦循环示例，不会伪装成自动识谱结果。“仅保存原谱”保留原有手动和弦流程。

## 本地数据与网络

原始乐谱保存在浏览器 IndexedDB；校对结果和练习记录在 localStorage。后端临时输入、Audiveris 导出文件在任务结束后删除。识谱任务结果只保留进程内存，完成任务一小时后可回收；重启会丢失未保存任务。

后端单进程串行识谱，最多排队 3 份任务；单文件最多 20 MB，PDF 最多 12 页；超时默认 300 秒，可设置 `AUDIVERIS_TIMEOUT`。服务器默认仅监听 127.0.0.1。它是本机伴随服务，不包含多用户认证；不要直接用 `0.0.0.0` 暴露到公网。远程部署需要独立认证网关、HTTPS 和任务隔离。

现有 Sites 网址托管静态界面，不能运行 Audiveris 的 Java 进程。在线页面可在“偏好设置 → 识谱服务设置”配置服务地址，但访问 localhost 可能受浏览器本地网络权限限制。推荐直接从本地服务地址使用完整功能。

## API

- `GET /api/health`：Audiveris / VLM 配置状态，不返回密钥。
- `POST /api/recognitions`：multipart 字段 `file`、`engine`（`audiveris` 或 `vlm`），返回 202 与任务 ID。
- `GET /api/recognitions/{id}`：轮询 queued / running / completed / failed；完成时返回结构化 score。

## 验证

```sh
python -m pip install httpx
python -m unittest discover -s tests -v
node tests/timeline.cjs
```

自动化覆盖附点、三连音、休止、弱起、和弦同时起音、多声部、延音线、速度变化、MXL、缺失 BPM、XML 实体拒绝、Audiveris 命令与临时文件清理、未配置 VLM 和 OpenAI 兼容请求格式。VLM 协议测试使用本地 mock，无真实付费调用。

实际 Audiveris 验证使用上游公开示例 `data/examples/chula.png`，识别出 19 小节、158 个音符/休止事件。这验证执行链路，不等于对真实吉他谱识谱准确率的评测。
