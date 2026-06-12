# agents/multi_hop.py
"""
Multi-hop Reasoning — handles complex questions that require chaining
multiple agents together.

Example: "How does auth connect to payment processing?"
  Step 1: Retrieval Agent finds auth-related code
  Step 2: Dependency Agent finds what auth imports/exports
  Step 3: Retrieval Agent searches payment code
  Step 4: LLM synthesizes the connection
"""

from typing import Dict, List, TypedDict

from langgraph.graph import StateGraph, END
from langchain_core.prompts import ChatPromptTemplate

from agents.base import get_llm, get_parser


class MultiHopState(TypedDict, total=False):
    question: str
    step_results: List[Dict]
    final_answer: str
    sources: List[str]


class MultiHopReasoner:
    """Chain multiple agent calls to answer complex questions."""

    def __init__(self, retrieval_agent, dependency_agent, documentation_agent):
        self.retrieval = retrieval_agent
        self.dependency = dependency_agent
        self.documentation = documentation_agent
        self.llm = get_llm(temperature=0.1)
        self.parser = get_parser()
        self._graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        g = StateGraph(MultiHopState)

        g.add_node("decompose", self._node_decompose)
        g.add_node("gather_context", self._node_gather)
        g.add_node("synthesize", self._node_synthesize)

        g.set_entry_point("decompose")
        g.add_edge("decompose", "gather_context")
        g.add_edge("gather_context", "synthesize")
        g.add_edge("synthesize", END)

        return g.compile()

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------
    def _node_decompose(self, state: MultiHopState) -> Dict:
        """Break the complex question into simpler sub-questions."""
        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are a code analysis planner. Given a complex question about "
             "a codebase, break it into 2-4 simpler sub-questions that can be "
             "answered independently. Return each sub-question on its own line, "
             "numbered. Nothing else."),
            ("human", "{question}"),
        ])

        chain = prompt | self.llm | self.parser
        raw = chain.invoke({"question": state["question"]})

        sub_questions = [
            line.strip().lstrip("0123456789.-) ")
            for line in raw.strip().split("\n")
            if line.strip()
        ]

        return {"step_results": [{"sub_question": sq} for sq in sub_questions]}

    def _node_gather(self, state: MultiHopState) -> Dict:
        """Run each sub-question through retrieval + dependency agents."""
        results = state.get("step_results", [])
        all_sources = []

        for step in results:
            sq = step["sub_question"]

            # Try retrieval first
            try:
                ret_result = self.retrieval.answer_question(sq, k=3)
                step["retrieval_answer"] = ret_result["answer"]
                all_sources.extend(ret_result.get("sources", []))
            except Exception as e:
                step["retrieval_answer"] = f"(retrieval error: {e})"

            # Try dependency context
            try:
                dep_result = self.dependency.answer_question(sq)
                step["dependency_answer"] = dep_result["answer"]
            except Exception as e:
                step["dependency_answer"] = f"(dependency error: {e})"

        return {"step_results": results, "sources": list(set(all_sources))}

    def _node_synthesize(self, state: MultiHopState) -> Dict:
        """Combine all sub-answers into a final coherent response."""
        results = state.get("step_results", [])

        # Build context from all sub-answers
        context_parts = []
        for step in results:
            part = f"Sub-question: {step['sub_question']}\n"
            part += f"Code analysis: {step.get('retrieval_answer', 'N/A')}\n"
            part += f"Dependency analysis: {step.get('dependency_answer', 'N/A')}"
            context_parts.append(part)

        context = "\n\n---\n\n".join(context_parts)

        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are a senior code analyst. Given the results of multiple "
             "sub-analyses about a codebase, synthesize them into a clear, "
             "coherent answer to the original question. Reference specific "
             "files and function names. Be thorough but concise.\n\n"
             "Analysis results:\n{context}"),
            ("human", "{question}"),
        ])

        chain = prompt | self.llm | self.parser
        answer = chain.invoke({"context": context, "question": state["question"]})

        return {"final_answer": answer}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def answer(self, question: str) -> Dict:
        """Answer a complex multi-hop question."""
        result = self._graph.invoke({"question": question})
        return {
            "answer": result.get("final_answer", ""),
            "sources": result.get("sources", []),
            "steps": len(result.get("step_results", [])),
            "agent_used": "multi_hop",
        }


# ------------------------------------------------------------------
# Standalone test
# ------------------------------------------------------------------
if __name__ == "__main__":
    from agents.retrieval_agent import RetrievalAgent
    from agents.dependency_agent import DependencyAgent
    from agents.documentation_agent import DocumentationAgent

    retrieval = RetrievalAgent()
    retrieval.load_existing_index()

    dependency = DependencyAgent()
    dependency.build_graph(".")

    documentation = DocumentationAgent()

    reasoner = MultiHopReasoner(retrieval, dependency, documentation)
    result = reasoner.answer("How does authentication connect to payment processing?")

    print(f"Answer: {result['answer']}")
    print(f"Sources: {result['sources']}")
    print(f"Steps: {result['steps']}")
