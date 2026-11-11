# 自建实测环境（deploy/）

在**你自己的电脑**上运行一套以生产规格搭建的被测对象：自架的开源 RAG 平台 Dify（固定版本 1.19.0，默认配置）加答信。
它**不是任何机构的系统**，结果只能表述为“自建环境实测”。平台只发布在 `127.0.0.1`，同一网络的其他人访问不到。

与 `testkit/range/` 的区别：靶场是 14 段虚构知识库加一个自写的检索服务，用来注入已知故障；这里换成市面上实际在用的平台和真实的公开文件，用来观察自然发生的错误。两者并存。

```
提问（答信 HTTP 适配器，仅本机） → bridge.py（127.0.0.1:8810） → 你自架的 Dify（127.0.0.1:8080）
                                        └ 记录检索到的段落（deploy/data/bridge_log.jsonl）
```

## 需要准备

- Docker（Compose 2.35 以上）、git、Python 3.10 以上；内存建议 8 GB 以上，磁盘预留 15 GB。
- 你自己的大模型 API 密钥（在 Dify 的界面里填，不经过本仓库）。
- 本仓库已安装：`pip install -e ".[dev]"`。

## 步骤

**1. 启动平台**

```bash
python deploy/env.py up        # 首次要下载镜像
python deploy/env.py status
```

**2. 在 Dify 界面里完成四件事**（浏览器打开 `http://127.0.0.1:8080/install`）

1. 建立管理员账号。
2. 设置 → 模型供应商：安装你使用的供应商插件并填入密钥；确认有一个对话模型和一个向量（Embedding）模型。
3. 知识库 → 创建：上传文件，分段与检索设置**保持默认**，等待索引完成。
4. 工作室 → 创建“聊天助手”：在“上下文”里关联上面的知识库，提示词只写一句普通的客服说明，发布；然后在“访问 API”创建密钥。

不要为了考试去调分段、检索或提示词：要测的是平台在默认配置下的表现。

**3. 填写设置并冻结标准**

```bash
cp deploy/.env.example deploy/.env      # 填 DIFY_APP_KEY、DAXIN_KB_DIR、DAXIN_SYSTEM_LABEL
```

标准由人确认后冻结，两种来源任选：

```bash
# a) 第一次试跑：用仿真靶场的知识库与标准（虚构，代号 BANK-X）
python deploy/env.py smoke-kb testkit/private/kb_smoke     # 把生成的 14 个文本文件上传到知识库
python testkit/range/setup_workspace.py deploy/data/ws

# b) 真实的公开文件：原件放 testkit/private/ 下（不提交），仓库内一律用代号
daxin init --ws deploy/data/ws
daxin policy draft testkit/private/kb/某文件.txt --ws deploy/data/ws --effective-from 2026-01-01   # LLM 草拟，只进草稿
daxin policy list --ws deploy/data/ws        # 逐条核对后再 confirm、freeze
```

**4. 考一轮**

```bash
python deploy/env.py exam --limit 5     # 先试 5 题
python deploy/env.py exam               # 全部题目；同一天再跑请加 --run 另给代号
```

产出在 `deploy/data/runs/<代号>/`：`blind_sheet.csv` 复制两份交给两位复核人各自填写；`meta_do_not_share_with_reviewers.json` 含被测系统指纹，不要给复核人。复核完成后：

```bash
daxin review-import 甲的表.csv --by 甲 --ws deploy/data/ws
daxin review-import 乙的表.csv --by 乙 --ws deploy/data/ws
daxin accuracy --ws deploy/data/ws
daxin release --ws deploy/data/ws
```

**5. 备份与每晚自动运行**

```bash
python deploy/env.py backup             # 一致性备份 + 审计链与锚点核对
```

每晚自动考试用系统自带的计划任务调用同一条命令，例如 cron：`0 2 * * * cd /路径/Daxin && python deploy/env.py exam && python deploy/env.py backup`（Windows 用“任务计划程序”）。

**6. 制度变更演练**

在知识库里换上新版文件，同时冻结新版标准、把 `DAXIN_SYSTEM_LABEL` 改成新的说明，再跑 `exam`。`daxin release` 应先因“标准有新版本未复测”降级，复测并复核后恢复。

## 密钥与数据放在哪里

| 内容 | 位置 | 是否进仓库 |
|---|---|---|
| Dify 应用密钥、审计链 HMAC 密钥 | `deploy/.env` | 否（gitignore） |
| 大模型密钥 | Dify 自己的数据库（Docker 卷） | 否 |
| Dify 源码与数据、答信工作区、日志、备份 | `deploy/data/` | 否（gitignore） |
| 公开文件原件 | `testkit/private/` | 否（gitignore） |

## 限制（如实）

- **指纹看不到平台内部设置。** 应用密钥读不到提示词、模型与检索参数。指纹只含应用名称与模式、公开参数的哈希、知识库目录中文件的哈希，以及你填写的 `DAXIN_SYSTEM_LABEL`。在 Dify 界面改了设置而没有改这个说明，指纹不会变。`DAXIN_KB_DIR` 也只是你声明的目录，程序无法核对它与平台内的知识库是否一致。
- **每题都是新会话**，不测多轮对话。
- **只在本机可用。** 没有 HTTPS、没有登录网关，不适合直接开放给他人。让复核人和受邀提问者从外部访问，需要搬到云主机并加上这两项，尚未实现。
- 检索日志 `bridge_log.jsonl` 含问题与回答原文，仅留在本机；对外材料请用答信的脱敏导出。
- 平台的桥接程序只用仓库测试里的替身接口验证过（`tests/test_deploy_bridge.py`），请求格式依据 Dify 1.19.0 随附的接口文档；换平台版本后需重新核对。
- 不得把桥接或适配器指向任何不是你自己架设的系统。
