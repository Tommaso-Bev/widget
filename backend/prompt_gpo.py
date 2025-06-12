from openai import OpenAI
import key
import json
import logging


client = OpenAI(api_key=key.gpo_key()) #OpenAI(api_key="here there's the api key") io ho fatto una funzione esterna per prendere la chiave

# Funzione che genera il prompt GPT utilizzando la query dell'utente arricchita e il retriaval dal RAG, in maniera intelligente
def generate_prompt(user_query: str, expanded_query: str, retrieved_nodes: list[dict[str, any]], current_page_id: int) -> str:
    context_parts = []
    for i, node in enumerate(retrieved_nodes):
        # Si prendono tutte le parti dei nodi ritornati dal retrieval, quindi contensto, selettore CSS dell'elemento e della pagina in cui esso si trova insieme insieme al suo URL ed ID
        node_text = node.get("enriched_text")
        css_selector = node.get("cssselector")
        page_id = node.get("page_id")
        page_url = node.get("page_url")
        source_link_css = node.get("source_link_css") # selettore CSS della pagina in cui e' presente l'elemento
        
        context_info = ""
        # aggiunge maggiore contesto alla riga dell'elemento specificando se esso si trova nella pagina attuale o meno
        if page_id and page_id != current_page_id:
            context_info = f" (FROM OTHER PAGE - PageID: {page_id}, URL: {page_url}"
            if source_link_css:
                context_info += f", Link on current page leading to this: {source_link_css}"
            context_info += ")"
        else:
            context_info = " (FROM CURRENT PAGE)"
        # scrive nel prompt le varie componenti dell'elemento (elemento, contesto)
        if node_text and css_selector:
            context_parts.append(f"--- Element {i+1} (Selector: {css_selector}){context_info} ---\n{node_text}\n")
        elif node_text: # metto anche questa condizione, ma non dovrebbe essere necessaria
            context_parts.append(f"--- Element {i+1}{context_info} ---\n{node_text}\n")

    context_str = "\n".join(context_parts) if context_parts else "No specific relevant information found in the webpage content."

    # prompt effettivo con descrizione generale del funzionamento del database e di cosa il modello dovrebbe rispondere
    prompt = f"""
    You are an AI assistant that answers questions about the current webpage content.
    I will provide you with a user's question, an expanded version of that question,
    and several pieces of information (elements) retrieved from webpages, along with their CSS selectors.
    Some elements might come from pages other than the one currently displayed.

    For elements from **other pages**, their context will include:
    - `FROM OTHER PAGE` indicator
    - `PageID` of the source page
    - `URL` of the source page
    - `Link on current page leading to this`: This is the CSS selector of the <a> tag on the *current page* that leads to that other page.

    Your response MUST be a JSON object with two keys:
    1.  `"answer"`: A string containing your natural language answer to the user's query.
        **If your answer relies significantly on information from a page that is NOT the current page,**
        you MUST explicitly mention that the information is found on another page and include the URL of that page
        at the end of your answer, formatted like: **"More info: URL"**. (Just the raw URL, no brackets or parentheses around it).
    2.  `"tour_selectors"`: A JSON array of strings, where each string is the CSS selector of an HTML element
        that was *directly used* to formulate your answer, intended for a visual guide.
        **IMPORTANT:** This array should contain a maximum of 3 CSS selectors.
        **If a selected element is from the `CURRENT PAGE`:** provide its own `CSS Selector`.
        **If a selected element is from an `OTHER PAGE`:** you MUST provide the `Link on current page leading to this` CSS selector (if available)
        instead of the element's own `CSS Selector`. If `Link on current page leading to this` is not provided, you should not include this element in `tour_selectors`.
        If you did not use any specific elements from the provided context, this array should be empty (`[]`).

    Example of desired JSON output:
    ```json
    {{
        "answer": "The main section regarding product details is located at the top of the page. More info: [https://example.com/products]",
        "tour_selectors": [".product-info-heading", "#product-description", ".link-to-products-page-on-current-page"]
    }}
    ```

    User Query: {user_query}
    Expanded User Query: {expanded_query}

    Retrieved Elements from the Webpage (Current Page ID: {current_page_id}):
    {context_str}

    Based on the above, answer the User Query concisely and accurately, always returning the response in the specified JSON format.
    Note that Children is the direct context under one element, Father is what is over the element and Brothers are the elements that are close to the element, but not under it.
    """
    return prompt

# Manda il prompt al modello GPT ed elabora una risposta effettiva sia per il modulo testuale che visivo, si aspetta un JSON dal modello
def gpt_query(prompt: str) -> dict:
    try:
        # settaggio del modello
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an AI assistant that answers questions about webpage content. Always provide your response in a JSON format."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
            response_format={"type": "json_object"} # forziamo una risposta JSON come atteso
        )
        full_response_content = response.choices[0].message.content.strip()
        parsed_data = json.loads(full_response_content) # conversione da JSON ad oggetto Python
        answer = parsed_data.get("answer", "I'm sorry, I couldn't provide a clear answer based on the information available.") # mette come default se non trova risposta I'm sorry, I couldn't provide a clear answer based on the information available
        tour_selectors = parsed_data.get("tour_selectors", []) # mette come default un array vuoto, nel caso appunto non siano stati trovati i tour_selectors
        # tour_selectors deve essere una lista
        if not isinstance(tour_selectors, list):
            logging.warning(f"GPT returned non-list tour_selectors: {tour_selectors}. Defaulting to empty list.")
            tour_selectors = []
        return {"answer": answer, "tour_selectors": tour_selectors}
    except json.JSONDecodeError as e:
        logging.error(f"Failed to decode JSON from GPT response: {e}\nResponse: {full_response_content}")
        return {"answer": "I'm sorry, there was an issue parsing the response from the AI.", "tour_selectors": []}
    except Exception as e:
        logging.error(f"Error calling GPT API: {e}")
        return {"answer": "I'm sorry, I couldn't process your request at the moment.", "tour_selectors": []}
