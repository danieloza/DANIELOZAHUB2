# -*- coding: utf-8 -*-
import asyncio
import logging
from pathlib import Path

# Paths to the sibling RAG project
RAG_PROJECT_DIR = Path(r"C:\Users\syfsy\projekty\python-rag-langchain")
RAG_PYTHON_EXE = RAG_PROJECT_DIR / ".venv" / "Scripts" / "python.exe"
RAG_SCRIPT = RAG_PROJECT_DIR / "rag_demo.py"

async def get_rag_context(query: str) -> str:
    """
    Senior IT: Isolated Async RAG Bridge.
    Calls the LangChain project asynchronously to keep the bot responsive.
    """
    if not RAG_PYTHON_EXE.exists() or not RAG_SCRIPT.exists():
        logging.warning("RAG Project not found at %s. Falling back.", RAG_PROJECT_DIR)
        return ""

    try:
        # Run the RAG demo script as an async subprocess
        process = await asyncio.create_subprocess_exec(
            str(RAG_PYTHON_EXE), str(RAG_SCRIPT), "-q", query,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(RAG_PROJECT_DIR)
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
            
            if process.returncode == 0:
                output = stdout.decode("utf-8", errors="ignore")
                # Senior IT: Extract answer between markers or fallback to 'A: '
                if "A: " in output:
                    # If markers exist, stay within them
                    content = output
                    if "---RAG-START---" in output and "---RAG-END---" in output:
                        content = output.split("---RAG-START---")[1].split("---RAG-END---")[0]
                    
                    return content.split("A: ", 1)[1].strip()
                return output.strip()
            else:
                logging.error("RAG Subprocess Error: %s", stderr.decode())
                return ""
        except asyncio.TimeoutError:
            process.kill()
            logging.error("RAG Subprocess timed out after 60s")
            return ""
            
    except Exception as e:
        logging.error("RAG Bridge Exception: %s", e)
        return ""

async def get_smart_context_for_invoice(ocr_text: str) -> str:
    """
    Extracts keywords from OCR and queries the RAG system for business context.
    """
    # Extract first 200 chars or some keywords
    words = ocr_text.split()[:20]
    query = " ".join(words)
    return await get_rag_context(f"Znajdz informacje o firmie i typowych fakturach dla: {query}")

async def analyze_spending_trend(query: str) -> str:
    """
    Senior IT: Advanced BI Analysis using RAG.
    Asks the RAG system to perform trend analysis and synthesis on the retrieved documents.
    """
    prompt = (
        f"Przeanalizuj historie zakupow i odpowiedz na pytanie biznesowe: {query}. "
        "Skup sie na datach, kwotach i nazwach produktow. "
        "Jesli widzisz powtarzajace sie zakupy, wspomnij o tym. "
        "Jesli to pytanie o rekomendacje, opieraj sie na poprzednich zakupach."
    )
    return await get_rag_context(prompt)

def teach_rag_invoice(invoice_data: dict, full_ocr_text: str):
    """
    Senior IT: Continuous Learning Pipeline.
    Injects new invoice data into the RAG knowledge base for future retrieval.
    """
    KNOWLEDGE_FILE = RAG_PROJECT_DIR / "knowledge.txt"
    if not KNOWLEDGE_FILE.exists():
        return

    # Create a semantic summary
    items = full_ocr_text.replace("\n", " ")[:300] # Simplified item extraction
    entry = (
        f"\n[INVOICE-ENTRY] Date: {invoice_data.get('date')} | "
        f"Vendor: {invoice_data.get('company')} | "
        f"Amount: {invoice_data.get('gross')} PLN | "
        f"Content Keywords: {items}..."
    )
    
    try:
        with open(KNOWLEDGE_FILE, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as e:
        logging.error(f"Failed to teach RAG: {e}")
