import argparse
import contextlib
import os
import shlex
import shutil
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, cast

from datasets import load_dataset
from docker import DockerClient, from_env
from docker.errors import APIError, ImageNotFound, NotFound
from docker.models.containers import Container, ExecResult
from tqdm import tqdm

AGENT_IMAGE = "pywen/agent:0.1"
AGENT_IMAGE_DOCKERFILE = "Dockerfile.pywen-agent"

AGENT_IMAGE_PATH_IN_CONTAINER = "/opt/Pywen"
UV_BIN_IN_CONTAINER = "/root/.local/bin/uv"
UV_SHARE_IN_CONTAINER = "/root/.local/share/uv"

HOST_AGENT_CACHE_DIRNAME = "pywen_agent_cache"
HOST_UV_BIN_DIRNAME = "uv_bin"
HOST_UV_SHARE_DIRNAME = "uv_share"
RESULTS_DIRNAME = "results"


class DockerOps:
    """ docker 操作的统一封装,增加错误处理机制 """
    def __init__(self):
        self.client: DockerClient = from_env()

    def image_exists(self, name: str) -> bool:
        try:
            self.client.images.get(name)
            return True
        except ImageNotFound:
            return False

    def pull_image(self, name: str) -> None:
        last_err = None
        for _ in range(3):
            try:
                self.client.images.pull(name)
                return
            except Exception as e:
                last_err = e
        raise RuntimeError(f"Failed to pull image {name}: {last_err}")

    def build_image(self, tag: str, dockerfile: Path, context: Path) -> None:
        try:
            stream = self.client.api.build(
                path=str(context),
                dockerfile=str(dockerfile.name),
                tag=tag,
                decode=True,
                rm=True
            )
            for chunk in stream:
                if "error" in chunk:
                    raise RuntimeError(chunk["error"])
        except APIError as e:
            raise RuntimeError(f"Docker build failed: {e}") from e

    def run_container(self, image: str, *, command: str = "/bin/bash", detach: bool = True,
                      tty: bool = False, stdin_open: bool = True, environment: dict | None = None,
                      volumes: dict | None = None, working_dir: str | None = None) -> Container:
        try:
            container = self.client.containers.run(
                image=image,
                command=command,
                detach=detach,
                tty=tty,
                stdin_open=stdin_open,
                environment=environment or {},
                volumes=volumes or {},
                working_dir=working_dir
            )
            return cast(Container, container)
        except Exception as e:
            raise RuntimeError(f"Failed to run container from {image}: {e}") from e

    def exec_sh(self, container: Container, shell_cmd: str, check: bool = True) -> str:
        """ 在容器内用 /bin/bash -lc 执行命令。统一解析 ExitCode 和输出，失败时抛错。 """
        try:
            res: ExecResult = container.exec_run(
                    cmd=["/bin/bash", "--noprofile", "--norc", "-lc", shell_cmd],
                    tty=False,
                    stdin=False,
            )
        except Exception as e:
            raise RuntimeError(f"Exec failed: {shell_cmd}\n{e}") from e

        code = getattr(res, "exit_code", None)
        out = getattr(res, "output", None)
        if code is None:
            code = res[0]
            out = res[1]
        text = out.decode("utf-8", "ignore") if isinstance(out, (bytes, bytearray)) else (out or "")

        if check and code != 0:
            raise RuntimeError(f"Command failed ({code}): {shell_cmd}\n{text}")
        return text

    def stop_and_remove(self, container: Container | None) -> None:
        if container is None:
            return
        with contextlib.suppress(Exception):
            container.stop(timeout=5)
        with contextlib.suppress(Exception):
            container.remove()

    def cp_from_container(self, container: Container, src_path: str, dst: Path) -> None:
        """ 将容器内路径内容复制到宿主目录。dst 若不存在会创建。 """
        dst.mkdir(parents=True, exist_ok=True)
        try:
            stream, _ = container.get_archive(src_path)
        except NotFound as e:
            raise RuntimeError(f"Path not found in container: {src_path}") from e
        import io as _io
        import tarfile
        bio = _io.BytesIO()
        for chunk in stream:
            bio.write(chunk)
        bio.seek(0)
        with tarfile.open(fileobj=bio, mode="r|*") as tar:
            tar.extractall(path=dst)

@dataclass
class BenchmarkConfig:
    valid_datasets: list[str]
    load_dataset: Callable[[str], Any]
    image_name: Callable[[str], str]
    problem_statement: Callable[[dict, Path], Any]
    working_dir: Callable[[str], str]
    evaluate_harness: Callable[..., list[str]]
    evaluate_harness_before: Callable[..., Any]
    evaluate_harness_after: Callable[..., Any]

def _write_problem_statement(instance_dir: Path, content: str) -> int:
    with open(instance_dir / "problem_statement.txt", "w", encoding="utf-8") as f:
        return f.write(content)

BENCHMARK_CONFIG: dict[str, BenchmarkConfig] = {
    "SWE-bench": BenchmarkConfig(
        valid_datasets=["SWE-bench", "SWE-bench_Lite", "SWE-bench_Verified"],
        load_dataset=lambda dataset_name: load_dataset(f"princeton-nlp/{dataset_name}", split="test"),
        image_name=lambda instance_id: f"swebench/sweb.eval.x86_64.{instance_id.lower()}:latest".replace("__", "_1776_"),
        problem_statement=lambda instance, instance_dir: _write_problem_statement(instance_dir, instance.get("problem_statement", "")),
        working_dir=lambda instance_id: "/testbed/",
        evaluate_harness=lambda dataset_name, task_results_dir, task_id, max_workers: [
            "swebench_venv/bin/python",
            "-m", "swebench.harness.run_evaluation",
            "--dataset_name", f"princeton-nlp/{dataset_name}",
            "--predictions_path", (task_results_dir / "predictions.json").absolute().as_posix(),
            "--max_workers", str(max_workers),
            "--run_id", task_id,
        ],
        evaluate_harness_before=lambda: None,
        evaluate_harness_after=lambda: None,
    ),
}

class BenchmarkEvaluation:
    def __init__(self, benchmark: str, working_dir: str, config_path: str, dataset_name: str = "SWE-bench_Lite",
        run_id: str = "pywen-agent",  max_workers: int = 4, instance_ids: list[str] | None = None,
        agent_name: str = "pywen", pattern: str | None = None, limit: int | None = None,
        force: bool = False):

        self.pattern = pattern
        self.limit   = limit
        self.skip_completed = not force  # 默认跳过已完成的，--force 时重跑所有
        self.ops = DockerOps()

        self.benchmark = benchmark
        self.config = BENCHMARK_CONFIG[benchmark]
        self.dataset_name = dataset_name
        self.dataset = self.config.load_dataset(self.dataset_name)

        eval_dir = Path(__file__).parent.resolve()
        self.working_dir = (eval_dir / working_dir).resolve()
        self.working_dir.mkdir(parents=True, exist_ok=True)

        self.config_src = self._resolve_config_path(Path(config_path))
        self.config_dest = self.working_dir / f"pywen_config{self.config_src.suffix}"
        shutil.copy(self.config_src, self.config_dest)

        self.results_dir = (eval_dir / RESULTS_DIRNAME).resolve()
        self.results_dir.mkdir(parents=True, exist_ok=True)

        self.task_id = f"{benchmark}_{dataset_name}_{run_id}".replace("/", "_")
        self.task_results_dir = self.results_dir / self.task_id
        self.task_results_dir.mkdir(parents=True, exist_ok=True)

        if instance_ids is not None:
            self.instance_ids = instance_ids
        else:
            ids = [item["instance_id"] for item in self.dataset]
            if hasattr(self, "pattern") and self.pattern:
                import re
                regex = re.compile(self.pattern)
                ids = [iid for iid in ids if regex.search(iid)]
            if hasattr(self, "limit") and self.limit:
                ids = ids[: self.limit]

            self.instance_ids = ids

        self.max_workers = max_workers
        self.agent_name = agent_name

        self.host_agent_cache = self.working_dir / HOST_AGENT_CACHE_DIRNAME
        self.host_agent_cache.mkdir(parents=True, exist_ok=True)

    def _resolve_config_path(self, user_path: Path) -> Path:
        if user_path and user_path.exists():
            return user_path
    
        home_default = Path.home() / ".pywen" / "pywen_config.yaml"
        if home_default.exists():
            return home_default
    
        repo_root = Path(__file__).parents[2].resolve()
        example = repo_root / "pywen_config.example.yaml"
        if example.exists():
            return example
    
        raise FileNotFoundError(
            "No YAML config found. Expected one of: "
            f"{user_path} (from --config) OR {home_default} OR {example}"
        )

    def ensure_agent_image_and_cache(self):
        repo_root = Path(__file__).parents[2].resolve()
        dockerfile = repo_root / AGENT_IMAGE_DOCKERFILE
        if not dockerfile.exists():
            raise FileNotFoundError(f"Missing {AGENT_IMAGE_DOCKERFILE} at repo root: {dockerfile}")

        if not self.ops.image_exists(AGENT_IMAGE):
            print(f"Building agent image {AGENT_IMAGE} ...")
            self.ops.build_image(tag=AGENT_IMAGE, dockerfile=dockerfile, context=repo_root)
        else:
            print(f"Found agent image {AGENT_IMAGE}")

        target_pywen = self.host_agent_cache / "Pywen"
        target_uv_bin = self.host_agent_cache / HOST_UV_BIN_DIRNAME
        target_uv_share = self.host_agent_cache / HOST_UV_SHARE_DIRNAME

        need_export = not (target_pywen.exists() and (target_uv_bin / "uv").exists() and (target_uv_share / "uv").exists())
        if need_export:
            print("Exporting agent cache from image ...")
            container = None
            try:
                container = self.ops.run_container(AGENT_IMAGE, command="sleep 60")

                shutil.rmtree(target_pywen, ignore_errors=True)
                shutil.rmtree(target_uv_bin, ignore_errors=True)
                shutil.rmtree(target_uv_share, ignore_errors=True)

                # /opt/Pywen -> host
                self.ops.cp_from_container(container, AGENT_IMAGE_PATH_IN_CONTAINER, self.host_agent_cache)

                # /root/.local/bin/uv -> host/uv_bin/uv
                target_uv_bin.mkdir(parents=True, exist_ok=True)
                self.ops.cp_from_container(container, UV_BIN_IN_CONTAINER, target_uv_bin)

                # /root/.local/share/uv -> host/uv_share/uv
                target_uv_share.mkdir(parents=True, exist_ok=True)
                self.ops.cp_from_container(container, UV_SHARE_IN_CONTAINER, target_uv_share)

                resolved = self.ops.exec_sh(
                    container, "readlink -f /opt/Pywen/.venv/bin/python || true", check=False
                ).strip()
                print(f"venv python resolves to: {resolved or 'EMPTY'}")
            finally:
                self.ops.stop_and_remove(container)
        else:
            print("Found existing host cache of pywen-agent. Skipping export.")

    
    def pull_images(self):
        names = {self.config.image_name(iid) for iid in self.instance_ids}
        print(f"Preparing {len(names)} SWE images ...")
        for name in tqdm(sorted(names), desc="Pull SWE images"):
            if not self.ops.image_exists(name):
                self.ops.pull_image(name)

    def _is_instance_completed(self, instance_id: str) -> bool:
        """检查实例是否已完成（存在 patch 或 run.log）"""
        instance_res_dir = self.task_results_dir / instance_id
        patch_path = instance_res_dir / f"{instance_id}.patch"
        log_path = instance_res_dir / "run.log"
        
        # 如果 patch 文件存在且非空，认为已完成
        if patch_path.exists() and patch_path.stat().st_size > 0:
            return True
        
        # 如果 log 文件存在且非空，也认为已完成（即使没有生成 patch）
        return bool(log_path.exists() and log_path.stat().st_size > 0)

    def run_one_instance(self, instance_id: str):
        # Skip if already completed
        if self.skip_completed and self._is_instance_completed(instance_id):
            print(f"⏭️  Skipping {instance_id} (already completed)")
            return
        
        ops = DockerOps()
        instance = next((i for i in self.dataset if i["instance_id"] == instance_id), None)
        if not instance:
            print(f"Instance {instance_id} not found")
            return
    
        image_name = self.config.image_name(instance_id)
        if not ops.image_exists(image_name):
            print(f"Pulling {image_name} ...")
            ops.pull_image(image_name)
    
        instance_res_dir = self.task_results_dir / instance_id
        instance_res_dir.mkdir(parents=True, exist_ok=True)
        self.config.problem_statement(instance, instance_res_dir)
    
        host_pywen = (self.host_agent_cache / "Pywen").resolve()
        host_uv_bin = (self.host_agent_cache / HOST_UV_BIN_DIRNAME).resolve()
        host_uv_share = (self.host_agent_cache / HOST_UV_SHARE_DIRNAME).resolve()
    
        volumes = {
            str(instance_res_dir): {"bind": "/results", "mode": "rw"},
            str(host_pywen): {"bind": AGENT_IMAGE_PATH_IN_CONTAINER, "mode": "ro"},
            str(host_uv_bin): {"bind": "/root/.local/bin", "mode": "ro"},
            str(host_uv_share): {"bind": "/root/.local/share", "mode": "ro"},
        }
        environment = {
            "PATH": "/root/.local/bin:" + os.environ.get("PATH", ""),
        }
    
        container = None
        try:
            container = ops.run_container(
                image=image_name,
                command="/bin/bash",
                environment=environment,
                volumes=volumes,
                tty=True,
                stdin_open=True,
            )
    
            verify = ops.exec_sh(
                container,
                f'[ -x "{AGENT_IMAGE_PATH_IN_CONTAINER}/.venv/bin/pywen" ] && echo OK || echo MISSING',
                check=False,
            )
            if "MISSING" in verify:
                ops.exec_sh(container, f"ls -l /opt && ls -l {AGENT_IMAGE_PATH_IN_CONTAINER}", check=False)
    
            # 读取问题并保存一份备查（可选）
            problem_stmt_path = instance_res_dir / "problem_statement.txt"
            problem_stmt = problem_stmt_path.read_text(encoding="utf-8") if problem_stmt_path.exists() else ""
            prompt = (
                "You are tasked with resolving a GitHub issue in this repository.\n"
                "The repository is checked out at /testbed.\n\n"
                "IMPORTANT: You must analyze the issue, locate the relevant code files, make the necessary changes to fix the bug, "
                "and verify your solution. Do not just acknowledge the task - you must actually implement the fix.\n\n"
                f"Issue Description:\n{problem_stmt}\n\n"
                "Please start by exploring the codebase to understand the issue, then implement the fix.\n"
            )
            (instance_res_dir / "problem_statement_for_pywen.txt").write_text(prompt, encoding="utf-8")
    
            instance_cfg = instance_res_dir / self.config_dest.name
            shutil.copy(self.config_dest, instance_cfg)
    
            quoted_prompt = shlex.quote(prompt)
            # 在启动 pywen 前激活 conda testbed 环境，确保 pywen 及其子进程（bash_tool）都能使用正确的 Python 环境
            run_cmd = f"""
cd /testbed && \
source /opt/miniconda3/etc/profile.d/conda.sh && \
conda activate testbed && \
{AGENT_IMAGE_PATH_IN_CONTAINER}/.venv/bin/pywen \
--config /results/{self.config_dest.name} \
--permission-mode yolo \
--agent {shlex.quote(self.agent_name)} \
-p {quoted_prompt}
"""
            output = ops.exec_sh(container, run_cmd, check=False)
            (instance_res_dir / "run.log").write_text(output, encoding="utf-8")
    
            patch_out = ops.exec_sh(container, "cd /testbed && git diff", check=False)
            if patch_out.strip():
                (instance_res_dir / f"{instance_id}.patch").write_text(patch_out, encoding="utf-8")
                print(f"✅ Patch saved: {instance_id}")
            else:
                print(f"⚠️  No patch generated for {instance_id}")
    
        except Exception as e:
            print(f"Error running {instance_id}: {e}")
            traceback.print_exc()
        finally:
            ops.stop_and_remove(container)


    def run_all(self):
        self.ensure_agent_image_and_cache()
        self.pull_images()

        # Check completion status
        if self.skip_completed:
            completed = [iid for iid in self.instance_ids if self._is_instance_completed(iid)]
            remaining = [iid for iid in self.instance_ids if not self._is_instance_completed(iid)]
            print(f"📊 Status: {len(completed)} completed, {len(remaining)} remaining (total: {len(self.instance_ids)})")
            if len(remaining) == 0:
                print("✅ All instances already completed!")
                return
        else:
            print(f"Running {len(self.instance_ids)} instances with {self.max_workers} workers")

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(self.run_one_instance, iid): iid for iid in self.instance_ids}
            for fut in tqdm(as_completed(futures), total=len(futures)):
                iid = futures[fut]
                try:
                    fut.result()
                except Exception as e:
                    print(f"Instance {iid} crashed: {e}")

    def collect_predictions(self, instance_ids: list[str] | None = None) -> Path:
        """
        收集所有生成的 patch 文件，汇总成 predictions.json。
        
        Args:
            instance_ids: 要收集的实例 ID 列表，None 则收集所有数据集中的实例
            
        Returns:
            predictions.json 的路径
        """
        import json
        
        if instance_ids is None:
            instance_ids = [item["instance_id"] for item in self.dataset]
        
        predictions = []
        found_count = 0
        missing_count = 0
        
        for instance_id in instance_ids:
            patch_path = self.task_results_dir / instance_id / f"{instance_id}.patch"
            
            if not patch_path.exists():
                missing_count += 1
                continue
            
            patch_content = patch_path.read_text(encoding="utf-8")
            if not patch_content.strip():
                missing_count += 1
                continue
                
            predictions.append({
                "instance_id": instance_id,
                "model_name_or_path": "pywen-agent",
                "model_patch": patch_content,
            })
            found_count += 1
        
        predictions_path = self.task_results_dir / "predictions.json"
        with open(predictions_path, "w", encoding="utf-8") as f:
            json.dump(predictions, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Collected {found_count} patches into {predictions_path}")
        if missing_count > 0:
            print(f"⚠️  {missing_count} instances have no patch")
        
        return predictions_path

def main():
    parser = argparse.ArgumentParser(
        description="Run Pywen on SWE-bench instances using official Docker images",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--instance-ids", nargs="+", help="Specific instance IDs to run (e.g., django__django-11001). If not specified, runs all instances in dataset.")
    parser.add_argument("--dataset", default="SWE-bench_Lite", choices=["SWE-bench", "SWE-bench_Lite", "SWE-bench_Verified"], help="Dataset to use")
    parser.add_argument("--max-workers", type=int, default=1, help="Number of parallel workers")
    parser.add_argument("--config", type=str, default=str(Path.home() / ".pywen" / "pywen_config.yaml"), help="Pywen config file path")
    parser.add_argument("--agent", default="pywen", choices=["pywen", "codex", "claude"], help="Agent to use")
    parser.add_argument("--limit", type=int, default=None, help="Only run first N instances after filtering")
    parser.add_argument("--pattern", type=str, default=None, help="Regex to filter instance_id")
    parser.add_argument("--mode", type=str, default="expr", choices=["expr", "collect", "e2e"],
                        help="Mode: expr=only generate patches, collect=only collect patches to predictions.json, e2e=both")
    parser.add_argument("--run-id", type=str, default="pywen-agent", help="Run ID for this evaluation")
    parser.add_argument("--force", action="store_true", help="Force re-run all instances, ignoring existing results")

    args = parser.parse_args()

    # collect 模式不需要确认
    if args.mode != "collect" and not args.instance_ids:
        print("⚠️  Warning: No --instance-ids specified. Will run ALL instances in dataset.")
        print(f"   Dataset: {args.dataset}")
        print(f"   Using config: {args.config} (YAML)")
        resp = input("   Continue? [y/N]: ")
        if resp.lower() != "y":
            print("Aborted.")
            return

    evaluator = BenchmarkEvaluation(
        benchmark="SWE-bench",
        working_dir="pywen_workspace",
        config_path=args.config,
        dataset_name=args.dataset,
        max_workers=args.max_workers,
        instance_ids=args.instance_ids,
        agent_name=args.agent,
        pattern=args.pattern,
        limit=args.limit,
        force=args.force,
    )
    
    # 根据模式执行
    if args.mode in ("expr", "e2e"):
        evaluator.run_all()
    
    if args.mode in ("collect", "e2e"):
        evaluator.collect_predictions(args.instance_ids)

if __name__ == "__main__":
    main()
