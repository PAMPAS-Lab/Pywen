# Pywen SKILLS 说明

## 概述

SKILLS 是 Pywen 的技能发现与注入系统，实现参考了OpenAI/Codex 的 Skills 功能。
它通过 Markdown 文件定义技能（Skills），Pywen在启动时会按照一定顺序查找发现这些技能，
并在对话中根据用户需求或技能描述自动加载和执行相应的技能。
如果技能中有脚本或应用，Pywen还会在自动在需要时调用这些脚本或应用。

## 细节介绍

### SKILL 查找顺序

启动时会自动查找是否有SKILLS，查找顺序依次是：

```
1. REPO (项目级)   >  2. USER (用户级)  >  3. SYSTEM (系统级)  >  4. ADMIN (管理员级)
```

- **REPO (repo)**: 当前项目仓库内的 `.pywen/skills/` 目录
- **USER (user)**: 用户主目录下的 `~/.pywen/skills/` 目录
- **SYSTEM (system)**: `~/.pywen/skills/.system/` 目录（嵌入式系统技能）
- **ADMIN (admin)**: `/etc/pywen/skills/` 目录（仅 POSIX 系统）

**优先级规则**：当不同范围内存在同名技能时，优先级高的生效（REPO > USER > SYSTEM > ADMIN）。

### 自动发现机制

1. 启动时，系统递归扫描所有技能根目录
2. 查找名为 `SKILL.md` 的文件
3. 解析文件中的 YAML Frontmatter 提取元数据
4. 去重并按名称排序
5. 缓存结果（按工作目录）

## SKILL文件格式

### SKILL.md 结构

每个技能由一个 `SKILL.md` 文件定义，其中`SKILL.md`文件是必需的，其他则是可选的。
`SKILL.md` 采用 YAML Frontmatter + Markdown 正文的格式：

```markdown
---
name: 名称
description: 描述，用于触发匹配
metadata:
  short-description: 简短描述（可选）
---

注册SKILL时，name以及description字段的内容会被添加到提示词中发送给Agent。

# 技能详细说明

这里是技能的完整文档，包含：
- 功能介绍
- 使用方法
- 参数说明
- 示例代码
- 注意事项

## 子章节

可以包含任意 Markdown 内容...
```

### 字段说明

| 字段 | 必填 | 最大长度 | 说明 |
|------|------|----------|------|
| `name` | 是 | 64 字符 | 技能唯一名称 |
| `description` | 是 | 1024 字符 | 技能描述，用于触发匹配 |
| `metadata.short-description` | 否 | 1024 字符 | 简短描述（可选） |

## SKILL 示例

以下是一个简单的docker技能，用于告诉模型具体的使用方法。当然由于docker太通用了，
即便没有这个技能，模型大概率也会知道如何使用docker，但是使用docker技能时，
不仅可以添加一些自定义技能，还可以增加一些限制，比如禁止执行某些命令。

### Docker技能示例

**文件**: `~/.pywen/skills/docker/SKILL.md`

```markdown
---
name: docker
description: 使用 Docker 进行容器化管理，包括镜像构建、容器运行、网络配置等
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

### Docker Compose
- `docker-compose up`: 启动服务
- `docker-compose down`: 停止服务

## 使用限制

1. 不会执行危险的 `docker rm -f` 命令
2. 不会修改生产环境的容器配置
3. 需要用户确认后才能删除镜像
```

这个示例太简单，只有`SKILL.md`文件，实际中还包含`scripts/`,`schema.json`,
`examples/`以及方便用户阅读的`README.md`文件。

## 使用方法

对于已有的SKILL或者从第三方下载的SKILL，可按照前文介绍的SKILL查找顺序，放置到其中任一目录即可。
启动Pywen即可。比如我设置了三个SKILLS:

```
✦a87c1db4 ❯ 当前有哪些可用的SKILLS？
✅ Trajectory saved to: /home/xxx/.pywen/trajectories/trajectory_20260109_000314.json
🔵 User:当前有哪些可用的SKILLS？

🤖 
I'll check the current available skills by reading the project structure.
🔧 Calling ls tool...

╭─ ✓ list ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ 📄 docx/                                                                                                                                                                                                                                                                                                            │
│ 📄 pdf/                                                                                                                                                                                                                                                                                                             │
│ 📄 pptx/                                                                                                                                                                                                                                                                                                            │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
🤖 
当前可用的SKILLS有：

1. **docx** - 文档创建、编辑和分析技能，支持跟踪更改、评论、格式保留和文本提取
2. **pdf** - PDF操作工具包，用于提取文本和表格、创建新PDF、合并/拆分文档和处理表单
3. **pptx** - 演示文稿创建、编辑和分析技能

===================================================

这些技能位于 `/home/xxx/workdir/test/pywen/.pywen/skills/` 目录下，每个技能都有对应的 `SKILL.md` 文件包含详细的使用说明。
✅ Task completed!
```

## 故障排除

### 技能未加载

比如技能未触发，可以询问模型当前有哪些技能，如果模型没发现我们添加的技能，
即"技能未加载"

1. 检查 `SKILL.md` 文件名是否正确
2. 确认文件位于正确的技能目录下
3. 验证 YAML Frontmatter 格式正确
4. 确保 `name` 和 `description` 字段不为空

### 加载错误

查看 `outcome.errors` 获取详细信息，常见错误：
- `missing YAML frontmatter`: 缺少 `---` 分隔符
- `missing field 'name'`: 未找到 name 字段
- `missing field 'description'`: 未找到 description 字段
- `exceeds maximum length`: 字段长度超出限制

### 技能未触发

这种情况时有发生，可能与系统提示词相关，也可能与模型相关，
最有效的方法是显示调用技能。

1. 检查技能描述是否与任务匹配
2. 确认技能已被正确加载
3. 尝试显式调用技能（使用 `$SkillName`）
