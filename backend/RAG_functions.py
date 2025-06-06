import utilities
import psycopg2
import numpy as np
from utilities import timing_decorator


conn = psycopg2.connect(
    dbname="database",
    user="postgres",
    password="provatesting",
    host="localhost",
    port="5432"
)

cursor = conn.cursor()

cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
#384 per embedder mini 768 per l'altro embedder

Maximum=50
Minimum=30

def get_enriched_text(node_id, text, parent_ids, children_str, nodes_cache):
    """
    Arricchisce il testo seguendo questa logica:
      - Se il testo ha tra 30 e 50 parole, lo restituisce così com'è.
      - Se il testo è troppo corto (<30 parole):
          1. Aggiunge il testo del padre (se esiste).
          2. Se ancora insufficiente, aggiunge il testo dei figli.
          3. Se ancora insufficiente, itera sui padri (dal più immediato a quelli superiori)
             e aggiunge il testo dei fratelli (ossia altri nodi che condividono quell'antenato),
             evitando duplicazioni della sezione "fratelli".
      - Se il testo (o quello arricchito) supera le 50 parole, lo spezza in chunk.
    Restituisce una lista di stringhe.
    """
    def count_words(s):
        return len(s.split())
    
    enriched = f"MAIN: {text} |MAIN_R: {text}"
    # Caso base: se il testo ha già tra 12 e 16 parole, lo usiamo così com'è
    if Minimum <= count_words(enriched) <= Maximum:
        return [enriched]
    
    
    # 1. Aggiungi il testo del padre (prendiamo l'ultimo elemento di ParentIDs)
    if parent_ids and parent_ids.strip() and parent_ids.strip() != "0":
        parent_list = parent_ids.split()
        for parent_id in reversed(parent_list):
            p_text=nodes_cache.get(int(parent_id),{}).get("text")
            if p_text is not None and p_text!='':
                enriched += f" |PARENT: {parent_id}: {p_text}"
                break
    
    # 2. Se ancora insufficiente, aggiungo il testo dei figli
    if count_words(enriched) < Minimum and children_str and children_str.strip():
        children_info = get_child_texts_stop_at_first(node_id, nodes_cache)
        if children_info:
            enriched += children_info

    
    # 3. Se il testo è ancora troppo corto, cerca il primo padre con fratelli con testo e interrompi
    if count_words(enriched) < Minimum and parent_ids and parent_ids.strip() and parent_ids.strip() != "0":
        parent_list = parent_ids.split()

        # Iteriamo in ordine inverso (dal padre immediato all'antenato più remoto)
        for candidate_parent in reversed(parent_list):
            siblings_str = nodes_cache.get(int(candidate_parent), {}).get("children")  # Recupera i figli del padre
            counter=count_words(enriched)
            if siblings_str:
                siblings_ids = [sib for sib in siblings_str.split() if str(sib) != str(node_id)]
                siblings_texts = []
                
                for sib in siblings_ids:
                    if counter <= Maximum:
                        sib_text = nodes_cache.get(int(sib), {}).get("text")  # Prende il testo del fratello
                        
                        if sib_text and count_words(enriched+f"{sib}: {sib_text}")<Maximum:  
                            siblings_texts.append(f"{sib}: {sib_text}")
                            counter+=count_words(f"{sib}: {sib_text}")
    
                if siblings_texts:
                    # Appena troviamo un padre con fratelli con testo, li aggiungiamo e ci fermiamo
                    enriched += " |BROTHERS: " + " |".join(siblings_texts)
                    break  # Interrompiamo subito la ricerca dopo il primo trovato
                
    return [enriched]

def get_enriched_text_sections(node_id, text, parent_ids, children_str, nodes_cache):
    enriched = {"MAIN": text}

    if parent_ids and parent_ids.strip() and parent_ids.strip() != "0":
        for parent_id in reversed(parent_ids.split()):
            p_text = nodes_cache.get(int(parent_id), {}).get("text")
            if p_text:
                enriched["PARENT"] = p_text
                break

    if children_str and children_str.strip():
        children_info = get_child_texts_stop_at_first(node_id, nodes_cache)
        if children_info:
            enriched["CHILDREN"] = children_info.replace(" |CHILDREN: ", "")

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


@timing_decorator
def create_rag_nodes(embedder):
    """
    Itera sui nodi della tabella HTMLTree che hanno del testo e li elabora
    per creare le entry arricchite nella tabella RAG_HTMLTree.
    """
    cursor.execute("DROP TABLE IF EXISTS RAG_HTMLTree")
    conn.commit()
    
    cursor.execute("""
        SELECT ID, TextContent, ParentIDs, Children, XPath, CSSSelector, Tag
        FROM HTMLTree 
    """)
    nodes = cursor.fetchall()
    
    
    # creo una cache così da dover fare l'accesso una sola volta in generale 
    nodes_cache = {
        int(row[0]): {
            "text": row[1],
            "parent_ids": row[2],
            "children": row[3],
            "xpath":row[4],
            "css":row[5],
            "tag":row[6]
        }
        for row in nodes
    }

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS RAG_HTMLTree (
        ID SERIAL PRIMARY KEY,
        SourceID INTEGER,
        Tag TEXT,
        EnrichedText TEXT,
        embedding vector(768),
        XPath TEXT,
        CSSSelector TEXT
    )
    """)
    conn.commit()
    
    # Accumulo tutti i dati da inserire
    enriched_texts_batch = []
    source_ids_batch = []
    xpaths_batch = []
    css_batch = []
    tag_batch = []   
     
    weights = {
    "MAIN": 1.0,
    "PARENT": 0.5,
    "CHILDREN": 0.4,
    "BROTHERS": 0.3
    }   
    
    for node_id, node_data in nodes_cache.items():
        text = node_data.get("text", "")
        
        if text:
            parent_ids = node_data.get("parent_ids", "")
            children_str = node_data.get("children", "")
            xpath = node_data.get("xpath", "")
            css=node_data.get("css", "")
            tag=node_data.get("tag", "")
            
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
                INSERT INTO RAG_HTMLTree (SourceID, Tag, EnrichedText, embedding, XPath, CSSSelector) 
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (node_id, tag, full_text, combined_embedding.tolist(), xpath, css))
            conn.commit()

@timing_decorator
def RAG_retrieval(embedder, query_text, top_k=10):
    enriched = utilities.expand_query(query_text)
    query_embedding = embedder.encode(enriched).tolist()
    embedding_str = f"'[{', '.join(map(str, query_embedding))}]'::vector"

    cursor.execute(f"""
        SELECT SourceID, Tag, EnrichedText, 1 - (embedding <=> {embedding_str}) AS similarity, CSSSelector
        FROM RAG_HTMLTree
        WHERE EnrichedText IS NOT NULL AND EnrichedText != ''
        ORDER BY similarity DESC
        LIMIT {top_k}
    """)

    results = cursor.fetchall()
    columns = ["source_id", "tag", "enriched_text", "similarity", "cssselector"]
    print(dict(zip(columns, row)) for row in results)
    return [dict(zip(columns, row)) for row in results]



def get_child_texts_stop_at_first(node_id, nodes_cache):
    """ Recupera i figli diretti di node_id e, se un figlio ha testo, non esplora i suoi figli. """
    queue = [node_id]  # Inizializza la coda con il nodo di partenza
    selected_children = []  # Lista per i figli con testo
    
    while queue:
        current_id = queue.pop(0)  # Prendi il primo nodo dalla coda
        children_str = nodes_cache.get(int(current_id), {}).get("children")  # Recupera i figli
        
        if children_str:
            child_ids = children_str.split()  # Lista di ID figli
            
            for child_id in child_ids:
                child_text = nodes_cache.get(int(child_id), {}).get("text")
                
                if child_text:  
                    # Se il figlio ha testo, lo aggiungiamo e NON esploriamo i suoi figli
                    selected_children.append(f"{child_id}: {child_text}")
                else:
                    # Se non ha testo, continuiamo a cercare nei suoi figli
                    queue.append(child_id)
    
    return f" |CHILDREN: {' |'.join(selected_children)}" if selected_children else ""