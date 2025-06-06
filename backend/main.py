import psycopg2
import os
import numpy as np

from sentence_transformers import SentenceTransformer
import nltk

from RAG_functions import RAG_retrieval, create_rag_nodes
import webscraping
from prompt_gpo import gpt_query, generate_prompt
import utilities

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Any

from selenium.webdriver.chrome.options import Options
from selenium import webdriver
import undetected_chromedriver as uc

import threading

def get_css_selector_from_node(node):
    """
    Simula una versione semplificata di get_css_selector, basata su id o class
    (usa dati già presenti nel node, senza bisogno del driver).
    """
    el_id = node.get("id")
    if el_id:
        return f"#{el_id}"

    class_attr = node.get("class") or ""
    classes = class_attr.split()
    if classes:
        tag = node.get("tag", "div").lower()
        return f"{tag}.{classes[0]}"

    tag = node.get("tag", "div").lower()
    index = node.get("index", 1)
    return f"{tag}:nth-of-type({index})"


# Scarico le cose necessarie per "l'arricchimento" della query
nltk.download('punkt')
nltk.download('wordnet')
nltk.download('omw-1.4')# sarebbe per espandere la query arricchita con altri linguaggi
embedder = SentenceTransformer('all-mpnet-base-v2')
conn = psycopg2.connect(
    dbname="database",
    user="postgres",
    password="provatesting",
    host="localhost",
    port="5432"
)
cursor = conn.cursor()

app = FastAPI(title="chatbot RAG with visual tours")

# Enable CORS to allow JS to talk to Python API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],            # ← Or list specific origins e.g. ["https://yourdomain.com"]
    allow_credentials=True,
    allow_methods=["*"],            # GET, POST, PUT, etc.
    allow_headers=["*"],            # e.g. Authorization, Content-Type
)

frontend_path = os.path.join(os.path.dirname(__file__), '..', 'frontend')
frontend_path = os.path.abspath(frontend_path)

app.mount("/frontend", StaticFiles(directory=frontend_path), name="frontend")

# ---- Pydantic models ----
class ChatRequest(BaseModel):
    message: str


class TourStep(BaseModel):
    selector: str  # Cambio da 'element' (XPath) a 'selector' (CSS)
    intro: str
    

class ChatResponse(BaseModel):
    answer: str
    tour_steps: Optional[List[TourStep]] = None
    
class ScrapeRequest(BaseModel):
    url: str

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    # 1. Your existing logic
    user_input = req.message
    user_input_expanded = utilities.expand_query(user_input)
    # Make sure RAG_retrieval also returns each node’s XPath and enriched text:
    # e.g. [{"source_id":…, "enriched_text":…, "xpath":…}, …]
    nodes_retrieved = RAG_retrieval(embedder, user_input_expanded)
    
    gpt_prompt = generate_prompt(user_input, user_input_expanded, nodes_retrieved)
    response = gpt_query(gpt_prompt)  # or await if it’s async

    # 2. Build tour_steps *always* (for testing)
    tour_steps = []
    for node in nodes_retrieved:
        selector = node.get("cssselector")
        enriched = node.get("enrichedtext") or node.get("text", "")
        if selector:
            tour_steps.append({
                "selector": selector,
                "intro": utilities.generate_intro(node),
                "position": "bottom"  # opzionale
            })
        print(selector)
        print(enriched)
    # limit to first 3 steps
    tour_steps = tour_steps[:3]
    print(tour_steps)
    # 3. Return both answer and tour_steps
    return {
        "answer": response,
        "tour_steps": tour_steps
    }



def should_generate_tour_for_question(question: str) -> bool:
    # TODO Per il momento metto sempre a True, poi lo devo gestire meglio
    return True

def perform_scraping(url: str):
    options=uc.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    driver=uc.Chrome(options=options)
    
    webscraping.starting_webscraping(driver, url)
 
    driver.quit()
    
@app.post("/api/start-scraping/")
async def start_scraping(data: ScrapeRequest):
    url = data.url
    print(f"🌐 Ricevuto URL: {url}")

    # Esegui scraping in background per non bloccare la risposta
    threading.Thread(target=perform_scraping, args=(url,)).start()

    return {"message": f"Scraping avviato per {url}"}