"""Assistant opérateur RAG — Ollama + LangChain sur le corpus documentaire.

Rôle (sujet §3.3) : aider l'opérateur confronté à l'incident à retrouver une
information dans les procédures / l'architecture. Il N'EST PAS l'automate de
remédiation et ne dispose d'AUCUN accès privilégié au système : il lit un corpus
documentaire en lecture seule et répond en langage naturel.

Dégradation maîtrisée : si Ollama est indisponible, l'API répond proprement
(503) au lieu de planter, et l'index se (re)construit à la première requête.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("rag")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "hf.co/unsloth/Qwen3-4B-GGUF:Q4_K_M")
EMBED_MODEL = os.getenv("RAG_EMBED_MODEL", "nomic-embed-text")
CORPUS_DIR = os.getenv("CORPUS_DIR", "/app/corpus")
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)

app = FastAPI(title="Resilience-Alpha RAG Assistant", version="1.0.0")
_retriever = None  # construit paresseusement


class Question(BaseModel):
    q: str


class Answer(BaseModel):
    answer: str
    sources: list[str]


def _build_retriever():
    """Indexe le corpus Markdown en base vectorielle (FAISS, en mémoire)."""
    from langchain_community.document_loaders import DirectoryLoader, TextLoader
    from langchain_community.vectorstores import FAISS
    from langchain_ollama import OllamaEmbeddings
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    docs_path = Path(CORPUS_DIR)
    loader = DirectoryLoader(
        str(docs_path), glob="**/*.md", loader_cls=TextLoader, loader_kwargs={"encoding": "utf-8"}
    )
    documents = loader.load()
    if not documents:
        raise RuntimeError(f"corpus vide dans {CORPUS_DIR}")

    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=120)
    chunks = splitter.split_documents(documents)
    embeddings = OllamaEmbeddings(base_url=OLLAMA_BASE_URL, model=EMBED_MODEL)
    store = FAISS.from_documents(chunks, embeddings)
    log.info("index RAG construit : %d chunks", len(chunks))
    return store.as_retriever(search_kwargs={"k": 4})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ask", response_model=Answer)
def ask(question: Question) -> Answer:
    global _retriever
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_ollama import ChatOllama

    try:
        if _retriever is None:
            _retriever = _build_retriever()

        context_docs = _retriever.invoke(question.q)
        context = "\n\n".join(d.page_content for d in context_docs)
        sources = sorted({Path(d.metadata.get("source", "?")).name for d in context_docs})

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "Tu es un assistant d'exploitation. Réponds en français, "
                    "de façon concise, UNIQUEMENT à partir du contexte fourni. "
                    "Si l'information n'y est pas, dis-le. /no_think",
                ),
                ("human", "Contexte :\n{context}\n\nQuestion : {q}"),
            ]
        )
        llm = ChatOllama(base_url=OLLAMA_BASE_URL, model=OLLAMA_MODEL, temperature=0)
        chain = prompt | llm
        resp = chain.invoke({"context": context, "q": question.q})
        # Qwen3 émet un bloc <think> (vide avec /no_think) : jamais montré à l'opérateur.
        answer = _THINK.sub("", resp.content).strip()
        return Answer(answer=answer, sources=sources)
    except Exception as exc:
        log.error("RAG indisponible: %s", exc)
        raise HTTPException(503, f"assistant indisponible (Ollama requis): {exc}") from exc
