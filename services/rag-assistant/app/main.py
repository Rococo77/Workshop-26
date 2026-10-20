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
    """Indexe le corpus Markdown : recherche hybride mots-clés (BM25) + vecteurs.

    Mesuré sur le corpus : vecteurs seuls -> bon passage pour 1 question sur 3
    (ex. "réaction à un DoS" ramenait les risques résiduels, pas le playbook).
    Les 3 leviers ci-dessous portent le score à 4/4 sur les questions documentées.
    """
    from langchain.retrievers import EnsembleRetriever
    from langchain_community.document_loaders import DirectoryLoader, TextLoader
    from langchain_community.retrievers import BM25Retriever
    from langchain_community.vectorstores import FAISS
    from langchain_core.documents import Document
    from langchain_ollama import OllamaEmbeddings
    from langchain_text_splitters import (
        MarkdownHeaderTextSplitter,
        RecursiveCharacterTextSplitter,
    )

    class NomicEmbeddings(OllamaEmbeddings):
        """nomic-embed-text attend ces préfixes de tâche (sinon recherche dégradée)."""

        def embed_documents(self, texts):
            return super().embed_documents([f"search_document: {t}" for t in texts])

        def embed_query(self, text):
            return super().embed_query(f"search_query: {text}")

    docs_path = Path(CORPUS_DIR)
    loader = DirectoryLoader(
        str(docs_path), glob="**/*.md", loader_cls=TextLoader, loader_kwargs={"encoding": "utf-8"}
    )
    documents = loader.load()
    if not documents:
        raise RuntimeError(f"corpus vide dans {CORPUS_DIR}")

    # Découpage par sections, chaque passage préfixé de "fichier | titres" : une
    # ligne de tableau garde ainsi le contexte de la section qui la contient.
    by_header = MarkdownHeaderTextSplitter(
        [("#", "h1"), ("##", "h2"), ("###", "h3")], strip_headers=False
    )
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=120)
    chunks = []
    for doc in documents:
        name = Path(doc.metadata["source"]).name
        for section in by_header.split_text(doc.page_content):
            titles = " > ".join(v for _, v in sorted(section.metadata.items()))
            chunks += [
                Document(page_content=f"[{name} | {titles}]\n{c}", metadata=doc.metadata)
                for c in splitter.split_text(section.page_content)
            ]

    k = 6
    dense = FAISS.from_documents(
        chunks, NomicEmbeddings(base_url=OLLAMA_BASE_URL, model=EMBED_MODEL)
    ).as_retriever(search_kwargs={"k": k})
    log.info("index RAG construit : %d chunks", len(chunks))
    return EnsembleRetriever(
        retrievers=[BM25Retriever.from_documents(chunks, k=k), dense], weights=[0.5, 0.5]
    )


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

        context_docs = _retriever.invoke(question.q)[:6]  # union BM25+vecteurs -> top 6
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
