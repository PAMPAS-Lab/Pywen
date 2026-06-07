import argparse
import json
import sys
from pathlib import Path
from typing import Optional

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from evaluation.bfcl.adapter import create_bfcl_adapter  # noqa: E402
from evaluation.bfcl.dataset import BFCLDataset  # noqa: E402
from evaluation.bfcl.evaluator import BFCLEvaluator  # noqa: E402


def create_llm_client(config_path: Optional[str] = None):
    from pywen.config.manager import ConfigManager
    from pywen.llm.llm_client import LLMClient

    cfg_mgr = ConfigManager(config_path) if config_path else ConfigManager()

    class Args:
        def __init__(self):
            self.model = None
            self.api_key = None
            self.base_url = None
            self.permission_mode = "yolo"

    args = Args()
    config = cfg_mgr.resolve_effective_config(args)
    llm_client = LLMClient(config.active_model)
    model = config.active_model.model

    return llm_client, model


def run_bfcl_evaluation(
    category: str = "simple_python",
    max_samples: int = 5,
    bfcl_data_dir: str | Path | None = None,
    config_path: Optional[str] = None,
    output_dir: str | Path | None = None
):
    print("\n" + "="*60)
    print("🚀 Pywen BFCL评估")
    print("="*60)

    print("\n🤖 创建LLM客户端...")
    try:
        llm_client, model = create_llm_client(config_path)
        if not model:
            print("❌ 未配置模型")
            return None
        print(f"   LLM模型: {model}")
    except Exception as e:
        print(f"❌ 创建LLM客户端失败: {e}")
        return None

    print("\n🔧 创建BFCL适配器...")
    bfcl_agent = create_bfcl_adapter(llm_client, model)
    print(f"   适配器名称: {bfcl_agent.name}")

    print("\n📚 加载BFCL数据集 (自动下载)...")
    print(f"   类别: {category}")
    print(f"   样本数: {max_samples if max_samples > 0 else '全部'}")

    dataset = BFCLDataset(bfcl_data_dir=bfcl_data_dir, category=category, auto_download=True)

    if len(dataset) == 0:
        print(f"❌ 数据集为空，请检查类别 '{category}' 是否正确")
        return None

    print("\n📊 创建BFCL评估器...")
    evaluator = BFCLEvaluator(dataset=dataset, category=category, evaluation_mode="ast")

    print("\n🔄 开始评估...")
    results = evaluator.evaluate(agent=bfcl_agent, max_samples=max_samples if max_samples > 0 else None)

    print("\n" + "="*60)
    print("📊 评估结果")
    print("="*60)
    print(f"总体准确率: {results['overall_accuracy']:.2%}")
    print(f"正确样本数: {results['correct_samples']}/{results['total_samples']}")

    if results.get('category_metrics'):
        print("\n分类准确率:")
        for cat, metrics in results['category_metrics'].items():
            print(f"  {cat}: {metrics['accuracy']:.2%} ({metrics['correct']}/{metrics['total']})")

    if output_dir:
        output_path = Path(output_dir)
    else:
        output_path = project_root / "evaluation" / "bfcl" / "results"

    output_path.mkdir(parents=True, exist_ok=True)
    result_file = output_path / f"BFCL_v4_{category}_result.json"
    evaluator.export_to_bfcl_format(results, result_file)

    detail_file = output_path / f"bfcl_{category}_detailed.json"
    with open(detail_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n📄 详细结果已保存: {detail_file}")
    return results


def main():
    parser = argparse.ArgumentParser(description="运行BFCL评估", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--category", type=str, default="simple_python", choices=BFCLDataset.SUPPORTED_CATEGORIES, help="评估类别")
    parser.add_argument("--samples", type=int, default=5, help="评估样本数 (0表示全部)")
    parser.add_argument("--data-dir", type=str, default=None, help="BFCL数据目录路径")
    parser.add_argument("--config", type=str, default=None, help="Pywen配置文件路径")
    parser.add_argument("--output-dir", type=str, default=None, help="输出目录路径")
    args = parser.parse_args()

    results = run_bfcl_evaluation(
        category=args.category,
        max_samples=args.samples,
        bfcl_data_dir=args.data_dir,
        config_path=args.config,
        output_dir=args.output_dir
    )

    if results:
        print("\n✅ 评估完成!")
    else:
        print("\n❌ 评估失败!")
        sys.exit(1)


if __name__ == "__main__":
    main()

