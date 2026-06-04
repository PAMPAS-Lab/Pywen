# Pywen Skills 说明

## 概述

Skills 是 Pywen 的技能发现与注入系统，参考 OpenAI/Codex 的 Skills 功能设计。它通过 Markdown 文件定义技能（Skills），Pywen 在启动时按一定顺序查找并发现这些技能，在对话中根据用户需求或技能描述自动加载和执行相应技能。如果技能中包含脚本或应用，Pywen 还会在需要时自动调用这些脚本或应用。

Pywen Skills 框架提供以下核心能力：

1. **多层级技能发现** — 支持项目级、用户级、系统级、管理员级四层技能目录
2. **增量热更新** — 基于文件 mtime 追踪，仅重解析变化的技能文件
3. **依赖声明与解析** — 技能可声明对其他技能的依赖及版本约束
4. **安全扫描** — 对技能内容进行提示注入、路径遍历等安全检查
5. **结构化审计日志** — 记录所有技能加载、注入、错误事件
6. **健康检查** — 验证技能完整性，包括脚本引用和符号链接
7. **语义相关性排序** — 基于用户输入对技能进行相关性排序

## 目录结构

```
skills/
├── docx/                      # 技能目录
│   ├── SKILL.md               # 技能定义文件（必需）
│   ├── scripts/               # 脚本目录（可选）
│   │   ├── create.py
│   │   └── extract.py
│   ├── schema.json            # 数据模式（可选）
│   └── examples/              # 示例目录（可选）
└── pdf/
    ├── SKILL.md
    └── scripts/
```

## 技能查找顺序

启动时会自动查找技能，查找顺序依次为：

```
1. REPO (项目级)  >  2. USER (用户级)  >  3. SYSTEM (系统级)  >  4. ADMIN (管理员级)
```

| 层级 | 路径 | 说明 |
|------|------|------|
| **REPO** | `{项目根}/.pywen/skills/` | 当前 Git 仓库内的技能，仅在存在 `.git` 目录时生效 |
| **USER** | `~/.pywen/skills/` | 用户主目录下的技能 |
| **SYSTEM** | `~/.pywen/skills/.system/` | 嵌入式系统技能 |
| **ADMIN** | `/etc/pywen/skills/` | 仅 POSIX 系统，管理员安装的技能 |

**优先级规则**：当不同层级存在同名技能时，优先级高的生效（REPO > USER > SYSTEM > ADMIN）。解析完成后系统按名称排序并去重。

## SKILL.md 文件格式

### 基本结构

每个技能由一个 `SKILL.md` 文件定义，采用 YAML Frontmatter + Markdown 正文格式：

```markdown
---
name: 技能名称
description: 技能描述，用于触发匹配
version: 1.0.0
metadata:
  short-description: 简短描述（可选）
requires:
  - name: docker
    min_version: "1.0.0"
    max_version: "2.0.0"
---

# 技能详细说明

这里是技能的完整文档，包含功能介绍、使用方法、参数说明等。
```

### 字段说明

| 字段 | 必填 | 最大长度 | 说明 |
|------|------|----------|------|
| `name` | 是 | 64 字符 | 技能唯一名称 |
| `description` | 是 | 1024 字符 | 技能描述，用于触发匹配 |
| `version` | 否 | — | 语义版本（SemVer 2.0.0） |
| `metadata.short-description` | 否 | 1024 字符 | 简短描述 |
| `requires` | 否 | — | 依赖声明列表 |

### 语义版本（SemVer 2.0.0）

`version` 字段支持完整的 SemVer 2.0.0 格式：

| 格式 | 示例 | 说明 |
|------|------|------|
| 标准版本 | `1.2.3` | 主版本.次版本.修订 |
| 预发布版 | `1.2.3-beta.1` | 支持预发布标识 |
| 构建元数据 | `1.2.3+build.123` | 构建元数据（比较时忽略） |

### 依赖声明

技能可通过 `requires` 字段声明对其他技能的依赖：

```markdown
---
name: docker-compose
description: 使用 Docker Compose 管理多容器应用
requires:
  - name: docker
    min_version: "1.0.0"
  - name: python
    min_version: "3.8.0"
---
```

依赖解析时会验证：
- 依赖技能是否已安装
- 版本是否满足 `min_version` / `max_version` 约束
- 是否存在循环依赖

## 自动发现机制

1. 启动时，系统递归扫描所有技能根目录
2. 查找名为 `SKILL.md` 的文件（跳过符号链接目录）
3. 解析 YAML Frontmatter 提取元数据，同时执行安全扫描
4. 按名称排序并去重
5. 验证依赖声明
6. 缓存结果（按工作目录）

### 增量热更新

SkillsManager 使用文件级 mtime 追踪机制：

- **首次加载**：扫描所有技能文件并缓存
- **后续访问**：仅检查文件 mtime 变化
- **精确更新**：只重解析变化的技能文件，合并回缓存结果
- **去重与依赖重检**：合并后重新排序并验证依赖关系

无需重启即可感知技能目录中的新增、修改和删除操作。

## 安全扫描

### 扫描范围

加载技能时，系统对以下内容进行安全扫描：

1. **description 字段** — 描述文本中的风险模式
2. **frontmatter 原文** — 捕获自定义元数据字段中的注入
3. **SKILL.md 正文** — 完整正文内容

### 内置安全规则

| 规则 | 风险等级 | 描述 |
|------|----------|------|
| `prompt_injection_ignore` | HIGH | "ignore previous/all/above instructions" 等提示注入模式 |
| `prompt_injection_override` | HIGH | 系统提示覆盖尝试（system prompt override/bypass/hack） |
| `path_traversal` | HIGH | 路径遍历模式（`../../`） |
| `sensitive_file_access` | MEDIUM | 敏感文件引用（`/etc/passwd`、`~/.ssh`、`.env`） |

### 风险处理策略

| 风险等级 | 处理方式 |
|----------|----------|
| **HIGH** | 拒绝加载技能，抛出 `SkillParseError` |
| **MEDIUM** | 打印警告，技能仍可加载 |
| **LOW** | 仅记录，不阻断 |

### 信任路径

可通过 `configure_trusted_paths()` 配置信任路径，位于信任路径下的技能跳过安全扫描：

```python
from pywen.skills import configure_trusted_paths
configure_trusted_paths(["/path/to/internal/skills", "/opt/company/skills"])
```

## 审计日志

### 事件类型

系统通过 Python 标准 `logging` 模块（logger 名：`pywen.skills.audit`）输出结构化 JSON 审计事件：

| 事件 | 说明 |
|------|------|
| `skill_loaded` | 技能成功加载（记录名称、路径、层级、耗时） |
| `skill_load_failed` | 技能加载失败（记录路径、错误信息） |
| `skill_injected` | 技能注入上下文成功 |
| `skill_inject_failed` | 技能注入失败 |
| `system_skills_installed` | 系统技能安装完成 |
| `security_violation` | 安全扫描发现违规 |

### 日志配置示例

```python
import logging

# 配置审计日志输出到文件
handler = logging.FileHandler("skills_audit.log")
handler.setFormatter(logging.Formatter("%(message)s"))
logger = logging.getLogger("pywen.skills.audit")
logger.addHandler(handler)
logger.setLevel(logging.INFO)
```

### 输出格式

每条事件为单行 JSON：

```json
{"timestamp":"2026-05-17T22:00:00+08:00","event":"skill_loaded","skill_name":"docker","scope":"user","duration_ms":12.34}
```

## 健康检查

### 检查项目

| 检查项 | 说明 |
|--------|------|
| YAML 可解析性 | 重新解析 SKILL.md，确认无语法错误 |
| 正文脚本引用 | 从正文中提取 `scripts/...` 引用，验证文件存在 |
| 断裂符号链接 | 检测 `scripts/` 目录中的断裂符号链接 |
| 版本格式 | 验证 `version` 字段符合 SemVer 格式 |

### CLI 用法

```bash
# 文本格式输出
pywen skill health-check

# JSON 格式输出（CI 友好）
pywen skill health-check --json
```

### 输出示例

```
Checking 5 skills...

✓ docx (repo): OK
✗ pdf (user): FAIL
  - scripts/extract.py: referenced but not found
  - scripts/merge.sh: broken symbolic link
✓ docker (system): OK
✓ python (system): OK
✗ custom (user): FAIL
  - version: invalid semver format 'v1.0.0'

Summary: 3 OK, 2 FAILED
```

退出码：`0` = 全部健康，`1` = 存在故障。

## 相关性排序

根据用户输入对技能进行语义相关性排序：

```python
from pywen.skills import rank_skills_by_relevance

ranked = rank_skills_by_relevance(
    skills=outcome.skills,
    user_input="如何创建一个 Word 文档？",
    top_k=5,
)
```

排序结果可用于：
- 仅向模型注入最相关的技能，减少上下文消耗
- 实现渐进式披露（Progressive Disclosure）

## 技能示例

### Docker 技能示例

**文件**: `~/.pywen/skills/docker/SKILL.md`

```markdown
---
name: docker
description: 使用 Docker 进行容器化管理，包括镜像构建、容器运行、网络配置等
version: 1.0.0
metadata:
  short-description: Docker 容器管理
---

# Docker 技能

本技能提供 Docker 容器操作的相关能力。

## 核心功能

### 镜像管理
- `docker build`: 构建镜像
- `docker pull`: 拉取镜像
- `docker push`: 推送镜像
- `docker images`: 列出镜像

### 容器管理
- `docker run`: 运行容器
- `docker ps`: 列出运行中的容器
- `docker stop`: 停止容器
- `docker rm`: 删除容器

## 使用限制

1. 不会执行危险的 `docker rm -f` 命令
2. 不会修改生产环境的容器配置
3. 需要用户确认后才能删除镜像
```

### 带脚本的技能示例

```
skills/
└── pdf/
    ├── SKILL.md
    └── scripts/
        ├── extract.py      # scripts/extract.py
        └── merge.py        # scripts/merge.py
```

**SKILL.md** 中引用脚本：

```markdown
本技能提供以下脚本：

- `scripts/extract.py` — 从 PDF 提取文本和图片
- `scripts/merge.py` — 合并多个 PDF 文件
```

## 使用方法

### 安装技能

对于已有的技能或从第三方下载的技能，按照查找顺序放置到任一目录即可：

| 安装方式 | 路径 |
|----------|------|
| 项目级 | `{项目根}/.pywen/skills/` |
| 用户级 | `~/.pywen/skills/` |
| 系统级 | `~/.pywen/skills/.system/` |
| 管理员级（POSIX） | `/etc/pywen/skills/` |

### 编程使用

```python
from pathlib import Path
from pywen.skills import SkillsManager

# 初始化管理器
manager = SkillsManager(pywen_home=Path.home() / ".pywen")

# 获取当前工作目录的技能
outcome = manager.skills_for_cwd()
print(f"加载了 {len(outcome.skills)} 个技能")
print(f"加载耗时: {outcome.load_duration_ms:.2f}ms")

# 强制重新加载
outcome = manager.skills_for_cwd_with_options(
    cwd=Path.cwd(),
    force_reload=True,
)

# 健康检查
from pywen.skills import check_all_skills_health
reports = check_all_skills_health(outcome.skills)
```

### 提示词注入

```python
from pywen.skills import build_skill_injections

# 构建技能注入
injections = build_skill_injections(
    skills=outcome.skills,
    user_inputs=[UserInput.skill(name="docx", path=Path("..."))],
)

for item in injections.items:
    print(f"技能: {item.name}")
    print(item.contents)
```

## 故障排除

### 技能未加载

1. 检查 `SKILL.md` 文件名是否正确
2. 确认文件位于正确的技能目录下
3. 验证 YAML Frontmatter 格式正确
4. 确保 `name` 和 `description` 字段不为空

### 加载错误

查看 `outcome.errors` 获取详细信息，常见错误：

| 错误信息 | 说明 |
|----------|------|
| `missing YAML frontmatter` | 缺少 `---` 分隔符 |
| `missing field 'name'` | 未找到 name 字段 |
| `missing field 'description'` | 未找到 description 字段 |
| `exceeds maximum length` | 字段长度超出限制 |
| `Security violation` | 安全扫描拦截 |

### 技能未触发

最有效的方法是显式调用技能：

1. 检查技能描述是否与任务匹配
2. 确认技能已被正确加载
3. 尝试显式调用技能（使用 `$SkillName`）

### 健康检查失败

| 症状 | 解决方案 |
|------|----------|
| `referenced but not found` | 添加缺失的脚本文件，或修正引用路径 |
| `broken symbolic link` | 删除断裂链接或重新创建指向有效目标 |
| `invalid semver format` | 修正 `version` 字段为标准格式（如 `1.0.0`） |
