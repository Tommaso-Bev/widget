import psycopg2
from sentence_transformers import SentenceTransformer
import RAG_functions
import webscraping
import nltk
import utilities
import prompt_gpo

# Scarico le cose necessarie per "l'arricchimento" della query
nltk.download('punkt')
nltk.download('wordnet')
nltk.download('omw-1.4')# sarebbe per espandere la query arricchita con altri linguaggi

conn = psycopg2.connect(
    dbname="database",
    user="postgres",
    password="provatesting",
    host="localhost",
    port="5432"
)

webscraping.starting_webscraping()

# Utilizziamo 'all-mpnet-base-v2' come embedder
embedder = SentenceTransformer('all-mpnet-base-v2')
# voglio fare dei test per vedere se fosse meglio avere questo embedder
# embedder = SentenceTransformer ('all-MiniLM-L6-v2')

cursor = conn.cursor()

RAG_functions.create_rag_nodes(embedder)

# query="Is there a section related to decaffeinated coffee?"
# query_enriched=utilities.expand_query(query)
# nodes_retrieved=RAG_functions.RAG_retrieval(embedder, query_enriched)

# gpt_prompt=prompt_gpo.generate_prompt(query, query_enriched, nodes_retrieved)

# #print(gpt_prompt)

# test sul numero di token del prompt
# prompt_gpo.test(gpt_prompt)
# gpt_answer=prompt_gpo.gpt_query(gpt_prompt)

# print(gpt_answer)

# for row in nodes_retrieved:
#     print(row)

