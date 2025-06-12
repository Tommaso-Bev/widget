import utilities
import psycopg2
import numpy as np
from utilities import timing_decorator

# Massimo e minimo della grandezza dei chunk
Maximum=50
Minimum=30

# Connesione al database PostgreSQL
conn = psycopg2.connect(
    dbname="database",
    user="postgres",
    password="provatesting",
    host="localhost",
    port="5432"
)
cursor = conn.cursor()

# Recupera i figli diretti del nodo (che abbiano del contesto)
def get_child_texts_stop_at_first(node_id, nodes_cache):
    queue = [node_id]  # inizializza la coda con il nodo di partenza
    selected_children = []  # lista per i figli con testo
    while queue:
        current_id = queue.pop(0)  # prende il primo nodo dalla coda
        children_str = nodes_cache.get(int(current_id), {}).get("children")  # recupera i figli
        if children_str:
            child_ids = children_str.split()    
            for child_id in child_ids:
                child_text = nodes_cache.get(int(child_id), {}).get("text")
                if child_text:  
                    # se il figlio ha testo, lo aggiungiamo e NON esploriamo i suoi figli
                    selected_children.append(f"{child_id}: {child_text}")
                else:
                    # se non ha testo, continuiamo a cercare nei suoi figli
                    queue.append(child_id)
    return f" |CHILDREN: {' |'.join(selected_children)}" if selected_children else ""

# Funzione per arricchire i nodi seguendo l'approccio RAG aggiungendo informazioni relative al contesto limitrofo
def get_enriched_text_sections(node_id, text, parent_ids, children_str, nodes_cache):
    enriched = {"MAIN": text}

    # aggiunge il contesto limitrofo del PARENT con contesto
    if parent_ids and parent_ids.strip() and parent_ids.strip() != "0":
        for parent_id in reversed(parent_ids.split()):
            p_text = nodes_cache.get(int(parent_id), {}).get("text")
            if p_text:
                enriched["PARENT"] = p_text
                break
    # aggiunge il contesto limitrofo del CHILDREN con contesto
    if children_str and children_str.strip():
        children_info = get_child_texts_stop_at_first(node_id, nodes_cache)
        if children_info:
            enriched["CHILDREN"] = children_info.replace(" |CHILDREN: ", "")
    # aggiunge il contesto limitrofo del BROTHER con contesto
    if parent_ids and parent_ids.strip() and parent_ids.strip() != "0":
        for candidate_parent in reversed(parent_ids.split()):
            siblings_str = nodes_cache.get(int(candidate_parent), {}).get("children")
            if siblings_str:
                siblings_ids = [sib for sib in siblings_str.split() if str(sib) != str(node_id)]
                siblings_texts = []
                for sib in siblings_ids:
                    sib_text = nodes_cache.get(int(sib), {}).get("text")
                    if sib_text:
                        siblings_texts.append(sib_text)
                if siblings_texts:
                    enriched["BROTHERS"] = " ".join(siblings_texts)
                    break
    return enriched

# Funzione per la creazione vera e propria del database RAG utilizzando le funzioni soprastanti
@timing_decorator
def create_rag_nodes(embedder):
    cursor.execute("DROP TABLE IF EXISTS RAG_HTMLTree")
    conn.commit()
    cursor.execute("""
        SELECT ID, TextContent, ParentIDs, Children, CSSSelector, Tag, PageID
        FROM HTMLTree 
    """)
    nodes = cursor.fetchall()
    # cache per fare l'accesso una sola volta al database
    nodes_cache = {
        int(row[0]): {
            "text": row[1],
            "parent_ids": row[2],
            "children": row[3],
            "css":row[4],
            "tag":row[5],
            "page_id":row[6]
        }
        for row in nodes
    }
    # cache per le pagine (ID e selettore CSS dell'elemento hyperlink)
    page_link_css_cache = {}
    cursor.execute("SELECT PageID, SourceLinkCSS FROM Pages")
    for page_id, source_link_css in cursor.fetchall():
        page_link_css_cache[page_id] = source_link_css
        
    # creazione della tabella RAG    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS RAG_HTMLTree (
        ID SERIAL PRIMARY KEY,
        SourceID INTEGER,
        Tag TEXT,
        EnrichedText TEXT,
        embedding vector(768),
        CSSSelector TEXT,
        PageID INTEGER,
        SourceLinkCSS TEXT
    )
    """)
    conn.commit()
    
    # pesi specifici per il calcolo dell'embedding delle varie sezioni del nodo    
    weights = {
    "MAIN": 1.0,
    "PARENT": 0.5,
    "CHILDREN": 0.4,
    "BROTHERS": 0.3
    }   
    
    # calcolo pesato embedding ed inserimento all'interno della tabella RAG
    for node_id, node_data in nodes_cache.items():
        text = node_data.get("text", "") 
        if text:
            parent_ids = node_data.get("parent_ids", "")
            children_str = node_data.get("children", "")
            css=node_data.get("css", "")
            tag=node_data.get("tag", "")
            page_id = node_data.get("page_id")
            source_link_css = page_link_css_cache.get(page_id)
            enriched_sections = get_enriched_text_sections(node_id, text, parent_ids, children_str, nodes_cache)
            combined_embedding = np.zeros(embedder.get_sentence_embedding_dimension())
            total_weight = 0.0
            for section, content in enriched_sections.items():
                section_embedding = embedder.encode(content)
                weight = weights.get(section, 0.0)
                combined_embedding += np.array(section_embedding) * weight
                total_weight += weight
            if total_weight > 0:
                combined_embedding /= total_weight
            full_text = " |".join([f"{k}: {v}" for k, v in enriched_sections.items()])
            cursor.execute("""
                INSERT INTO RAG_HTMLTree (SourceID, Tag, EnrichedText, embedding, CSSSelector, PageID, SourceLinkCSS) 
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (node_id, tag, full_text, combined_embedding.tolist(), css, page_id, source_link_css))
            conn.commit()
            
# Retrieval dei nodi a partire dalla query dell'utente, la quale viene estesa tramite nltk e successivamente fatta la ricerca per somiglianza nella tabella
@timing_decorator
def RAG_retrieval(embedder, query_text, top_k=10):
    enriched = utilities.expand_query(query_text)
    query_embedding = embedder.encode(enriched).tolist()
    embedding_str = f"'[{', '.join(map(str, query_embedding))}]'::vector"
    # join con la raccolta di pagine per accedere all'url della pagina
    cursor.execute(f"""
        SELECT 
            rh.SourceID, 
            rh.Tag, 
            rh.EnrichedText, 
            1 - (rh.embedding <=> {embedding_str}) AS similarity, 
            rh.CSSSelector, 
            rh.PageID, 
            rh.SourceLinkCSS,
            p.URL AS PageURL -- Get the URL from the Pages table
        FROM RAG_HTMLTree rh
        JOIN Pages p ON rh.PageID = p.PageID -- Join on PageID
        WHERE rh.EnrichedText IS NOT NULL AND rh.EnrichedText != '' 
        ORDER BY similarity DESC
        LIMIT {top_k}
    """)
    results = cursor.fetchall()
    columns = ["source_id", "tag", "enriched_text", "similarity", "cssselector", "page_id", "source_link_css", "page_url"]
    print(dict(zip(columns, row)) for row in results)
    return [dict(zip(columns, row)) for row in results]