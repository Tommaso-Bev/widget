import psycopg2
import os
from sentence_transformers import SentenceTransformer
import nltk
from RAG_functions import RAG_retrieval
import webscraping
from prompt_gpo import gpt_query, generate_prompt
import utilities
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Any
import undetected_chromedriver as uc
import logging
import threading

# Scarico le cose necessarie per "l'arricchimento" della query
nltk.download('punkt')
nltk.download('wordnet')
nltk.download('omw-1.4')# sarebbe per espandere la query arricchita con altri linguaggi

current_page_id = 1
embedder = SentenceTransformer('all-mpnet-base-v2')
frontend_path = os.path.join(os.path.dirname(__file__), '..', 'frontend')
frontend_path = os.path.abspath(frontend_path)

# Connessione al database PostgreSQL
conn = psycopg2.connect(
    dbname="database",
    user="postgres",
    password="provatesting",
    host="localhost",
    port="5432"
)
cursor = conn.cursor()

# FastAPI
app = FastAPI(title="chatbot RAG with visual tours")
app.add_middleware(
    CORSMiddleware, # per sviare dalla policy CORS
    allow_origins=["*"],          
    allow_credentials=True,
    allow_methods=["*"],            
    allow_headers=["*"],           
)
app.mount("/frontend", StaticFiles(directory=frontend_path), name="frontend")

# ---- Modelli Pydantic ----
# Richiesta dell'utente alla chat
class ChatRequest(BaseModel):
    message: str
# Singolo step del tour guidato
class TourStep(BaseModel):
    selector: str
    intro: str    
# Risposta del backend alla domanda dell'utente
class ChatResponse(BaseModel):
    answer: str
    tour_steps: Optional[List[TourStep]] = None  
# Richiesta di scraping ad un url specifico
class ScrapeRequest(BaseModel):
    url: str

# Funzione che ritorna l'url della pagina partendo dall'ID della pagina 
def get_page_url_from_id(page_id: int):
    try:
        cursor.execute("SELECT URL FROM Pages WHERE PageID = %s", (page_id,))
        result = cursor.fetchone()
        if result:
            return result[0]
    except Exception as e:
        logging.error(f"Error fetching URL for PageID {page_id}: {e}")
    return None

# Funzione che ritorna il selettore CSS a partire dal nodo
def get_css_selector_from_node(node):
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

# Funzione per avviare lo scraping su un browser con le opzioni indicate
def perform_scraping(url: str):
    options=uc.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    driver=uc.Chrome(options=options)
    
    webscraping.starting_webscraping(driver, url)
 
    driver.quit()
        
# Funzione che da' in maniera automatica le risposte per la guida visuale (più accortezze per gli elementi non presenti nella pagina attuale)
def build_tour_steps(gpt_response_data: dict[str, Any],nodes_retrieved: list[dict[str, Any]],current_page_id: str,generate_intro_func) -> List[dict[str, str]]:
    response_text = gpt_response_data.get("answer", "")
    chosen_selectors = gpt_response_data.get("tour_selectors", [])
    tour_steps = []
    selector_to_node_map = {node.get("cssselector"): node for node in nodes_retrieved if node.get("cssselector")}
    urls_mentioned_in_answer = set()

    for selector in chosen_selectors:
        found_node_for_selector = None
        for node in nodes_retrieved:
            if node.get("cssselector") == selector:
                found_node_for_selector = node
                break
            if node.get("source_link_css") == selector:
                found_node_for_selector = node
                break
        if found_node_for_selector:
            node = found_node_for_selector
            is_element_selector = node.get("cssselector") == selector
            is_source_link_selector = node.get("source_link_css") == selector and node.get("page_id") != current_page_id
            intro_text = ""
            if is_source_link_selector:
                intro_text = f"This link (on the current page) leads to more information on '{node.get('page_url')}'."
            elif is_element_selector:
                intro_text = generate_intro_func(node)
                if node.get("page_id") != current_page_id:
                    logging.warning(f"GPT returned element selector '{selector}' for external PageID {node.get('page_id')}. Cannot highlight directly.")
                    continue
            if intro_text:
                tour_steps.append({
                    "selector": selector,
                    "intro": intro_text,
                    "position": "bottom"
                })
        else:
            logging.warning(f"GPT referenced a selector '{selector}' that could not be mapped to any retrieved RAG node (either as cssselector or source_link_css).")        
    return {
        "answer": response_text,
        "tour_steps":tour_steps
        }

# Endpoint FastAPI che gestisce la richiesta da parte del frontend, interagisce con il sistema di RAG e il modello GPT e restituisce la risposta
@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    # domanda dell'utente ed arricchimento della richiesta tramite nltk
    user_input = req.message
    user_input_expanded = utilities.expand_query(user_input)
    # retrieval
    nodes_retrieved = RAG_retrieval(embedder, user_input_expanded)
    # elaborazione prompt e conseguente risposta del modello GPT
    gpt_prompt = generate_prompt(user_input, user_input_expanded, nodes_retrieved, current_page_id)
    gpt_response_data = gpt_query(gpt_prompt) 
    # funzione per ritornare risposta e guida visuale
    return build_tour_steps(gpt_response_data, nodes_retrieved, current_page_id, generate_intro_func=utilities.generate_intro)

# Endpoint per avviare lo scraping della pagina web
@app.post("/api/start-scraping/")
async def start_scraping(data: ScrapeRequest):
    url = data.url
    print(f"🌐 Ricevuto URL: {url}")

    # esegue scraping in background per non bloccare la risposta
    threading.Thread(target=perform_scraping, args=(url,)).start()

    return {"message": f"Scraping avviato per {url}"}

