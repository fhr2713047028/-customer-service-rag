"""Locust 结果分析：从 --csv-full-history 输出提取各端点 P50/P95/P99 与计数。

用法：
    PYTHONIOENCODING=utf-8 .venv\\Scripts\\python -m scripts.analyze_locust --prefix results/business
"""
import argparse
import csv
import json
from pathlib import Path


def analyze(prefix: str) -> dict:
    stats_path = Path(f"{prefix}_stats.csv")
    hist_path = Path(f"{prefix}_stats_history.csv")

    # 每个端点最后一行的累计百分位（history CSV 含 50%/95%/99% 列）
    last_rows: dict[str, dict] = {}
    with hist_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            last_rows[row["Name"]] = row

    endpoints = []
    total_requests = 0
    total_failures = 0
    with stats_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["Name"]
            if name == "Aggregated":
                total_requests = int(row["Request Count"])
                total_failures = int(row["Failure Count"])
                continue
            hist = last_rows.get(name, {})
            p50 = hist.get("50%") or row.get("Median Response Time") or "0"
            p95 = hist.get("95%") or row.get("95%") or "0"
            p99 = hist.get("99%") or "0"
            endpoints.append(
                {
                    "name": name,
                    "requests": int(row["Request Count"]),
                    "failures": int(row["Failure Count"]),
                    "p50_ms": round(float(p50)),
                    "p95_ms": round(float(p95)),
                    "p99_ms": round(float(p99)),
                    "avg_ms": round(float(row["Average Response Time"])),
                    "rps": round(float(row["Requests/s"]), 2),
                }
            )

    total_rps = round(total_requests / _duration_seconds(hist_path), 2)
    summary = {"total": {"requests": total_requests, "failures": total_failures, "rps": total_rps},
               "endpoints": endpoints}
    out = Path(f"{prefix}_summary.json")
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def _duration_seconds(hist_path: Path) -> float:
    """从 history CSV 的时间戳列估算持续时间。"""
    first = last = None
    with hist_path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ts = row.get("Timestamp") or ""
            if not first:
                first = ts
            last = ts
    try:
        from datetime import datetime

        a = datetime.fromisoformat(first)
        b = datetime.fromisoformat(last)
        return max((b - a).total_seconds(), 1.0)
    except Exception:
        return 120.0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", required=True, help="CSV 文件前缀，如 results/business")
    args = parser.parse_args()
    result = analyze(args.prefix)
    print(json.dumps(result, ensure_ascii=False, indent=2))
