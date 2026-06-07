import math
import time
from pathlib import Path


class IntelligentFileRestorer():
    def __init__(self):
        self.max_files = 20
        self.max_tokens_per_file = 8192
        self.total_token_limit = 32768
        self.scoring_weights = {
            "temporal": 0.35,
            "frequency": 0.25,
            "operation": 0.20,
            "fileType": 0.20,
        }

    def calculate_importance_score(self, metadata):
        total_score = 0.0
        temporal_score = self.calculate_temporal_score(metadata)
        total_score += temporal_score * self.scoring_weights["temporal"]
        frequency_score = self.calculate_frequency_score(metadata)
        total_score += frequency_score * self.scoring_weights["frequency"]
        operation_score = self.calculate_operation_score(metadata)
        total_score += operation_score * self.scoring_weights["operation"]
        file_type_score = self.calculate_file_type_score(metadata)
        total_score += file_type_score * self.scoring_weights["fileType"]

        return round(total_score)

    def calculate_temporal_score(self, metadata):
        now = time.time() * 1000
        hours_since_last_access = (now - metadata["lastAccessTime"]) / (1000 * 60 * 60)
        if hours_since_last_access <= 1:
            return 100
        elif hours_since_last_access <= 6:
            return 90
        elif hours_since_last_access <= 24:
            return 75
        else:
            return max(10, 75 * math.exp(-0.1 * (hours_since_last_access - 24)))

    def calculate_frequency_score(self, metadata):
        total_operations = metadata["readCount"] + metadata["writeCount"] + metadata["editCount"]
        score = min(80, total_operations * 5)
        recent_operations = metadata.get("operationsInLastHour", 0)
        score += min(20, recent_operations * 10)
        return min(100, score)

    def calculate_operation_score(self, metadata):
        score = 0
        score += metadata["writeCount"] * 15
        score += metadata["editCount"] * 10
        score += metadata["readCount"] * 3
        if metadata.get("lastOperation") == "write":
            score += 25
        elif metadata.get("lastOperation") == "edit":
            score += 15
        return min(100, score)

    def calculate_file_type_score(self, metadata):
        extension = metadata["path"].split(".")[-1].lower()
        code_extensions = {
            "js": 100, "ts": 100, "jsx": 95, "tsx": 95,
            "py": 90, "java": 85, "cpp": 85, "c": 85,
            "go": 80, "rs": 80, "php": 75, "rb": 75
        }
        
        config_extensions = {
            "json": 70, "yaml": 65, "yml": 65, "toml": 60,
            "xml": 55, "ini": 50, "env": 50, "config": 50

        }

        doc_extensions = {
            "md": 40, "txt": 30, "doc": 25, "docx": 25,
            "pdf": 20, "html": 35, "css": 45

        }

        if extension in code_extensions:
            return code_extensions[extension]
        elif extension in config_extensions:
            return config_extensions[extension]
        elif extension in doc_extensions:
            return doc_extensions[extension]
        return 30

    def find_best_fit_file(self, files, remaining_tokens):
        sorted_files = sorted(files, key=lambda f: f["score"], reverse=True)
        for f in sorted_files:
            if f["estimatedTokens"] <= remaining_tokens:
                return f
        return None

    def select_optimal_file_set(self, ranked_files):
        selected_files = []
        total_tokens = 0
        file_count = 0
        sorted_files = sorted(ranked_files, key=lambda f: f["score"], reverse=True)
        i = 0
        while i < len(sorted_files):
            file = sorted_files[i]
            if file_count >= self.max_files:
                #print(f"📊 达到文件数量限制: {self.max_files}")
                break
            if file["estimatedTokens"] > self.max_tokens_per_file:
                #print(f"⚠️ 文件 {file['path']} 超出单文件限制，跳过")
                i += 1
                continue
            if total_tokens + file["estimatedTokens"] > self.total_token_limit:
                #print(f"📊 添加 {file['path']} 将超出总Token限制")
                remaining_tokens = self.total_token_limit - total_tokens
                alternative_file = self.find_best_fit_file(sorted_files[i+1:], remaining_tokens)
                if alternative_file:
                    selected_files.append(alternative_file)
                    total_tokens += alternative_file["estimatedTokens"]
                    file_count += 1
                    sorted_files.remove(alternative_file)
                i += 1
                continue
            selected_files.append(file)
            total_tokens += file["estimatedTokens"]
            file_count += 1
            i += 1
        return {
            "files": selected_files,
            "totalFiles": file_count,
            "totalTokens": total_tokens,
            "efficiency": (total_tokens / self.total_token_limit) * 100 if self.total_token_limit > 0 else 0
        }

    # API
    def file_recover(self, file_counter) -> str:
        if not file_counter:
            #print("⚠️ 暂无文件记录，无法恢复。")
            return '' 

        # 1. 计算每条记录的 importance score
        ranked_files = []
        for meta in file_counter.values():
            meta_copy = meta.copy()              # 防止打分函数内部修改
            meta_copy["score"] = self.calculate_importance_score(meta_copy)
            ranked_files.append(meta_copy)

        # 2. 按分数+约束选最优文件集
        selected = self.select_optimal_file_set(ranked_files)

        # 3. 按分数倒序读取内容
        contents = []
        base_path = Path.cwd().resolve()
        for file_info in sorted(selected["files"], key=lambda f: f["score"], reverse=True):
            full_path = base_path / file_info["path"]
            try:
                text = full_path.read_text(encoding="utf-8")
                contents.append(
                    f"File: {file_info['path']}\n"
                    f"Score: {file_info['score']}\n"
                    f"Content:\n{text}\n\n"
                )
            except Exception as e:
                contents.append(
                    f"File: {file_info['path']}\n"
                    f"Error reading: {e}\n\n"
                )

        return "".join(contents)

    # API
    def update_file_metrics(self, arguments, result, file_metrics, tool_name):
        try:
            # 1) 取文件路径
            file_path_str = None
            if isinstance(result, dict) and "file_path" in result:
                file_path_str = result["file_path"]
            elif isinstance(arguments, dict):
                file_path_str = arguments.get("path")

            if not file_path_str:
                raise ValueError("missing file path")

            file_path = Path(file_path_str).resolve()

            # 2) 计算 key
            try:
                key = str(file_path.relative_to(Path.cwd()))
            except ValueError:
                key = str(file_path)

            # 3) 重新 stat —— 失败就整体跳过，不硬凑
            st = file_path.stat()
            last_access_ms = int(st.st_atime * 1000)
            est_tokens = st.st_size // 4

        except Exception:
            # 任何一步拿不到可靠数据就直接放弃本次指标更新
            return

        # 3) 建档案（尽量从 stat 补充；失败则使用兜底值）
        if key not in file_metrics:
            # 第一次见：根据本次工具类型初始化计数
            init_read = 1 if tool_name == "read_file" else 0
            init_write = 1 if tool_name == "write_file" else 0
            init_edit = 1 if tool_name == "edit" else 0
            last_op = {"read_file": "read", "write_file": "write", "edit": "edit"}[tool_name]

            file_metrics[key] = {
                "path": key,
                "lastAccessTime": last_access_ms,
                "readCount": init_read,
                "writeCount": init_write,
                "editCount": init_edit,
                "operationsInLastHour": 0,
                "lastOperation": last_op,
                "estimatedTokens": est_tokens,
            }
        else:
            # 已存在：只累加计数、刷新时间和大小
            meta = file_metrics[key]

            if tool_name == "read_file":
                meta["readCount"] += 1
                meta["lastOperation"] = "read"
            elif tool_name == "write_file":
                meta["writeCount"] += 1
                meta["lastOperation"] = "write"
            elif tool_name == "edit":
                meta["editCount"] += 1
                meta["lastOperation"] = "edit"

            meta["lastAccessTime"] = last_access_ms
            meta["estimatedTokens"] = est_tokens
