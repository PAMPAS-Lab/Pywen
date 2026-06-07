import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

BFCL_REPO_URL = "https://github.com/ShishirPatil/gorilla.git"
BFCL_DATA_SUBDIR = "berkeley-function-call-leaderboard/bfcl_eval/data"


@dataclass
class BFCLSample:
    id: str
    question: str
    functions: List[Dict[str, Any]]
    ground_truth: List[str]
    category: str
    metadata: Dict[str, Any]


class BFCLDataset:
    SUPPORTED_CATEGORIES = [
        "simple_python",
        "multiple",
        "parallel",
        "parallel_multiple",
        "java",
        "javascript",
        "live_simple",
        "live_multiple",
        "live_parallel",
        "live_parallel_multiple",
        "live_relevance",
        "live_irrelevance",
        "irrelevance",
        "multi_turn_base",
        "multi_turn_miss_func",
        "multi_turn_miss_param",
        "multi_turn_long_context",
    ]

    CATEGORY_FILE_MAP = {
        "simple_python": "BFCL_v4_simple_python.json",
        "multiple": "BFCL_v4_multiple.json",
        "parallel": "BFCL_v4_parallel.json",
        "parallel_multiple": "BFCL_v4_parallel_multiple.json",
        "java": "BFCL_v4_simple_java.json",
        "javascript": "BFCL_v4_simple_javascript.json",
        "live_simple": "BFCL_v4_live_simple.json",
        "live_multiple": "BFCL_v4_live_multiple.json",
        "live_parallel": "BFCL_v4_live_parallel.json",
        "live_parallel_multiple": "BFCL_v4_live_parallel_multiple.json",
        "live_relevance": "BFCL_v4_live_relevance.json",
        "live_irrelevance": "BFCL_v4_live_irrelevance.json",
        "irrelevance": "BFCL_v4_irrelevance.json",
        "multi_turn_base": "BFCL_v4_multi_turn_base.json",
        "multi_turn_miss_func": "BFCL_v4_multi_turn_miss_func.json",
        "multi_turn_miss_param": "BFCL_v4_multi_turn_miss_param.json",
        "multi_turn_long_context": "BFCL_v4_multi_turn_long_context.json",
    }

    def __init__(self, bfcl_data_dir: str | Path | None = None, category: str = "simple_python", auto_download: bool = True):
        self.base_dir = Path(__file__).parent
        if bfcl_data_dir is None:
            self.data_dir = self.base_dir / "gorilla" / BFCL_DATA_SUBDIR
        else:
            self.data_dir = Path(bfcl_data_dir)
        self.category = category
        self.auto_download = auto_download
        self.samples: List[BFCLSample] = []
        self._validate_category()
        self._load_data()

    def _validate_category(self):
        if self.category not in self.SUPPORTED_CATEGORIES:
            raise ValueError(f"不支持的类别: {self.category}。支持的类别: {self.SUPPORTED_CATEGORIES}")

    def _get_data_file_path(self) -> Path:
        filename = self.CATEGORY_FILE_MAP.get(self.category, f"BFCL_v4_{self.category}.json")
        return self.data_dir / filename

    def _clone_bfcl_repo(self) -> bool:
        repo_dir = self.base_dir / "gorilla"
        if repo_dir.exists() and (repo_dir / BFCL_DATA_SUBDIR).exists():
            return True
        print("📥 正在克隆BFCL仓库 (sparse checkout, 仅下载数据目录)...")
        try:
            if repo_dir.exists():
                shutil.rmtree(repo_dir)
            subprocess.run(
                ["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse", BFCL_REPO_URL, str(repo_dir)],
                check=True, capture_output=True, text=True
            )
            subprocess.run(
                ["git", "sparse-checkout", "set", BFCL_DATA_SUBDIR],
                cwd=str(repo_dir), check=True, capture_output=True, text=True
            )
            print(f"✅ BFCL数据下载完成: {self.data_dir}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"❌ 克隆失败: {e.stderr}")
            return False
        except FileNotFoundError:
            print("❌ 请先安装git")
            return False

    def _load_data(self):
        data_path = self._get_data_file_path()
        if not data_path.exists():
            if self.auto_download:
                if not self._clone_bfcl_repo():
                    return
                data_path = self._get_data_file_path()
                if not data_path.exists():
                    print(f"❌ 数据文件不存在: {data_path}")
                    return
            else:
                print(f"警告: 数据文件不存在 {data_path}")
                return

        ground_truth_map = self._load_ground_truth()

        with open(data_path, 'r', encoding='utf-8') as f:
            raw_data = []
            for line in f:
                line = line.strip()
                if line:
                    raw_data.append(json.loads(line))

        for idx, item in enumerate(raw_data):
            sample = self._parse_sample(item, idx, ground_truth_map)
            if sample:
                self.samples.append(sample)

        print(f"✅ 加载了 {len(self.samples)} 个样本 (类别: {self.category})")

    def _load_ground_truth(self) -> Dict[str, List[str]]:
        filename = self.CATEGORY_FILE_MAP.get(self.category, f"BFCL_v4_{self.category}.json")
        gt_path = self.data_dir / "possible_answer" / filename
        gt_map = {}
        if gt_path.exists():
            with open(gt_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        item = json.loads(line)
                        sample_id = item.get("id", "")
                        gt = item.get("ground_truth", [])
                        gt_map[sample_id] = gt
        return gt_map

    def _parse_sample(self, item: Dict[str, Any], idx: int, ground_truth_map: Optional[Dict[str, Any]] = None) -> Optional[BFCLSample]:
        try:
            sample_id = item.get("id") or f"{self.category}_{idx}"

            question_raw = item.get("question") or item.get("query") or item.get("user_query") or item.get("prompt", "")
            question = ""
            if isinstance(question_raw, str):
                question = question_raw
            elif isinstance(question_raw, list) and question_raw:
                if isinstance(question_raw[0], list) and question_raw[0]:
                    if isinstance(question_raw[0][0], dict):
                        question = str(question_raw[0][0].get("content", ""))
                elif isinstance(question_raw[0], dict):
                    question = str(question_raw[0].get("content", ""))

            functions = item.get("functions") or item.get("function") or item.get("tools") or []
            if not isinstance(functions, list):
                functions = [functions]

            ground_truth: List[Any] = []
            if ground_truth_map and sample_id in ground_truth_map:
                ground_truth = ground_truth_map[sample_id]
            elif item.get("ground_truth"):
                ground_truth = item.get("ground_truth", [])

            return BFCLSample(
                id=sample_id,
                question=question,
                functions=functions,
                ground_truth=ground_truth,
                category=self.category,
                metadata=item.get("metadata", {})
            )
        except Exception as e:
            print(f"警告: 解析样本 {idx} 失败: {e}")
            return None

    def __len__(self) -> int:
        return len(self.samples)

    def __iter__(self) -> Iterator[BFCLSample]:
        return iter(self.samples)

    def __getitem__(self, idx: int) -> BFCLSample:
        return self.samples[idx]

