"""S5-P1: RAGAS testset generator for answer-layer eval pilot.

Generates Q&A samples from indexed corpus using RAGAS TestsetGenerator.
Requires: pip install ragas langchain-community langchain-text-splitters
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

try:
    from langchain.docstore.document import Document as LangChainDocument
    from ragas.testset.evolutions import multi_context, reasoning, simple
    from ragas.testset.generator import TestsetGenerator
    RAGAS_AVAILABLE = True
except ImportError:
    RAGAS_AVAILABLE = False

from app.services.knowledge_metadata_store import knowledge_metadata_store


def load_documents_for_ragas(kb_ids: list[str]) -> list[LangChainDocument]:
    """Load indexed documents and convert to LangChain format."""
    documents = []

    for kb_id in kb_ids:
        docs = knowledge_metadata_store.list_documents(kb_id)
        for doc in docs:
            # Read document content
            doc_path = Path(doc.filepath)
            if not doc_path.exists():
                continue

            content = doc_path.read_text(encoding="utf-8")

            # Convert to LangChain Document
            lc_doc = LangChainDocument(
                page_content=content,
                metadata={
                    "kb_id": kb_id,
                    "doc_id": doc.doc_id,
                    "filename": doc.filename,
                    "source": str(doc_path),
                }
            )
            documents.append(lc_doc)

    return documents


def generate_ragas_testset(
    *,
    output_path: str | Path,
    target_size: int = 40,
    kb_ids: list[str] | None = None,
    generator_llm=None,
    embeddings=None,
) -> dict:
    """Generate RAGAS testset from indexed corpus."""
    if not RAGAS_AVAILABLE:
        print("ERROR: RAGAS not installed. Install with:")
        print("  uv pip install ragas langchain-community langchain-text-splitters")
        return {"status": "ragas_not_installed"}

    output_path = Path(output_path)

    if kb_ids is None:
        kb_ids = ["process_digital_dept", "craft_dept"]

    print(f"Loading documents from KBs: {kb_ids}")
    documents = load_documents_for_ragas(kb_ids)
    print(f"Loaded {len(documents)} documents")

    if not documents:
        print("ERROR: No documents found")
        return {"status": "no_documents"}

    # Initialize RAGAS generator
    if generator_llm is None or embeddings is None:
        print("ERROR: LLM and embeddings required for RAGAS generation")
        print("Pass --use-openai to use OpenAI, or provide custom LLM")
        return {"status": "llm_required"}

    generator = TestsetGenerator.from_langchain(
        generator_llm=generator_llm,
        critic_llm=generator_llm,
        embeddings=embeddings,
    )

    print(f"Generating {target_size} test samples...")
    testset = generator.generate_with_langchain_docs(
        documents=documents,
        test_size=target_size,
        distributions={
            simple: 0.5,      # 50% simple fact lookup
            reasoning: 0.3,   # 30% reasoning required
            multi_context: 0.2  # 20% multi-document
        }
    )

    # Convert RAGAS output to our answer-layer format
    candidates = []
    for i, row in enumerate(testset.to_pandas().itertuples(), 1):
        sample = {
            "sample_id": f"S5P1-R-{i:03d}",
            "layer": "answer",
            "query": row.question,
            "allowed_kb_ids": kb_ids,
            "expected_doc_ids": [],  # RAGAS doesn't provide this, need manual review
            "reference_answer": row.ground_truth if hasattr(row, 'ground_truth') else "[HUMAN_REVIEW_REQUIRED]",
            "must_include_facts": ["[EXTRACT_FROM_REFERENCE_ANSWER]"],
            "must_not_include_claims": ["[HUMAN_REVIEW_REQUIRED]"],
            "required_citations": [],  # Need manual review
            "context_policy": "retrieved_context_only",
            "judge_policy": "ragas_shadow",
            "retrieval_mode": "dense_only",
            "top_k": 3,
            "ragas_generated": True,
            "ragas_evolution_type": row.evolution_type if hasattr(row, 'evolution_type') else "simple",
            "human_review_status": "pending",
            "_ragas_context": row.contexts[:2] if hasattr(row, 'contexts') else [],
        }
        candidates.append(sample)

    # Save candidates
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for sample in candidates:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "generator": "ragas_testset_generator",
        "status": "generated_pending_human_review",
        "target_size": target_size,
        "generated_samples": len(candidates),
        "kb_ids": kb_ids,
        "source_documents": len(documents),
        "distributions": {
            "simple": 0.5,
            "reasoning": 0.3,
            "multi_context": 0.2
        },
        "human_review_required": [
            "1. Review each query for quality and relevance",
            "2. Fill expected_doc_ids (which doc should answer this)",
            "3. Review/refine reference_answer",
            "4. Extract must_include_facts from reference_answer",
            "5. Fill must_not_include_claims (common fabrications)",
            "6. Fill required_citations (source_file/section expected)",
            "7. Filter out low-quality samples",
            "8. Save final 20-30 samples to department_rag_answer_pilot_20q.jsonl"
        ]
    }

    report_path = output_path.parent / f"{output_path.stem}_generation_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\n✅ Generated {len(candidates)} samples: {output_path}")
    print(f"📊 Generation report: {report_path}")
    print("\n⚠️  Human review required before use")

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="S5-P1 RAGAS testset generator")
    parser.add_argument("--output", default="evals/knowledge_base/evalsets/generated.local.jsonl")
    parser.add_argument("--target-size", type=int, default=40)
    parser.add_argument("--kb-ids", nargs="+", default=["process_digital_dept"])
    parser.add_argument("--use-openai", action="store_true", help="Use OpenAI for generation (requires OPENAI_API_KEY)")
    args = parser.parse_args()

    if not RAGAS_AVAILABLE:
        print("❌ RAGAS not installed")
        print("\nInstall with:")
        print("  uv pip install ragas langchain-community langchain-text-splitters")
        return 1

    generator_llm = None
    embeddings = None

    if args.use_openai:
        try:
            from langchain_openai import ChatOpenAI, OpenAIEmbeddings
            generator_llm = ChatOpenAI(model="gpt-4")
            embeddings = OpenAIEmbeddings()
            print("Using OpenAI GPT-4 for generation")
        except ImportError:
            print("ERROR: langchain-openai not installed")
            print("  uv pip install langchain-openai")
            return 1
    else:
        print("ERROR: No LLM provider specified")
        print("Use --use-openai or implement custom LLM integration")
        return 1

    generate_ragas_testset(
        output_path=args.output,
        target_size=args.target_size,
        kb_ids=args.kb_ids,
        generator_llm=generator_llm,
        embeddings=embeddings,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
