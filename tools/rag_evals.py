#!/usr/bin/env python3
"""
RAG evaluation utilities for CognitiveFS using RAGAS.

Examples:
  python tools/rag_evals.py generate \
    --kg /path/to/your.kg.db \
    --output rag_testset.jsonl \
    --test-size 50 \
    --model gpt-4o-mini

  python tools/rag_evals.py run \
    --kg /path/to/your.kg.db \
    --testset rag_testset.jsonl \
    --output rag_results.jsonl \
    --answer-model gpt-4o-mini

  python tools/rag_evals.py evaluate \
    --results rag_results.jsonl \
    --model gpt-4o-mini
"""

import argparse
import json
from typing import List, Dict, Iterable, Optional

import pandas as pd
from langchain_core.documents import Document
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from ragas import evaluate
from ragas.llms import LangchainLLM
from ragas.metrics import faithfulness, answer_relevancy, context_precision
from ragas.testset.generator import TestsetGenerator

from cognitivefs.knowledge_graph import KnowledgeGraph
from cognitivefs.llm import KnowledgeQueryEngine, LLMResponse


DEFAULT_GENERATOR_MODEL = "gpt-4o-mini"
DEFAULT_JUDGE_MODEL = "gpt-4o-mini"
DEFAULT_ANSWER_MODEL = "gpt-4o-mini"


def load_documents(kg_path: str, limit: Optional[int], min_chars: int) -> List[Document]:
    kg = KnowledgeGraph(kg_path)
    kg.open()
    cursor = kg.conn.cursor()
    cursor.execute(
        """
        SELECT path, summary, extracted_text
        FROM files
        WHERE summary != '' OR extracted_text != ''
        ORDER BY modified_at DESC
        """
    )
    documents = []
    for row in cursor.fetchall():
        summary = row["summary"] or ""
        extracted_text = row["extracted_text"] or ""
        if summary and extracted_text:
            content = f"Summary:\n{summary}\n\nContent:\n{extracted_text}"
        else:
            content = extracted_text or summary
        if len(content.strip()) < min_chars:
            continue
        documents.append(Document(page_content=content, metadata={"path": row["path"]}))
        if limit and len(documents) >= limit:
            break
    kg.close()
    return documents


def _testset_to_dataframe(testset) -> pd.DataFrame:
    if isinstance(testset, pd.DataFrame):
        return testset
    if hasattr(testset, "to_pandas"):
        return testset.to_pandas()
    if hasattr(testset, "dataframe"):
        return testset.dataframe
    raise ValueError("Unsupported testset format returned by RAGAS")


def generate_testset(kg_path: str, output_path: str, test_size: int, model: str,
                     doc_limit: Optional[int], min_chars: int) -> None:
    documents = load_documents(kg_path, doc_limit, min_chars)
    if not documents:
        raise ValueError("No documents found in knowledge graph. Index files first.")

    llm = LangchainLLM(ChatOpenAI(model=model, temperature=0))
    generator = TestsetGenerator.from_langchain(generator_llm=llm, critic_llm=llm)
    testset = generator.generate_with_langchain_docs(documents, test_size=test_size)
    df = _testset_to_dataframe(testset)
    save_dataframe(df, output_path)


def _build_context_chunks(files: Iterable[Dict], max_chars: int) -> List[str]:
    chunks = []
    total_chars = 0
    for file_info in files:
        content = file_info.get("summary") or file_info.get("text") or ""
        if not content:
            continue
        if len(content) > 800:
            content = content[:800] + "..."
        chunk = f"[{file_info.get('path', 'unknown')}]:\n{content}"
        if total_chars + len(chunk) > max_chars:
            break
        chunks.append(chunk)
        total_chars += len(chunk)
    return chunks


def run_rag(kg_path: str, testset_path: str, output_path: str,
            answer_model: str, max_context_files: int, max_context_chars: int) -> None:
    testset_df = load_dataframe(testset_path)
    if "question" not in testset_df.columns:
        raise ValueError("Testset must include a 'question' column")

    kg = KnowledgeGraph(kg_path)
    kg.open()

    class OpenAIClient:
        def __init__(self, model: str):
            self._client = ChatOpenAI(model=model, temperature=0)
            self.model = model

        @property
        def is_available(self) -> bool:
            return True

        def generate(self, prompt: str, system: str = None,
                     temperature: float = 0.0, max_tokens: int = 1024) -> LLMResponse:
            messages = []
            if system:
                messages.append(SystemMessage(content=system))
            messages.append(HumanMessage(content=prompt))
            response = self._client.invoke(messages)
            return LLMResponse(content=response.content, model=self.model, done=True)

    engine = KnowledgeQueryEngine(kg, OpenAIClient(answer_model))

    answers = []
    contexts = []

    for _, row in testset_df.iterrows():
        question = row["question"]
        result = engine.query_with_context(question, max_context_files=max_context_files)
        answers.append(result.get("answer", ""))

        context_files = engine._find_relevant_files(question, max_context_files)
        context_chunks = _build_context_chunks(context_files, max_context_chars)
        contexts.append(context_chunks)

    results_df = testset_df.copy()
    results_df["answer"] = answers
    results_df["contexts"] = contexts
    save_dataframe(results_df, output_path)
    kg.close()


def evaluate_results(results_path: str, model: str, output_path: Optional[str]) -> None:
    results_df = load_dataframe(results_path)
    required_columns = {"question", "answer", "contexts", "ground_truth"}
    missing = required_columns - set(results_df.columns)
    if missing:
        raise ValueError(f"Results dataset missing columns: {sorted(missing)}")

    judge_llm = LangchainLLM(ChatOpenAI(model=model, temperature=0))
    results = evaluate(
        dataset=results_df,
        metrics=[faithfulness, answer_relevancy, context_precision],
        llm=judge_llm,
    )

    print(results)

    if output_path:
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(results, handle, indent=2)


def load_dataframe(path: str) -> pd.DataFrame:
    if path.endswith(".jsonl"):
        return pd.read_json(path, lines=True)
    if path.endswith(".json"):
        return pd.read_json(path)
    if path.endswith(".csv"):
        return pd.read_csv(path)
    raise ValueError("Unsupported file format. Use .jsonl, .json, or .csv")


def save_dataframe(df: pd.DataFrame, path: str) -> None:
    if path.endswith(".jsonl"):
        df.to_json(path, orient="records", lines=True)
        return
    if path.endswith(".json"):
        df.to_json(path, orient="records", indent=2)
        return
    if path.endswith(".csv"):
        df.to_csv(path, index=False)
        return
    raise ValueError("Unsupported output format. Use .jsonl, .json, or .csv")


def main() -> int:
    parser = argparse.ArgumentParser(description="RAG evals for CognitiveFS using RAGAS")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate_parser = subparsers.add_parser("generate", help="Generate a synthetic test set")
    generate_parser.add_argument("--kg", required=True, help="Path to knowledge graph .kg.db")
    generate_parser.add_argument("--output", required=True, help="Output file (.jsonl/.csv)")
    generate_parser.add_argument("--test-size", type=int, default=50, help="Number of Q&A pairs")
    generate_parser.add_argument("--model", default=DEFAULT_GENERATOR_MODEL, help="LLM model")
    generate_parser.add_argument("--doc-limit", type=int, default=None, help="Limit documents")
    generate_parser.add_argument("--min-chars", type=int, default=200, help="Minimum chars per doc")

    run_parser = subparsers.add_parser("run", help="Run the RAG pipeline on the test set")
    run_parser.add_argument("--kg", required=True, help="Path to knowledge graph .kg.db")
    run_parser.add_argument("--testset", required=True, help="Input testset file")
    run_parser.add_argument("--output", required=True, help="Output file (.jsonl/.csv)")
    run_parser.add_argument("--answer-model", default=DEFAULT_ANSWER_MODEL, help="Answer LLM model")
    run_parser.add_argument("--max-context-files", type=int, default=3, help="Max context files")
    run_parser.add_argument("--max-context-chars", type=int, default=1500, help="Max context chars")

    eval_parser = subparsers.add_parser("evaluate", help="Evaluate RAG outputs with RAGAS")
    eval_parser.add_argument("--results", required=True, help="Results file")
    eval_parser.add_argument("--model", default=DEFAULT_JUDGE_MODEL, help="Judge model")
    eval_parser.add_argument("--output", default=None, help="Optional output JSON for scores")

    args = parser.parse_args()

    if args.command == "generate":
        generate_testset(
            kg_path=args.kg,
            output_path=args.output,
            test_size=args.test_size,
            model=args.model,
            doc_limit=args.doc_limit,
            min_chars=args.min_chars,
        )
        return 0

    if args.command == "run":
        run_rag(
            kg_path=args.kg,
            testset_path=args.testset,
            output_path=args.output,
            answer_model=args.answer_model,
            max_context_files=args.max_context_files,
            max_context_chars=args.max_context_chars,
        )
        return 0

    if args.command == "evaluate":
        evaluate_results(
            results_path=args.results,
            model=args.model,
            output_path=args.output,
        )
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
