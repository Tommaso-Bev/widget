import requests
from openai import OpenAI
import prompt_gpo
import psycopg2
import faiss
import json
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import undetected_chromedriver as uc

from utilities import timing_decorator
from sentence_transformers import SentenceTransformer

import RAG_functions
import utilities

conn = psycopg2.connect(
    dbname="database",
    user="postgres",
    password="provatesting",
    host="localhost",
    port="5432"
)

cursor = conn.cursor()


def remove_empty_nodes():
    cursor.execute("""
        DELETE FROM HTMLTree WHERE TextContent IS NULL 
    """)
    conn.commit()

# Funzione per verificare se l'elemento è effettivamente nascosto con Selenium
def is_element_hidden_selenium(driver, element):
    try:
        return driver.execute_script(
            """
            var elem = arguments[0];
            var style = window.getComputedStyle(elem);
            return (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0');
            """,
            element
        )
    except Exception:
        return True
    
# Funzione per eseguire l'operazione di inserimento in database PostgreSQL
def insert_node(driver, tag_name, text, parent_ids, element=None):
    """
    Inserisce un nodo nella tabella HTMLTree. Se il contenuto è troppo lungo, 
    viene suddiviso in più nodi con un suffisso numerico.
    """
    
    # Variabili per l'operrazione di "spezzettamento"
    inserted_ids = [] 
    text = text or ""  # Evita None
    MAX_WORDS = 50
    words = text.split() if text.strip() else []
    chunks = [" ".join(words[i:i + MAX_WORDS]) for i in range(0, len(words), MAX_WORDS)] if words else [""]
    is_hidden=False
    xpath = None
    css=None
    
    # Operazione di verifica della visibilità, inizialmente tramite inline style, successivamente se non trova tramite selenium element.is_displayed()
    if element:
        # Verifica della visibilità tramite Selenium
        if not is_hidden and is_element_hidden_selenium(driver, element):
            is_hidden = True
            
        xpath = get_xpath(driver, element)
        css = get_css_selector(driver, element)
        
        
    # Questa parte di codice ha il compito di "spezzettare" i nodi che possiedono più di un tot di parole 
    for i, chunk in enumerate(chunks):
        # Calcolo del percorso
        if parent_ids:
            cursor.execute("SELECT Path FROM HTMLTree WHERE ID = %s", (parent_ids[-1],))
            parent_path = cursor.fetchone()
            if parent_path:
                cursor.execute("SELECT ID FROM HTMLTree WHERE Path = %s", (parent_path[0],))
                element_id = cursor.fetchone()
                if not chunk:
                    path = f"{parent_path[0]}" if element_id else f"{parent_path[0]}>tag no id"
                else:
                    path = f"{parent_path[0]}>{chunks[0]}"
            else:
                path = chunk if chunk else tag_name
        else:
            path = chunk if chunk else tag_name

        # Aggiungi suffisso numerico per le parti divise
        if len(chunks) > 1:
            path += f":{i+1}"

        # Inserisci nel database e ottieni l'ID
        cursor.execute(
            """
            INSERT INTO HTMLTree (Tag, Path, TextContent, ParentIDs, Hidden, XPath, CSSSelector) 
            VALUES (%s, %s, %s, %s, %s, %s, %s) 
            RETURNING ID
            """,
            (tag_name, path, chunk, " ".join(str(x) if x is not None else "0" for x in parent_ids), is_hidden, xpath, css)
        )
        
        node_id = cursor.fetchone()[0]
        # **Aggiorna il path con l'ID del nodo attuale**
        if not chunk and str(node_id) not in path.split(">"):
            new_path = f"{path}>{node_id}"
            cursor.execute("UPDATE HTMLTree SET Path = %s WHERE ID = %s", (new_path, node_id))
        inserted_ids.append(node_id)  # Salva l'ID per i nodi spezzettati

    conn.commit()

    return inserted_ids[0]  # Restituisce tutti gli ID creati

# Funzione per estrapolare il testo dall'elemento
def get_direct_text(driver, element):
    script = """
    return Array.from(arguments[0].childNodes)
      .filter(node => node.nodeType === Node.TEXT_NODE)
      .map(node => node.textContent.trim())
      .join(" ");
    """
    return driver.execute_script(script, element).strip()

def parse_node(driver, element, parent_ids=[None], control_flag=True):
    flag=True
    current_parent_ids = parent_ids
   
    # Se l'elemento è già stato processato si passa avanti
    if element.get_attribute("data-processed") == "true":
        return
    
    if element: 
        tag = element.tag_name.lower()
        # Estrai solo il testo diretto
        text = get_direct_text(driver, element)
        if text == "None":
            text = None
        elif text is not None and len(text) == 0:
            text = None
        
        
        # Gestione specifica per <ul>
        if tag == "ul":
            li_elements = element.find_elements(By.XPATH, "./li")
            for li in li_elements:
                # Descriviamo la lista di tutti i nodi all'interno del <li> che possiedono del testo
                significant_children = [
                    child for child in li.find_elements(By.XPATH, ".//*")
                    if child.tag_name in ["a", "b", "span", "p", "h1", "h2", "h3", "div"]
                    and child.get_attribute("innerText") and child.get_attribute("innerText").strip()  # Ignora vuoti
                    and not any(grandchild.get_attribute("innerText") and grandchild.get_attribute("innerText").strip() 
                                for grandchild in child.find_elements(By.XPATH, "./*"))
                ]
              
                if significant_children:
                    significant_child = significant_children[0]
                    significant_text = significant_child.get_attribute("innerText").strip()
                    parent_node_id = insert_node(driver, significant_child.tag_name.lower(), significant_text, parent_ids, element=li)
                    # Segna il nodo come già processato
                    driver.execute_script('arguments[0].setAttribute("data-processed", "true")', significant_child)

                    # Ora processa i figli, escludendo quelli già marcati
                    children = li.find_elements(By.XPATH, "./*")
                    for child in children:
                        if child.get_attribute("data-processed") != "true":
                            parse_node(driver, child, parent_ids + [parent_node_id], control_flag=False)
                else:
                    parse_node(driver, li, parent_ids, control_flag=False)

            return

        # Gestione per <img>
        if tag == "img":
            src = element.get_attribute("src")
            if src:
                insert_node(driver, "img", f"Image source: {src}", parent_ids, element=element)
            return

        if tag == "p":
            links = element.find_elements(By.TAG_NAME, "a")  # Trova tutti i link all'interno del <p>
            full_text = element.text.strip()

            # Sostituisce ogni link con il formato corretto all'interno del testo
            for a in links:
                link_text = a.text.strip()
                href = a.get_attribute("href")
                if link_text:
                    full_text = full_text.replace(link_text, f"{link_text} ({href})")
                else:
                    full_text = full_text.replace(href, f"({href})")

            text = full_text


        if tag == "form":
            # Estraggo gli attributi del form
            action = element.get_attribute("action")
            method = element.get_attribute("method")
            form_description = f"Form detected (method={method or 'GET'}, action={action or 'N/A'})"
            parent_node_id = insert_node(driver, "form", form_description, parent_ids, element=element)

            # Processo i campi interni
            input_elements = element.find_elements(By.XPATH, ".//input | .//button | .//textarea | .//select")
            for input_el in input_elements:
                input_tag = input_el.tag_name.lower()
                input_type = input_el.get_attribute("type") or ""
                input_name = input_el.get_attribute("name") or ""
                input_id = input_el.get_attribute("id") or ""
                input_class = input_el.get_attribute("class") or ""
                placeholder = input_el.get_attribute("placeholder") or ""
                value = input_el.get_attribute("value") or ""
                aria_label = input_el.get_attribute("aria-label") or ""
                title = input_el.get_attribute("title") or ""

                # Tentativo di estrarre label associata
                label_text = ""
                if input_id:
                    label_elements = element.find_elements(By.XPATH, f".//label[@for='{input_id}']")
                    if label_elements:
                        label_text = label_elements[0].text.strip()

                # Costruisci descrizione testuale utile per il RAG
                field_desc = f"{input_tag.upper()} field"
                if input_type:
                    field_desc += f" (type={input_type})"
                if label_text:
                    field_desc += f" labeled '{label_text}'"
                elif aria_label:
                    field_desc += f" labeled '{aria_label}'"
                elif title:
                    field_desc += f" titled '{title}'"
                elif placeholder:
                    field_desc += f" with placeholder '{placeholder}'"
                if input_name:
                    field_desc += f", name='{input_name}'"
                    
                if utilities.is_login_form(element):
                    field_desc= "This is a login signin form "+ field_desc
                # Inserisci nel DB
                insert_node(driver, input_tag, field_desc, parent_ids + [parent_node_id], element=input_el)

            return  # evita ulteriore parsing ricorsivo, già fatto sopra

            

        # Per altri tag, se l'elemento non ha figli e non possiede testo non ha senso salvarlo
        if control_flag:
            if text is not None or len(element.find_elements(By.XPATH, "./*")) > 0:
                node_id = insert_node(driver, tag, text, parent_ids, element=element)
                current_parent_ids = parent_ids + [node_id]

        # Parsing ricorsivo dei figli
        for child in element.find_elements(By.XPATH, "./*"):
            parse_node(driver, child, current_parent_ids, flag)

# Funzione per aggiornare i "figli" di tutti i nodi che sono preimpostati come None per tutti
def update_children_in_database():
    cursor.execute("SELECT ID, ParentIDs FROM HTMLTree")
    nodes = cursor.fetchall()
    parent_map = {}
    for node_id, parent_ids in nodes:
        # Se parent_ids è None o vuoto, lo sostituisco con "0" (per evitare problemi con PostgreSQL)
        if not parent_ids or not parent_ids.strip():
            parent_ids = "0"
        for parent_id in parent_ids.split():
            if parent_id not in parent_map:
                parent_map[parent_id] = []
            parent_map[parent_id].append(node_id)
            
    for parent_id, children in parent_map.items():
        children_str = " ".join(map(str, children))
        try:
            parent_id_int = int(parent_id)  # Converte in intero
        except ValueError:
            continue
        
        cursor.execute(
            "UPDATE HTMLTree SET Children = %s WHERE ID = %s RETURNING ID",
            (children_str, parent_id_int)

        )
        result = cursor.fetchone()
    conn.commit()

@timing_decorator
def starting_webscraping(driver, url):
    cursor.execute("DROP TABLE IF EXISTS HTMLTree")
    conn.commit()
    # Creazione della tabella con la colonna dei figli
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS HTMLTree (
        ID SERIAL PRIMARY KEY,
        Tag TEXT NOT NULL,
        TextContent TEXT,
        ParentIDs TEXT,
        Children TEXT,
        Path TEXT,
        Hidden Boolean,
        XPath TEXT,
        CSSSelector TEXT
    )
    """)
    conn.commit()
    
    
    # Opzioni Selenium per evitare vari problemi e settare a che grandezza viene aperta la pagina
    options=Options()
    options.add_argument("--headless") # Esegue senza aprire effettivamente il browser
    options.add_argument("--disable-gpu")  # Evita problemi grafici
    options.add_argument("--window-size=1920x1080")  # Simula schermo grande


    service = Service(ChromeDriverManager().install())
    # Metto un timer per far si che la pagina sia completamente caricata così da far partire le operazioni quando tutto è presente
    WebDriverWait(driver, 10).until(
        lambda driver: driver.execute_script("return document.readyState") == "complete"
    )
    
    driver.get(url)
    html=driver.page_source
    root = driver.find_element(By.TAG_NAME, "body")
    parse_node(driver, root)
    update_children_in_database()
    # Utilizziamo 'all-mpnet-base-v2' come embedder
    embedder = SentenceTransformer('all-mpnet-base-v2')
    RAG_functions.create_rag_nodes(embedder)


# Questo serve a ricavare l'XPATH assoluto degli elementi HTML, ma lo lascio perdere per vari motivi
def get_xpath(driver, element: WebElement) -> str:
    # Uso javascript per computare l'XPATH dell'elemento
    return driver.execute_script("""
        function absoluteXPath(element) {
            var comp, comps = [];
            var parent = null;
            var xpath = '';
            var getPos = function(element) {
                var position = 1, curNode;
                if (element.nodeType === Node.ATTRIBUTE_NODE) {
                    return null;
                }
                for (curNode = element.previousSibling; curNode; curNode = curNode.previousSibling){
                    if (curNode.nodeName === element.nodeName)
                        ++position;
                }
                return position;
            };

            if (element instanceof Document) {
                return '/';
            }

            for (; element && !(element instanceof Document); element = element.nodeType === Node.ATTRIBUTE_NODE ? element.ownerElement : element.parentNode) {
                comp = {};
                switch (element.nodeType) {
                    case Node.TEXT_NODE:
                        comp.name = 'text()';
                        break;
                    case Node.ATTRIBUTE_NODE:
                        comp.name = '@' + element.nodeName;
                        break;
                    case Node.PROCESSING_INSTRUCTION_NODE:
                        comp.name = 'processing-instruction()';
                        break;
                    case Node.COMMENT_NODE:
                        comp.name = 'comment()';
                        break;
                    case Node.ELEMENT_NODE:
                        comp.name = element.nodeName;
                        break;
                }
                comp.position = getPos(element);
                comps.push(comp);
            }

            for (var i = comps.length - 1; i >= 0; i--) {
                comp = comps[i];
                xpath += '/' + comp.name.toLowerCase();
                if (comp.position !== null && comp.position > 1)
                    xpath += '[' + comp.position + ']';
            }

            return xpath;
        }
        return absoluteXPath(arguments[0]);
    """, element)
    
    
def get_css_selector(driver, element):
    path = []
    current = element
    while current.tag_name.lower() != "html":
        tag = current.tag_name.lower()
        parent = current.find_element(By.XPATH, "..")
        siblings = parent.find_elements(By.XPATH, f"./{tag}")
        if len(siblings) > 1:
            index = siblings.index(current) + 1  # nth-of-type parte da 1
            path.insert(0, f"{tag}:nth-of-type({index})")
        else:
            path.insert(0, tag)
        current = parent
    return "html > " + " > ".join(path)


