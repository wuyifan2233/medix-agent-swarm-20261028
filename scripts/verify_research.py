"""Run isolated ResearchAgent regressions, including visible acceptance failures."""
import argparse
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    from loguru import logger
    logger.remove()
    with TemporaryDirectory(prefix="medix-research-tests-") as directory:
        os.environ.update(MEDIX_DATA_DIR=directory,
                          MEDIX_DATABASE_URL="sqlite:///" + str(Path(directory) / "app.db"),
                          MEDIX_IDENTITY_NAMESPACE="research-regression")
        suite = unittest.defaultTestLoader.loadTestsFromNames([
            "research.test_web_search", "research.test_research_agent", "research.test_research_contracts", "research.test_deepseek_search"])
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        failures = [{"test": test.id(), "trace": trace} for test, trace in result.failures]
        errors = [{"test": test.id(), "trace": trace} for test, trace in result.errors]
        report = {"total": result.testsRun,
                  "passed": result.testsRun - len(failures) - len(errors) - len(result.skipped),
                  "failures": failures, "errors": errors, "skipped": len(result.skipped),
                  "isolated_database": True, "external_apis": "mocked"}
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in report.items() if k not in {"failures", "errors"}}, ensure_ascii=False))
        return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
