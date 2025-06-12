import psycopg2
from sentence_transformers import SentenceTransformer
import RAG_functions
import webscraping
import nltk
import utilities
import prompt_gpo
import logging

conn = psycopg2.connect(
    dbname="database",
    user="postgres",
    password="provatesting",
    host="localhost",
    port="5432"
)


# Utilizziamo 'all-mpnet-base-v2' come embedder
embedder = SentenceTransformer('all-mpnet-base-v2')
# voglio fare dei test per vedere se fosse meglio avere questo embedder
# embedder = SentenceTransformer ('all-MiniLM-L6-v2')

current_page_id = 1
cursor = conn.cursor()
user_input = "Coffee has a long, rich story to tell. In fact, the history of coffee began over 1,000 years ago, according to legend. You can trace its path across the globe, all the way to your cup."
user_input_expanded = utilities.expand_query(user_input)

nodes_retrieved = RAG_functions.RAG_retrieval(embedder, user_input_expanded)

gpt_prompt = prompt_gpo.generate_prompt(user_input, user_input_expanded, nodes_retrieved, current_page_id)
logging.info(gpt_prompt)
gpt_response_data = prompt_gpo.gpt_query(gpt_prompt) 
response_text = gpt_response_data["answer"]
chosen_selectors = gpt_response_data["tour_selectors"]

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
            # Se l'elemento trovato non si trova nella pagina attuale
            intro_text = f"This link (on the current page) leads to more information on '{node.get('page_url')}'."
        elif is_element_selector:
            # Se l'elemento si trova in questa pagina
            intro_text = utilities.generate_intro(node)
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


print(f"GPT Answer: {response_text}")
print(f"Tour Selectors from GPT: {chosen_selectors}")
print(f"Final Tour Steps: {tour_steps}")
