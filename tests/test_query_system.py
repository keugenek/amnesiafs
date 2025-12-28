#!/usr/bin/env python3
"""
Comprehensive Query System Tests

Tests precision, performance, and usefulness of the CognitiveFS query system
using real data from memory/ and profiles/ directories.

Run with: python tests/test_query_system.py Z:
"""

import os
import sys
import time
import json
import subprocess
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from pathlib import Path


@dataclass
class QueryTest:
    """Defines a single query test case."""
    name: str
    query: str
    expected_keywords: List[str]  # Keywords that SHOULD appear in response
    expected_files: List[str] = field(default_factory=list)  # Files that should be referenced
    negative_keywords: List[str] = field(default_factory=list)  # Keywords that should NOT appear
    category: str = "general"  # precision, performance, usefulness


@dataclass
class TestResult:
    """Result of a single test."""
    test: QueryTest
    passed: bool
    response: str
    query_time: float
    poll_time: float
    keywords_found: List[str]
    keywords_missing: List[str]
    files_found: List[str]
    error: Optional[str] = None


# ============== TEST CASES ==============

PRECISION_TESTS = [
    QueryTest(
        name="geeky_inventor_channel",
        query="what is the geeky inventor youtube channel about",
        expected_keywords=["youtube", "channel", "tech", "hardware", "AI", "budget"],
        expected_files=["geekyinventor"],
        category="precision"
    ),
    QueryTest(
        name="voxelmosaic_identity",
        query="who is voxelmosaic and what do they do",
        expected_keywords=["voxelmosaic", "lidia", "production", "film"],
        expected_files=["voxelmosaic", "profile"],
        category="precision"
    ),
    QueryTest(
        name="viral_patterns",
        query="what are the viral video patterns",
        expected_keywords=["viral", "pattern", "video", "engagement"],
        expected_files=["viral-patterns"],
        category="precision"
    ),
    QueryTest(
        name="quality_gates",
        query="what quality gates are used for content",
        expected_keywords=["quality", "gate", "check", "standard"],
        expected_files=["quality-gates", "quality-standards"],
        category="precision"
    ),
    QueryTest(
        name="automation_tools",
        query="what automation tools are recommended",
        expected_keywords=["automation", "tool", "descript", "workflow"],
        expected_files=["automation-recommendations"],
        category="precision"
    ),
    QueryTest(
        name="audience_definition",
        query="who is the target audience",
        expected_keywords=["audience", "target", "viewer", "follower"],
        expected_files=["audience"],
        category="precision"
    ),
    QueryTest(
        name="content_mistakes",
        query="what are common content mistakes to avoid",
        expected_keywords=["mistake", "avoid", "error", "wrong"],
        expected_files=["common-mistakes"],
        category="precision"
    ),
    QueryTest(
        name="hivenode_product",
        query="what is the hivenode product plan",
        expected_keywords=["hivenode", "product", "plan", "feature"],
        expected_files=["hivenode-product-plan"],
        category="precision"
    ),
]

USEFULNESS_TESTS = [
    QueryTest(
        name="actionable_advice",
        query="how should I improve my video production workflow",
        expected_keywords=["workflow", "improve", "time", "efficiency"],
        category="usefulness"
    ),
    QueryTest(
        name="strategic_guidance",
        query="what content strategy should I follow for linkedin",
        expected_keywords=["strategy", "content", "linkedin", "post"],
        expected_files=["strategy", "linkedin"],
        category="usefulness"
    ),
    QueryTest(
        name="specific_metrics",
        query="what engagement metrics should I track",
        expected_keywords=["engagement", "metric", "view", "like"],
        expected_files=["engagement", "metrics"],
        category="usefulness"
    ),
    QueryTest(
        name="problem_solving",
        query="why did the zoya post fail and what can be learned",
        expected_keywords=["zoya", "fail", "learn", "post"],
        expected_files=["zoya", "post-mortem"],
        category="usefulness"
    ),
]

PERFORMANCE_TESTS = [
    QueryTest(
        name="simple_query",
        query="what files are in this system",
        expected_keywords=["file"],
        category="performance"
    ),
    QueryTest(
        name="medium_query",
        query="summarize the main topics covered in the profiles",
        expected_keywords=["profile", "topic"],
        category="performance"
    ),
    QueryTest(
        name="complex_query",
        query="analyze the relationship between audience targeting and content strategy across all documents",
        expected_keywords=["audience", "content", "strategy"],
        category="performance"
    ),
]

ALL_TESTS = PRECISION_TESTS + USEFULNESS_TESTS + PERFORMANCE_TESTS


class QueryTester:
    """Runs query tests against mounted CognitiveFS."""

    def __init__(self, mount_point: str):
        self.mount_point = Path(mount_point)
        self.results: List[TestResult] = []

    def read_file(self, path: str) -> str:
        """Read a file from the filesystem."""
        full_path = self.mount_point / path.lstrip("/\\")
        try:
            return full_path.read_text(encoding='utf-8')
        except Exception as e:
            return f"ERROR: {e}"

    def submit_query(self, query: str) -> Tuple[str, float]:
        """Submit a query and get the query ID."""
        query_path = query.replace(" ", "_")
        start = time.time()
        response = self.read_file(f".ai/query/{query_path}")
        elapsed = time.time() - start
        return response, elapsed

    def poll_result(self, query_id: str, max_wait: float = 60.0) -> Tuple[str, float]:
        """Poll for query result until complete or timeout."""
        start = time.time()
        while time.time() - start < max_wait:
            response = self.read_file(f".ai/query/results/{query_id}")
            if "still processing" not in response.lower():
                return response, time.time() - start
            time.sleep(1.0)
        return f"TIMEOUT after {max_wait}s", time.time() - start

    def run_test(self, test: QueryTest) -> TestResult:
        """Run a single test case."""
        print(f"  Running: {test.name}...", end=" ", flush=True)

        try:
            # Submit query
            submit_response, query_time = self.submit_query(test.query)

            # Extract query ID
            query_id = None
            for line in submit_response.split("\n"):
                if "Query queued with ID:" in line:
                    query_id = line.split(":")[-1].strip()
                    break

            if not query_id:
                # Might be direct response (disabled LLM)
                response = submit_response
                poll_time = 0.0
            else:
                # Poll for result
                response, poll_time = self.poll_result(query_id)

            # Check keywords
            response_lower = response.lower()
            keywords_found = [kw for kw in test.expected_keywords
                           if kw.lower() in response_lower]
            keywords_missing = [kw for kw in test.expected_keywords
                              if kw.lower() not in response_lower]

            # Check files
            files_found = [f for f in test.expected_files
                         if f.lower() in response_lower]

            # Determine pass/fail
            # Pass if at least 50% of expected keywords found
            keyword_ratio = len(keywords_found) / len(test.expected_keywords) if test.expected_keywords else 1.0
            passed = keyword_ratio >= 0.5 and "error" not in response_lower[:100]

            result = TestResult(
                test=test,
                passed=passed,
                response=response[:500],  # Truncate for display
                query_time=query_time,
                poll_time=poll_time,
                keywords_found=keywords_found,
                keywords_missing=keywords_missing,
                files_found=files_found
            )

            status = "[OK]" if passed else "[FAIL]"
            print(f"{status} ({query_time + poll_time:.1f}s)")

        except Exception as e:
            result = TestResult(
                test=test,
                passed=False,
                response="",
                query_time=0,
                poll_time=0,
                keywords_found=[],
                keywords_missing=test.expected_keywords,
                files_found=[],
                error=str(e)
            )
            print(f"[ERROR] {e}")

        self.results.append(result)
        return result

    def run_all_tests(self) -> Dict:
        """Run all test cases."""
        print("\n" + "="*60)
        print("CognitiveFS Query System Test Suite")
        print("="*60)

        # Check filesystem is mounted
        if not (self.mount_point / ".ai").exists():
            print(f"ERROR: Filesystem not mounted at {self.mount_point}")
            return {"error": "not mounted"}

        print(f"\nMount point: {self.mount_point}")
        print(f"Total tests: {len(ALL_TESTS)}")

        # Run by category
        for category in ["precision", "usefulness", "performance"]:
            tests = [t for t in ALL_TESTS if t.category == category]
            if tests:
                print(f"\n--- {category.upper()} TESTS ({len(tests)}) ---")
                for test in tests:
                    self.run_test(test)

        return self.generate_report()

    def generate_report(self) -> Dict:
        """Generate test report."""
        print("\n" + "="*60)
        print("TEST RESULTS SUMMARY")
        print("="*60)

        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed

        # By category
        by_category = {}
        for r in self.results:
            cat = r.test.category
            if cat not in by_category:
                by_category[cat] = {"passed": 0, "failed": 0, "total_time": 0}
            if r.passed:
                by_category[cat]["passed"] += 1
            else:
                by_category[cat]["failed"] += 1
            by_category[cat]["total_time"] += r.query_time + r.poll_time

        print(f"\nOverall: {passed}/{total} passed ({100*passed/total:.0f}%)")

        for cat, stats in by_category.items():
            cat_total = stats["passed"] + stats["failed"]
            cat_pct = 100 * stats["passed"] / cat_total if cat_total > 0 else 0
            avg_time = stats["total_time"] / cat_total if cat_total > 0 else 0
            print(f"  {cat}: {stats['passed']}/{cat_total} ({cat_pct:.0f}%) - avg {avg_time:.1f}s")

        # Failed tests details
        failed_tests = [r for r in self.results if not r.passed]
        if failed_tests:
            print(f"\nFailed Tests ({len(failed_tests)}):")
            for r in failed_tests:
                print(f"  - {r.test.name}: missing keywords {r.keywords_missing}")
                if r.error:
                    print(f"    Error: {r.error}")

        # Performance stats
        times = [r.query_time + r.poll_time for r in self.results]
        if times:
            print(f"\nPerformance:")
            print(f"  Min time: {min(times):.1f}s")
            print(f"  Max time: {max(times):.1f}s")
            print(f"  Avg time: {sum(times)/len(times):.1f}s")

        report = {
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": passed / total if total > 0 else 0,
            "by_category": by_category,
            "failed_tests": [r.test.name for r in failed_tests],
            "avg_time": sum(times) / len(times) if times else 0
        }

        print("\n" + "="*60)
        return report


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_query_system.py <mount_point>")
        print("Example: python test_query_system.py Z:")
        sys.exit(1)

    mount_point = sys.argv[1]
    tester = QueryTester(mount_point)
    report = tester.run_all_tests()

    # Save report
    report_path = Path(__file__).parent / "query_test_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport saved to: {report_path}")

    # Exit with appropriate code
    sys.exit(0 if report.get("pass_rate", 0) >= 0.5 else 1)


if __name__ == "__main__":
    main()
