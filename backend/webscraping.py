import time
from urllib.parse import urljoin, urlparse
import psycopg2
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from utilities import timing_decorator
from sentence_transformers import SentenceTransformer
import RAG_functions
import utilities
import logging

# Connessione al database PostgreSQL
conn = psycopg2.connect(
    dbname="database",
    user="postgres",
    password="provatesting",
    host="localhost",
    port="5432"
)
cursor = conn.cursor()
# Quantita' di elementi necessari per effettuare l'inserimento nella tabella di scraping
commit_counter = 0
commit_threshold = 50  # fai commit ogni 50 operazioni

# Classe che definisce tutti gli attributi e le azioni del crawler, che ricorsivamente puo' estrarre le informazioni di tutto un sito
class SiteCrawler:
    
    # Costruttore
    def __init__(self, driver, base_url, conn, cursor, max_pages=500, max_depth=500, delay=1.0):
        self.driver = driver
        self.base_url = base_url
        self.base_domain = urlparse(base_url).netloc
        self.max_pages = max_pages
        self.delay = delay
        self.conn = conn
        self.cursor = cursor
        self.max_depth=max_depth
        self.seen_urls = set()
        
    # Funzione che inserisce all'interno della tabella delle pagine quella da indagare, indicando url, livello (profondita') e selettore di CSS
    def enqueue_page(self, url, depth, css=None):
        if url in self.seen_urls:
            return
        if depth>self.max_depth:
            logging.info(f"Skipping {url} due to max depth ({depth} > {self.max_depth})")
            return
        self.seen_urls.add(url)
        try:
            self.cursor.execute(
                'INSERT INTO Pages (URL, Depth, SourceLinkCSS) VALUES (%s, %s, %s) ON CONFLICT (URL) DO UPDATE SET Depth = EXCLUDED.Depth',
                (url, depth, css)
            )
            self.conn.commit()
        except Exception as e:
            logging.warning(f"Errore enqueue_page {url}: {e}")

    # Funzione che seleziona tutti gli attributi necessari per il crawl dalla tabella delle pagine 
    def dequeue_page(self):
        self.cursor.execute('SELECT PageID, URL, Depth FROM Pages WHERE Visited=FALSE LIMIT 1')
        return self.cursor.fetchone()

    # Funzione per evidenziare se una pagina sia stata visitata o meno
    def mark_visited(self, page_id):
        self.cursor.execute('UPDATE Pages SET Visited=TRUE WHERE PageID=%s', (page_id,))
        self.conn.commit()

    # Funzioni per gli url
    def is_internal(self, href):
        return urlparse(urljoin(self.base_url, href)).netloc == self.base_domain # controlla se sia presente o meno all'interno dell'url un href
    def normalize(self, href):
        return urljoin(self.base_url, href.split('#')[0]) # converte in url assoluto

    # Funzione per svolgere l'effettivo crawl del sito
    def crawl(self):
        self.enqueue_page(self.base_url, 0, None)
        count = 0
        while count < self.max_pages:
            row = self.dequeue_page()
            if not row:
                break
            pid, url, current_depth = row
            logging.info(f"Pageid: {pid} with url: {url} at depth: {current_depth}")
            try:
                self.driver.get(url)
                WebDriverWait(self.driver, 10).until(lambda d: d.execute_script("return document.readyState")=='complete')
                time.sleep(self.delay)
                body = self.driver.find_element(By.TAG_NAME, 'body')
                logging.info(f"Pageid che metto dentro parse_node: {pid}")
                parse_node(self.driver, body, [None], pid=pid)
                update_children_in_database()
                self.mark_visited(pid)
                count += 1
                if current_depth < self.max_depth:
                    logging.info(f"Extracting links from {url} (Depth: {current_depth})")
                    for a in self.driver.find_elements(By.XPATH, "//a[@href and not(ancestor::details)]"):
                        href = a.get_attribute('href')
                        if href and self.is_internal(href):
                            normalized_href = self.normalize(href)
                            # prende il selettore di CSS dell'attuale tag <a> element
                            try:
                                a_css_selector = get_css_selector(self.driver, a)
                            except Exception as css_e:
                                logging.warning(f"Could not get CSS selector for link {href}: {css_e}. Enqueuing without it.")
                                a_css_selector = None
                            # Enqueue della nuova pagina con profondita' incrementata
                            self.enqueue_page(normalized_href, current_depth + 1, a_css_selector)
            except Exception as e:
                logging.error(f"Errore crawling {url}: {e}")
                self.mark_visited(pid)
                continue

# Funzione per verificare se l'elemento sia nascosto tramite la presenza di attributi specifici per la visibilita'
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
def insert_node(driver, tag_name, text, parent_ids, element=None, pid=None):
    global commit_counter
    text = text or ""
    is_hidden = False
    css = None
    if element:
        # verifica visibilita (veramente poco funzionante)
        if is_element_hidden_selenium(driver, element):
            is_hidden = True
        if text:
            css = get_css_selector(driver, element) # calcolo del selettore di CSS
        parent_id_str = " ".join(str(x) if x is not None else "0" for x in parent_ids)
        # inserimento nel database
        cursor.execute(
            """
            INSERT INTO HTMLTree (Tag, TextContent, ParentIDs, Hidden, CSSSelector, PageID) 
            VALUES (%s, %s, %s, %s, %s, %s) 
            RETURNING ID
            """,
            (tag_name, text, parent_id_str, is_hidden, css, pid)
        )
        node_id_result = cursor.fetchone()
        node_id = node_id_result[0] if node_id_result else None
        # viene fatto il commit solo se possiamo farlo in una batch di 50 elementi
        commit_counter+=1
        if commit_counter>=commit_threshold:
            conn.commit()
            commit_counter=0
        return node_id

# Funzione per estrapolare il testo dall'elemento
def get_direct_text(driver, element):
    script = """
    return Array.from(arguments[0].childNodes)
      .filter(node => node.nodeType === Node.TEXT_NODE)
      .map(node => node.textContent.trim())
      .join(" ");
    """
    return driver.execute_script(script, element).strip()

# Funzione per estrapolare ricorsivamente gli elementi all'interno dell'html posseduto
def parse_node(driver, element, parent_ids=[None], control_flag=True, pid=None):
    flag=True
    current_parent_ids = parent_ids
    # Se l'elemento e' gia' stato processato si passa avanti
    if element.get_attribute("data-processed") == "true":
        return
    # accortezze in base a tag e metadati
    if element: 
        tag = element.tag_name.lower()
        text = get_direct_text(driver, element)
        if text == "None":
            text = None
        elif text is not None and len(text) == 0:
            text = None # set del testo quando non ha contesto a NULL invece che a "" oppure "None" 
        # gestione per il tag <ul>
        if tag == "ul":
            li_elements = element.find_elements(By.XPATH, "./li")
            for li in li_elements:
                # ottiene tutti i discendenti in una sola volta
                all_descendants = li.find_elements(By.XPATH, ".//*")
                significant_children = []
                for child in all_descendants:
                    child_tag = child.tag_name.lower()
                    if child_tag in ["a", "b", "span", "p", "h1", "h2", "h3", "div"]:
                        child_text = child.get_attribute("innerText")
                        if not child_text or not child_text.strip():
                            continue
                        grand_children = child.find_elements(By.XPATH, "./*")
                        has_textual_grandchild = any(
                            gc.get_attribute("innerText") and gc.get_attribute("innerText").strip()
                            for gc in grand_children
                        )
                        if not has_textual_grandchild:
                            significant_children.append(child)
                if significant_children:
                    significant_child = significant_children[0]
                    significant_text = significant_child.get_attribute("innerText").strip()
                    parent_node_id = insert_node(
                        driver,
                        significant_child.tag_name.lower(),
                        significant_text,
                        parent_ids,
                        element=li,
                        pid=pid
                    )
                    # segna il nodo come già processato
                    driver.execute_script('arguments[0].setAttribute("data-processed", "true")', significant_child)
                    # processa i figli diretti del <li> se non già processati
                    children = li.find_elements(By.XPATH, "./*")
                    for child in children:
                        if child.get_attribute("data-processed") != "true":
                            parse_node(driver, child, parent_ids + [parent_node_id], control_flag=False, pid=pid)
                else:
                    parse_node(driver, li, parent_ids, control_flag=False, pid=pid)

            return
        
        # gestione per il tag <img>
        if tag == "img":
            src = element.get_attribute("src")
            if src:
                insert_node(driver, "img", f"Image source: {src}", parent_ids, element=element, pid=pid)
            return
        
        # gestione per il tag <p>
        if tag == "p":
            links = element.find_elements(By.TAG_NAME, "a")  # trova tutti i link all'interno del <p>
            full_text = element.text.strip()
            # sostituisce ogni link con il formato corretto all'interno del testo
            for a in links:
                link_text = a.text.strip()
                href = a.get_attribute("href")
                if link_text:
                    full_text = full_text.replace(link_text, f"{link_text} ({href})")
                else:
                    full_text = full_text.replace(href, f"({href})")
            text = full_text
            
        # gestione per il tag <form>
        if tag == "form":
            # estrae gli attributi del form
            action = element.get_attribute("action")
            method = element.get_attribute("method")
            form_description = f"Form detected (method={method or 'GET'}, action={action or 'N/A'})"
            parent_node_id = insert_node(driver, "form", form_description, parent_ids, element=element, pid=pid)
            # pre-mappa delle label con attributo for (una sola find_elements per tutto il form)
            label_map = {
                lbl.get_attribute("for"): lbl.text.strip()
                for lbl in element.find_elements(By.XPATH, ".//label[@for]")
                if lbl.get_attribute("for")
            }
            # processa tutti gli elementi di input
            input_elements = element.find_elements(By.XPATH, ".//input | .//button | .//textarea | .//select")
            for input_el in input_elements:
                input_tag = input_el.tag_name.lower()
                # preleva tutti gli attributi utili in un colpo solo
                attrs = {
                    "type": input_el.get_attribute("type") or "",
                    "name": input_el.get_attribute("name") or "",
                    "id": input_el.get_attribute("id") or "",
                    "class": input_el.get_attribute("class") or "",
                    "placeholder": input_el.get_attribute("placeholder") or "",
                    "value": input_el.get_attribute("value") or "",
                    "aria-label": input_el.get_attribute("aria-label") or "",
                    "title": input_el.get_attribute("title") or "",
                }
                label_text = label_map.get(attrs["id"], "")
                # costruzione della descrizione
                field_desc = f"{input_tag.upper()} field"
                if attrs["type"]:
                    field_desc += f" (type={attrs['type']})"
                if label_text:
                    field_desc += f" labeled '{label_text}'"
                elif attrs["aria-label"]:
                    field_desc += f" labeled '{attrs['aria-label']}'"
                elif attrs["title"]:
                    field_desc += f" titled '{attrs['title']}'"
                elif attrs["placeholder"]:
                    field_desc += f" with placeholder '{attrs['placeholder']}'"
                if attrs["name"]:
                    field_desc += f", name='{attrs['name']}'"
                if utilities.is_login_form(element):
                    field_desc = "This is a login signin form " + field_desc
                insert_node(driver, input_tag, field_desc, parent_ids + [parent_node_id], element=input_el, pid=pid)
            return
        
        if control_flag:
            if text is not None or len(element.find_elements(By.XPATH, "./*")) > 0:
                node_id = insert_node(driver, tag, text, parent_ids, element=element, pid=pid)
                current_parent_ids = parent_ids + [node_id]

        # parsing ricorsivo dei figli per tutti gli altri nodi "non particolari"
        for child in element.find_elements(By.XPATH, "./*"):
            parse_node(driver, child, current_parent_ids, flag, pid=pid)

# Funzione per aggiornare i figli, in precedenza salvati come None (serve che la tabella della pagina sia stata già estratta per discernere i figli)
def update_children_in_database():
    cursor.execute("SELECT ID, ParentIDs FROM HTMLTree")
    nodes = cursor.fetchall()
    parent_map = {}
    for node_id, parent_ids in nodes:
        # se parent_ids e' None o vuoto, lo sostituisco con "0" (per evitare problemi con PostgreSQL)
        if not parent_ids or not parent_ids.strip():
            parent_ids = "0"
        for parent_id in parent_ids.split():
            if parent_id not in parent_map:
                parent_map[parent_id] = []
            parent_map[parent_id].append(node_id)
    for parent_id, children in parent_map.items():
        children_str = " ".join(map(str, children))
        try:
            parent_id_int = int(parent_id)  # converte in intero
        except ValueError:
            continue
        cursor.execute(
            "UPDATE HTMLTree SET Children = %s WHERE ID = %s RETURNING ID",
            (children_str, parent_id_int)
        )
        result = cursor.fetchone()
    conn.commit()

# Funzione per eliminare tutti quegli elementi che possiedono stesso textcontent, cssselector e tag
def delete_duplicate_html_nodes():
    try:
        # questa query identifica i duplicati utilizzando tag, contenuto e selettore di CSS e poi lascia unicamente quello con l'ID della pagina inferiore
        cursor.execute("""
            DELETE FROM HTMLTree
            WHERE ID IN (
                SELECT ID
                FROM (
                    SELECT
                        ID,
                        ROW_NUMBER() OVER (
                            PARTITION BY Tag, TextContent, CSSSelector
                            ORDER BY PageID ASC, ID ASC
                        ) as rn
                    FROM HTMLTree
                ) AS subquery
                WHERE subquery.rn > 1
            );
        """)
        conn.commit()
        logging.info("Duplicate HTMLTree nodes removed successfully, keeping the one with the lowest PageID and then lowest ID.")
    except psycopg2.Error as e:
        logging.error(f"Error deleting duplicate HTMLTree nodes: {e}")
        conn.rollback() # rollback se da' errore

# Funzione per far partire il crawl del sito
@timing_decorator
def starting_webscraping(driver, url):
    # drop delle tabelle cosi' da poterle rigenerare
    cursor.execute("DROP TABLE IF EXISTS HTMLTree")
    conn.commit()
    cursor.execute("DROP TABLE IF EXISTS Pages")
    conn.commit()
    # creazione della tabella dello scraping
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS HTMLTree (
        ID SERIAL PRIMARY KEY,
        Tag TEXT NOT NULL,
        TextContent TEXT,
        ParentIDs TEXT,
        Children TEXT,
        Hidden Boolean,
        CSSSelector TEXT,
        PageID INT
    )
    """)
    conn.commit()
    # creazione della tabella delle pagine
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS Pages (
        PageID SERIAL PRIMARY KEY,
        URL TEXT UNIQUE NOT NULL,
        Visited BOOLEAN DEFAULT FALSE,
        Depth INT DEFAULT 0,
        SourceLinkCSS TEXT
    );
    """)
    # impostazione del numero massimo di pagine e di livelli da estrarre 
    max_pages=2
    max_depth=2
    
    # mette un timer per far si' che la pagina sia completamente caricata cosi' da far partire le operazioni quando tutto e' presente
    WebDriverWait(driver, 10).until(
        lambda driver: driver.execute_script("return document.readyState") == "complete"
    )
    
    # crawl del sito
    crawler=SiteCrawler(driver, url, conn, cursor, max_pages=max_pages, max_depth=max_depth, delay=1.0)
    crawler.crawl()
    delete_duplicate_html_nodes()
    # utilizziamo 'all-mpnet-base-v2' come embedder
    embedder = SentenceTransformer('all-mpnet-base-v2')
    RAG_functions.create_rag_nodes(embedder)

# Funzione per ottenere il selettore di CSS dell'elemento 
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


