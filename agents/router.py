# agents/router.py
"""
Question Router — classifies incoming questions to determine which
agent should handle them.

Categories:
  • code_search   → Retrieval Agent  (how does X work? where is Y?)
  • architecture  → Architecture Agent  (what's the structure? what framework?)
  • dependency    → Dependency Agent  (what depends on X? what does Y import?)
  • documentation → Documentation Agent  (summarize file Z, explain module W)
  • multi_hop     → Multi-hop chain  (complex cross-cutting questions)
"""

from agents.base import get_llm, get_parser
from langchain_core.prompts import ChatPromptTemplate


ROUTING_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are a question classifier for a codebase analysis system. "
     "Given a user question, classify it into exactly ONE of these categories:\n\n"
     "  code_search   — questions about specific code logic, functions, implementations\n"
     "  architecture  — questions about project structure, tech stack, frameworks, patterns\n"
     "  dependency    — questions about imports, dependencies, what depends on what\n"
     "  documentation — questions asking for summaries, explanations of files/modules\n"
     "  multi_hop     — complex questions that span multiple files or need cross-referencing\n\n"
     "Respond with ONLY the category name, nothing else.\n\n"
     "Examples:\n"
     '  "How does authentication work?" → code_search\n'
     '  "What framework is this project using?" → architecture\n'
     '  "What files import the User model?" → dependency\n'
     '  "Summarize the main.py file" → documentation\n'
     '  "How does auth connect to the payment system?" → multi_hop\n'),
    ("human", "{question}"),
])

VALID_ROUTES = {"code_search", "architecture", "dependency", "documentation", "multi_hop"}


class QuestionRouter:
    """Classify questions using a few-shot Gemini prompt."""

    def __init__(self):
        self.llm = get_llm(temperature=0)
        self.parser = get_parser()
        self.chain = ROUTING_PROMPT | self.llm | self.parser

    def classify(self, question: str) -> str:
        """Return the route category for a question."""
        result = self.chain.invoke({"question": question}).strip().lower()

        # Validate — fall back to code_search if the LLM hallucinates
        if result not in VALID_ROUTES:
            # Try to match a substring
            for route in VALID_ROUTES:
                if route in result:
                    return route
            return "code_search"

        return result


# ------------------------------------------------------------------
# Standalone test
# ------------------------------------------------------------------
if __name__ == "__main__":
    router = QuestionRouter()
    test_questions = [
        "How does authentication work?",
        "What framework is this project using?",
        "What files import the User model?",
        "Summarize the main.py file",
        "How does auth connect to the payment system?",
        "Where is the database connection configured?",
        "What are the external dependencies?",
        "Give me an overview of the project structure",
    ]

    for q in test_questions:
        route = router.classify(q)
        print(f"  {route:15s} ← {q}")
