import ast
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from .dataset import BFCLDataset, BFCLSample


class BFCLAgent(Protocol):
    name: str
    def generate(self, prompt: str, functions: List[Dict[str, Any]]) -> str: ...


@dataclass
class EvaluationResult:
    sample_id: str
    category: str
    correct: bool
    model_output: str
    expected: List[str]
    error: Optional[str] = None
    latency_ms: float = 0.0


@dataclass
class EvaluationReport:
    total_samples: int = 0
    correct_samples: int = 0
    overall_accuracy: float = 0.0
    category_metrics: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    results: List[EvaluationResult] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class BFCLEvaluator:
    def __init__(self, dataset: BFCLDataset, category: str = "simple_python", evaluation_mode: str = "ast"):
        self.dataset = dataset
        self.category = category
        self.evaluation_mode = evaluation_mode

    def evaluate(self, agent: BFCLAgent, max_samples: Optional[int] = None) -> Dict[str, Any]:
        report = EvaluationReport()
        samples = list(self.dataset)
        if max_samples and max_samples > 0:
            samples = samples[:max_samples]
        report.total_samples = len(samples)

        for sample in samples:
            try:
                result = self._evaluate_sample(agent, sample)
                report.results.append(result)
                if result.correct:
                    report.correct_samples += 1
            except Exception as e:
                error_result = EvaluationResult(
                    sample_id=sample.id, category=sample.category, correct=False,
                    model_output="", expected=sample.ground_truth, error=str(e)
                )
                report.results.append(error_result)

        if report.total_samples > 0:
            report.overall_accuracy = report.correct_samples / report.total_samples
        report.category_metrics = self._compute_category_metrics(report.results)
        return self._report_to_dict(report)

    def _evaluate_sample(self, agent: BFCLAgent, sample: BFCLSample) -> EvaluationResult:
        start_time = time.time()
        model_output = agent.generate(prompt=sample.question, functions=sample.functions)
        latency_ms = (time.time() - start_time) * 1000
        correct = self._check_correctness(model_output, sample.ground_truth)
        return EvaluationResult(
            sample_id=sample.id, category=sample.category, correct=correct,
            model_output=model_output, expected=sample.ground_truth, latency_ms=latency_ms
        )

    def _check_correctness(self, model_output: str, ground_truth: List[str]) -> bool:
        if self.evaluation_mode == "ast":
            return self._ast_match(model_output, ground_truth)
        return self._exact_match(model_output, ground_truth)

    def _ast_match(self, output: str, expected: List[Any]) -> bool:
        try:
            output_clean = self._extract_function_call(output)
            output_parsed = self._parse_function_call(output_clean)
            if not output_parsed:
                return False

            for exp in expected:
                if isinstance(exp, dict):
                    if self._match_bfcl_format(output_parsed, exp):
                        return True
                elif isinstance(exp, str):
                    exp_clean = self._extract_function_call(exp)
                    if self._compare_ast(output_clean, exp_clean):
                        return True
            return False
        except Exception:
            return False

    def _parse_function_call(self, call_str: str) -> Optional[Dict[str, Any]]:
        try:
            # 支持带点的函数名如 math.factorial
            match = re.match(r'([\w.]+)\s*\((.*)\)$', call_str.strip(), re.DOTALL)
            if not match:
                return None
            func_name = match.group(1)
            args_str = match.group(2).strip()
            if not args_str:
                return {"name": func_name, "arguments": {}}
            args = {}
            tree = ast.parse(f"f({args_str})", mode='eval')
            call_node = tree.body
            if isinstance(call_node, ast.Call):
                for kw in call_node.keywords:
                    if kw.arg:
                        args[kw.arg] = ast.literal_eval(ast.unparse(kw.value))
            return {"name": func_name, "arguments": args}
        except Exception:
            return None

    def _match_bfcl_format(self, parsed: Dict[str, Any], expected: Dict[str, Any]) -> bool:
        for func_name, params in expected.items():
            if parsed.get("name") != func_name:
                continue
            args = parsed.get("arguments", {})
            all_match = True
            for param_name, possible_values in params.items():
                if param_name not in args:
                    if possible_values and "" not in possible_values:
                        all_match = False
                        break
                    continue
                actual_value = args[param_name]
                if isinstance(possible_values, list):
                    if actual_value not in possible_values:
                        all_match = False
                        break
                elif actual_value != possible_values:
                    all_match = False
                    break
            if all_match:
                return True
        return False

    def _extract_function_call(self, text: str) -> str:
        text = text.strip()
        code_match = re.search(r'```(?:python)?\s*(.*?)\s*```', text, re.DOTALL)
        if code_match:
            text = code_match.group(1).strip()
        json_match = re.search(r'\{.*"name".*"arguments".*\}', text, re.DOTALL)
        if json_match:
            try:
                func_json = json.loads(json_match.group())
                name = func_json.get("name", "")
                args = func_json.get("arguments", {})
                if isinstance(args, str):
                    args = json.loads(args)
                args_str = ", ".join(f"{k}={repr(v)}" for k, v in args.items())
                return f"{name}({args_str})"
            except Exception:
                pass
        for prefix in ["Output:", "Answer:", "Result:"]:
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
        return text

    def _compare_ast(self, output: str, expected: str) -> bool:
        try:
            out_ast = ast.parse(output, mode='eval')
            exp_ast = ast.parse(expected, mode='eval')
            return ast.dump(out_ast) == ast.dump(exp_ast)
        except Exception:
            return output.strip() == expected.strip()

    def _exact_match(self, output: str, expected: List[str]) -> bool:
        output_clean = output.strip().lower()
        return any(output_clean == exp.strip().lower() for exp in expected)

    def _compute_category_metrics(self, results: List[EvaluationResult]) -> Dict[str, Dict[str, Any]]:
        metrics: Dict[str, Dict[str, Any]] = {}
        for result in results:
            cat = result.category
            if cat not in metrics:
                metrics[cat] = {"total": 0, "correct": 0, "accuracy": 0.0}
            metrics[cat]["total"] += 1
            if result.correct:
                metrics[cat]["correct"] += 1
        for cat in metrics:
            if metrics[cat]["total"] > 0:
                metrics[cat]["accuracy"] = metrics[cat]["correct"] / metrics[cat]["total"]
        return metrics

    def _report_to_dict(self, report: EvaluationReport) -> Dict[str, Any]:
        return {
            "total_samples": report.total_samples,
            "correct_samples": report.correct_samples,
            "overall_accuracy": report.overall_accuracy,
            "category_metrics": report.category_metrics,
            "timestamp": report.timestamp,
            "results": [
                {"sample_id": r.sample_id, "category": r.category, "correct": r.correct,
                 "model_output": r.model_output, "expected": r.expected, "error": r.error, "latency_ms": r.latency_ms}
                for r in report.results
            ]
        }

    def export_to_bfcl_format(self, results: Dict[str, Any], output_path: Path) -> None:
        bfcl_results = []
        for result in results.get("results", []):
            bfcl_results.append({"id": result["sample_id"], "result": result["model_output"], "correct": result["correct"]})
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(bfcl_results, f, ensure_ascii=False, indent=2)
        print(f"📄 BFCL格式结果已保存: {output_path}")
