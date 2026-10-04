# LLM Play Chinese Chess（大语言模型中国象棋对弈）

让两个 LLM 下中国象棋：程序把局面（FEN）和全部合法着法以英文提示词发给当前行棋方的
LLM，模型回复一个着法（或认输），程序判定合法性后照着实现在图形界面上，再轮到另一方。
所有 API 均使用 OpenAI 兼容的 `/chat/completions` 格式。

## 界面

程序打开 **三个窗口**：

1. **主窗口** — 棋盘（`Art_Assets` 美术资源，走子后以绿色箭头指示上一手）、
   双方走子信息（中文记谱如“马二进三”，并附每手思考用时）、当前 FEN、
   对局控制（选择红/黑方选手、开始、停止、测试 API 连接、编辑局面、
   重置/清空棋盘、翻转棋盘）。等待对方走棋时状态栏实时显示思考秒数。
2. **两个 API 通信日志窗口**（红方一个、黑方一个）— 启动时显示初始化信息，
   之后逐条显示每次发给模型的完整提示词（含 FEN、合法着法列表）和模型的原始返回。

## 日志落盘

每次启动自动创建 `logs/session_YYYYMMDD_HHMMSS/`：

- `red_api.log` / `black_api.log` — 两个日志窗口内容的完整镜像；
- `moves.txt` — 中文记谱棋谱（含每手用时与最终结果）。

## 运行

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt   # Windows
.venv/Scripts/python main.py
```

也可以指定配置文件：`python main.py --config 路径/config.yaml`

## 配置（config/config.yaml）

所有选项都从配置文件读取，详见文件内注释：

- `game`：走子间隔、非法着法重试次数（`invalid_move_retries`）、HTTP 失败重试次数
  （`request_retries`，与前者分开计数，网络抖动不会占用非法着法的重试额度）、
  请求超时、和棋规则（长打禁着**未**实现，仅简单三次重复判和；步数上限判和，0 为不限）。
- `prompts`：系统提示词（英文，保持简短以免干扰模型）、是否允许认输。
- `players`：选手档案列表（name / base_url / api_key / model / temperature /
  max_tokens / 可选 system_prompt 覆盖 / 可选 extra_headers）。
  主窗口的红方、黑方下拉框分别从该列表中选取。
  `api_key` 为空时依次尝试环境变量 `<NAME>_API_KEY`、`OPENAI_API_KEY`。

> ⚠️ `config/config.yaml` 已随仓库发布，其中 `api_key` 必须保持为空字符串。
> 切勿把填好的密钥提交进版本库；推荐用环境变量注入，或另存为
> `config/config.local.yaml`（已被 `.gitignore` 忽略）后在启动时用
> `python main.py --config config/config.local.yaml` 指定。

## 提示词格式

全部为英文且刻意精简：

```
系统提示词（角色、FEN 记谱说明、坐标说明、目标）
当前局面 (FEN): <fen>
It is your turn to move. You play Red|Black.
Legal moves: b7b4, h7e0, ...
[If your position is hopeless you may resign by replying exactly "resign".]
Reply with exactly one legal move in coordinate notation (e.g. "b7e4") or resign.
```

坐标约定：横线 a–i 自红方视角从左到右，纵线 0–9 从黑方底线到红方底线，
着法形如 `b7e4`（与 FEN 的行序一致）。

思考模型往往先写一大段分析再给答案，因此解析（`llm.prompts.extract_move`）按以下顺序取值：

1. 认输：整条回复或最后一行就是 `resign`（如“局面已经输定。\n\nresign”）；
2. 回复中明确声明的选择，如 `I will select \`d9d1\`.`、`Answer: b0c2`、
   `Therefore, **b0c2** is the best move.`（“如果下 X 会怎样”这类假设不算声明）；
3. 否则取回复中**最后**提到的合法着法（模型是边分析边收敛到结论的）；
4. 都不合法时，返回最后出现的着法字形，交由程序重试（重试提示里会带上模型的原话）。

引用提示词里的内容绝不会被当成答案：FEN 串（例如 `4C2c1` 里含有形如 `c2c1` 的子串）、
回显的 `Legal moves: ...` 列表、以及提示词中 `e.g. "b7e4"` 的示例都会被忽略。
非法着法按 `invalid_move_retries` 重试，重试耗尽后判该方负。

## 结束条件

将死 / 困毙（无着可动判负）/ 认输 / 三次重复或步数上限和棋 / 用户按“停止”/
 某方 API 出错或连续返回非法着法（该方判负）。
