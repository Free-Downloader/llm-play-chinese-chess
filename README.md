# LLM Play Chinese Chess · 大语言模型中国象棋对弈

**让两个大语言模型下一盘中国象棋。** 程序把当前局面（FEN）和全部合法着法发给轮到走棋的一方，
模型回一个着法（或认输），程序校验合法性后落在棋盘上，再轮到另一方，直到分出胜负。

> Two LLMs play Chinese Chess (Xiangqi) against each other. The program prompts the side to
> move with the current FEN and its complete legal-move list, validates the reply, plays it on
> a PySide6 board, and hands the turn over. Any OpenAI-compatible `/chat/completions`
> endpoint can take a seat.

- 完整的中国象棋规则引擎：FEN 读写、合法着法生成、将死 / 困毙 / 三次重复等判定
- 三窗口界面：棋盘 + 红/黑双方各自独立的 API 通信日志
- 发给模型的原话、解析结果、每手思考耗时全部落盘，便于事后复盘
- 端点、模型、思考档位全部写在配置文件里，换厂商不用改代码

## 快速开始

需要 **Python 3.10 或以上**（代码用到 `dict[...]` / `tuple[int, int] | None` 这类新语法，
3.9 会在导入阶段直接报错；本项目在 3.12 / 3.13 上开发与验证），
Windows / macOS / Linux 均可，界面基于 PySide6。

```bash
git clone https://github.com/Free-Downloader/llm-play-chinese-chess.git
cd llm-play-chinese-chess

python -m venv .venv

# Windows
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py

# macOS / Linux
.venv/bin/pip install -r requirements.txt
.venv/bin/python main.py
```

换用其他配置文件：`python main.py --config path/to/config.yaml`

- **填进配置文件**：编辑 `config/config.yaml`

### 启动后

1. 在「对局控制」里给**红方**、**黑方**各选一个选手档案；
2. 点**「测试双方 API 连接」**，确认两个端点都通；
3. 点**「开始对弈」**。

## 配置

默认读取 `config/config.yaml`，每一项都带注释。分三部分。

### `players` — 选手档案

红方、黑方的下拉框都从这张列表里取。

| 字段 | 说明 |
|---|---|
| `name` | 选手名，显示在下拉框里；也是环境变量名的来源（见「密钥」） |
| `base_url` | OpenAI 兼容端点，程序请求 `{base_url}/chat/completions`；结尾斜杠可有可无 |
| `api_key` | 直接填密钥；留空则按顺序去环境变量里找 |
| `model` | 模型名 |
| `temperature` | 采样温度，缺省 0.3 |
| `max_tokens` | 回复长度上限，缺省 1024。**思考模型务必调大**，思考占满预算会导致 `content` 为空 |
| `system_prompt` | 覆盖全局 `prompts.system`；留空则用全局 |
| `extra_headers` | 额外 HTTP 头，例如自定义鉴权或路由字段 |
| `extra_body` | 厂商私有参数，原样并入请求体；同名键会覆盖上面的 `temperature` / `max_tokens` |

`extra_body` 是放思考/推理档位的地方，例如：

```yaml
extra_body:
  thinking: { type: "enabled" }        # DeepSeek 风格开关
  reasoning_effort: "low"              # low | high | max
```

### `game` — 对局参数

| 键 | 缺省 | 说明 |
|---|---|---|
| `delay_between_moves_ms` | 500 | 两手之间的停顿毫秒数，方便观战 |
| `request_timeout_s` | 120 | 单次 HTTP 请求超时秒数。**注意**：程序内置缺省是 120，但仓库自带的 `config/config.yaml` 里写的是 600；改配置时以文件里的值为准。思考模型一次要几分钟，请调到比最慢的回复更宽松 |
| `invalid_move_retries` | 2 | 模型回了非法或无法解析的内容时，重问几次 |
| `request_retries` | 2 | 网络中断 / HTTP 失败时，重试几次 |
| `max_fullmoves` | 200 | 回合数（红+黑各一手）上限，达到判和；`0` 表示不限 |
| `threefold_repetition` | true | 同一局面（含行棋方）出现三次判和 |

两个重试额度**分开计数**：网络抖动不会吃掉留给非法着法的重试次数，反之亦然。

### `prompts` — 提示词

| 键 | 缺省 | 说明 |
|---|---|---|
| `allow_resign` | true | 是否告诉模型可以认输 |
| `system` | 见文件 | 系统提示词，`{side}` 会替换成 `Red` / `Black`。刻意写得很短，信息太多反而干扰模型 |

## 密钥

`api_key` 的解析顺序（`config/settings.py:resolve_api_key`）：

1. 配置文件里非空的 `api_key`；
2. 环境变量 `<NAME>_API_KEY` —— 把 `name` 转成大写，**空格和连字符都替换成下划线**（小数点保留）。
   例如 `name: Red-GLM-5.3-Flash-low` 对应 `RED_GLM_5.3_FLASH_LOW_API_KEY`；
3. 环境变量 `OPENAI_API_KEY`。

## 界面

程序打开**三个窗口**。

**1. 主窗口「LLM 中国象棋对弈」**

- **棋盘** —— 用 `Art_Assets/` 里的美术资源绘制。上一手以绿色箭头从起点指向终点，两端方格淡黄高亮；
  被将军的将/帅方格红底，选中的棋子绿底。
- **棋子面板「编辑局面」** —— 勾上「编辑局面」后，左键放置/走子，右键删除，可以摆任意局面再开打。
- **对局信息** —— 状态栏与当前 FEN。等待对方走棋时状态栏实时刷新已思考的秒数。
- **对局控制** —— 红/黑方选手下拉框、「开始对弈」「停止」「测试双方 API 连接」、
  「编辑局面」「翻转棋盘」两个勾选框、「重置为初始局面」「清空棋盘」。

**2. 两个 API 通信日志窗口**（红方一个、黑方一个）

启动时打印初始化信息（选手名、端点、模型、参数、密钥来自配置文件还是环境变量）。
之后逐条显示发给模型的完整请求体和模型的原始返回；思考模型单独返回的
`reasoning_content`（思维链）也会打印，解析结果（`Parsed answer: ...`）同样记录在案。

## 落盘日志

每次启动自动创建 `logs/session_YYYYMMDD_HHMMSS/`：

| 文件 | 内容 |
|---|---|
| `red_api.log` / `black_api.log` | 对应日志窗口内容的完整镜像 |
| `moves.txt` | 中文记谱棋谱，含每手思考用时与最终结果 |

## 对弈协议

### 每次发给模型的内容

系统提示词 + 一条 user 消息，全部英文且刻意精简：

```
Current position (FEN): <fen>
It is your turn to move. You play Red|Black.
Legal moves: b7b4, h7e0, ...
[If your position is hopeless you may resign by replying exactly "resign".]
Reply with exactly one legal move in coordinate notation (e.g. "b7e4") or resign.
```

方括号那行只在 `allow_resign: true` 时出现；不允许认输时，最后一句改为
`Reply with exactly one legal move in coordinate notation (e.g. "b7e4").`

**坐标约定**：横线 `a`–`i` 自红方视角从左到右，纵线 `0`–`9` 从黑方底线（0）到红方底线（9），
着法形如 `b7e4`，与 FEN 的行序一致。

### 怎么解析模型的回复

思考模型往往先写一大段分析、把 FEN 和着法列表原文抄回去，最后才在末句给出结论。
解析器（`llm/prompts.py:extract_move`）按以下优先级取值：

1. **认输** —— 整条回复或最后一行是 `resign`（`I would like to resign.` 这类包装也认）；
2. **明确声明的选择** —— `I will select \`d9d1\`.`、`Answer: b0c2`、
   `Therefore, **b0c2** is the best move.`；同一条回复里取最后出现的那一处，
   而 `if I play d9d1…` 这类假设/条件句一律不算声明；
3. 否则取回复中最后出现的**合法**着法 —— 模型是边分析边收敛的，结论通常在最后；
4. 都不合法时，返回最后出现的着法字形，由程序带着模型的原话重新发问。

引用提示词的内容永远不会被误当成答案：FEN 串（例如 `4C2c1` 里含有形如 `c2c1` 的子串）、
回显的 `Legal moves: ...` 列表、以及提示词里 `e.g. "b7e4"` 的示例，都会先被屏蔽掉再解析。

### 结束条件

| 情况 | 结果 |
|---|---|
| 将死 | 对方获胜 |
| 困毙（无着可动） | 无着可动的一方判负 |
| 将/帅被吃 | 对方获胜 |
| 一方认输 | 对方获胜 |
| 三次重复 / 达到步数上限 | 和棋 |
| 一方连续返回非法着法，重试耗尽 | 对方获胜 |
| 一方 API 反复失败，重试耗尽 | 对方获胜 |
| 用户点「停止」 | 对局中止 |

## 项目结构

```
main.py              入口：解析 --config，装配三个窗口
chess/
  engine.py          规则引擎：Board / Move / FEN / 合法着法 / 胜负判定
  notation.py        中文记谱（马二进三 / 炮8平5）
config/
  settings.py        配置加载、缺省值、api_key 解析
  config.yaml        选手档案与对局参数
game/
  controller.py      对局主循环：出题 → 校验 → 落子 → 换边，以及重试与终止判定
  session_log.py     会话日志落盘
llm/
  prompts.py         提示词构造 + 回复解析
  client.py          OpenAI 兼容 HTTP 客户端（QThread 包装，不阻塞界面）
ui/
  main_window.py     主窗口：棋盘 + 着法列表 + 控制区
  board_widget.py    棋盘绘制（美术资源、高亮、箭头）
  log_window.py      API 通信日志窗口
Art_Assets/          棋盘与棋子美术资源
requirements.txt     依赖清单
```

## 已知限制

- 亚洲规则里的**长打 / 长将禁着未实现**，只有简单的三次重复判和。
- 解析器是启发式的：模型答非所问时只能重问，重试耗尽即判该方负。
- 每手只让模型回一个坐标着法，没有搜索、没有候选评估，棋力完全取决于模型本身。
