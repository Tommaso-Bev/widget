from bs4 import BeautifulSoup
import sqlite3
import requests
from openai import OpenAI
import tiktoken
import key

client = OpenAI(api_key=key.gpo_key()) #OpenAI(api_key="here there's the api key")

conn = sqlite3.connect('html_tree.db')
cursor = conn.cursor()


def fetch_info():
    cursor.execute(
        """
        SELECT ID, Tag, TextContent, Path, Children FROM HTMLTree
        """
    )
    rows = cursor.fetchall()
    return rows[1:] 


#gpt model
def gpt_query(prompt):
    response= client.chat.completions.create(
    model="gpt-3.5-turbo",
    messages=[
        {"role": "system", "content": "You are an expert assistant"},
        {"role": "user", "content": prompt}
    ],
    max_tokens=500
    )
    return response.choices[0].message.content

def count_tokens(text, model="gpt-3.5-turbo"):
    # Load the appropriate tokenizer for the model
    encoding = tiktoken.encoding_for_model(model)
    # Encode the text into tokens
    tokens = encoding.encode(text)
    # Return the number of tokens
    return len(tokens)

def generate_prompt(user_query, enriched_context, retrieved_chunks ):
    """
    Genera il prompt per GPT-3.5/4 basato sulla query dell'utente, sui risultati della ricerca per somiglianza
    (arricchita con WordNet) e sul contesto strutturato (padri, figli, fratelli).
    """

    prompt = f"""
    You are an AI assistant that answers based on whatever database data you are given.
    
    🔹 **User query**: 
    {user_query}
    🔹 **User query, enriched via wordnet**: 
    {enriched_context}
    🔹 **Data retrieved from database**:
    Note that every node has an id, the content and a number that indicates how much likely it could be the answer for the user query. Every node could have a father, children or, if it has neither, its brothers.
    Base your answer on the idea that if the user asks for something and there are two database rows, one that has the thing the user wants precisely as its contents, and one as the content of a brother of the node, prefer using the row that has the precise content.
    {retrieved_chunks}

    
    ⚠️ Only use the data you are given, you have little independency on how to respond"
    """

    return prompt

def test(retrieved_chunks):
    print(count_tokens(retrieved_chunks))