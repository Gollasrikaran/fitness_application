import sys
import subprocess

try:
    import docx
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-docx"])
    import docx

doc = docx.Document()

text = """Ayush Kumar
+91-8595262736 | ayush21cs2029@gmail.com | LinkedIn | GitHub

Dear Hiring Team at dexter health,

I am writing to express my strong interest in the AI Engineer (LLM Products) - Remote position at dexter health. As a final-year Integrated Dual Degree (B.Tech CSE + M.Tech AI-ML) student at the Rajiv Gandhi Institute of Petroleum Technology, I have developed deep expertise in designing, optimizing, and deploying LLM applications and Generative AI systems.

My recent work at VitaInspire Private Limited heavily aligns with the core requirements of building robust LLM products. I engineered a Retrieval-Augmented Generation (RAG) chatbot utilizing pgvector embeddings and safety guardrails, alongside an LLM-as-a-judge evaluation pipeline using RAGAS to ensure high-fidelity response quality. Furthermore, I built and deployed a two-tier OCR/LLM document-grading pipeline by serving AWQ-quantized Qwen3-30B and InternVL2.5-8B vision models via vLLM on AWS GPU infrastructure, ensuring scalable, OpenAI-compatible REST API integration through continuous batching.

Beyond application development, I have extensive hands-on experience fine-tuning models for production environments. During my research internship at NIT Warangal, I implemented parameter-efficient techniques (LoRA/DORA) and 4-bit/8-bit quantization to optimize training efficiency and GPU memory usage for FLUX.1 Schnell. At BNNarratives, I optimized transformer-based architectures for Generative AI content generation, specifically focusing on reducing inference latency and improving factual consistency for media production. My personal projects further demonstrate my capabilities in LLM orchestration; for instance, I built a Multi-Agent LLM Debate Orchestrator powered by Mistral-8x7B, utilizing automated memory, directed acyclic graphs (DAG), and finite state machine (FSM) logic.

With expert-level proficiency in Python and deep familiarity with PyTorch, FastAPI, and inference acceleration tools, I am well-prepared to contribute to your engineering team immediately. I am eager to bring my background in end-to-end model deployment, RAG architectures, and AI agent frameworks to dexter health's remote setup.

Thank you for considering my application. I have attached my resume, Resume_Ayush.pdf, for your review, and I look forward to the possibility of discussing how my technical skill set can accelerate your LLM product roadmap.

Sincerely,

Ayush Kumar"""

for paragraph in text.split('\n'):
    doc.add_paragraph(paragraph)

import os
os.makedirs("E:\\downloads", exist_ok=True)
doc.save("E:\\downloads\\Cover_Letter_Ayush_Kumar.docx")
print("Saved to E:\\downloads\\Cover_Letter_Ayush_Kumar.docx")
