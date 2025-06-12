import time
from functools import wraps
import nltk
from nltk.corpus import wordnet
from selenium.webdriver.common.by import By

# Funzione per lo split degli elementi con troppo contesto
def split_text(text, target=25, merge_threshold=6):
    """
    Spezzetta il testo in chunk con target di ~18 parole.
    - Se il chunk finale ha meno di 'merge_threshold' parole, lo unisce al chunk precedente.
    - Altrimenti, lo lascia separato anche se ha meno di 12 parole.
    """
    words = text.split()
    # Se il testo totale è breve, non spezzettiamo
    if len(words) <= target:
        return [text]
    
    chunks = []
    i = 0
    while i < len(words):
        remaining = len(words) - i
        if remaining < target:
            # Se il chunk finale ha poche parole, controlla se va unito
            if chunks and remaining < merge_threshold:
                chunks[-1] = chunks[-1] + " " + " ".join(words[i:])
            else:
                chunks.append(" ".join(words[i:]))
            break
        else:
            chunk = " ".join(words[i:i+target])
            chunks.append(chunk)
            i += target
    return chunks


# Funzione di testing per misurare la quantita' di tempo richiesta per il completamento di una funzione 
def timing_decorator(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        print(f"{func.__name__} ha impiegato {end_time - start_time:.4f} secondi")
        return result
    return wrapper

# Funzione di arricchimento della query dell'utente utilizzando nltk
def expand_query(query, weight=2):
    # tokenizza la query
    tokens = nltk.word_tokenize(query)
    # crea lista che contiene i token originali ripetuti per dare loro maggiore peso
    expanded_list = tokens * weight  # ripete i termini originali 'weight' volte in base a quanto peso voglio dare alla query "originale"
    # Espande ogni token con i suoi sinonimi
    for token in tokens:
        for syn in wordnet.synsets(token, lang='eng'):
            for lemma in syn.lemmas():
                term = lemma.name().replace('_', ' ')
                # Aggiunge il termine solo se non contiene il token originale
                if token.lower() not in term.lower():
                    expanded_list.append(term)               
    # rimuovoe duplicati mantenendo l'ordine
    from collections import OrderedDict
    final_terms = list(OrderedDict.fromkeys(expanded_list))
    return " ".join(final_terms)

# Funzione che definisce se un elemento sia o meno una login form
def is_login_form(element):
    has_email_or_username = element.find_elements(By.XPATH, ".//input[@type='email']") or \
                             element.find_elements(By.XPATH, ".//input[@type='text' and (contains(translate(@name, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'email') or contains(translate(@name, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'user'))]")
    has_password = element.find_elements(By.XPATH, ".//input[@type='password']")
    login_keywords = ["login", "log in", "sign in", "accedi", "entra"]
    login_button = [
        btn for btn in element.find_elements(By.XPATH, ".//button | .//input[@type='submit']")
        if any(kw in (btn.text or btn.get_attribute("value") or "").lower() for kw in login_keywords)
    ]
    return (has_email_or_username and has_password) or (has_password and login_button)

# Genera l'intro in base alle informazioni dell'elemento, quindi tag, classe ecc
def generate_intro(element_info):
    tag = element_info.get("tag", "")
    classes = element_info.get("CSSSelector", "")
    text = element_info.get("enrichedtext", "").strip()
    print (tag)
    if tag == "button" or "btn" in classes:
        return f'Clicca il pulsante "{text}" per continuare' if text else "Clicca questo pulsante per procedere."
    elif tag == "input":
        input_type = element_info.get("type", "text")
        print(input_type)
        if input_type == "email":
            return "Inserisci il tuo indirizzo email in questo campo."
        elif input_type == "password":
            return "Inserisci la tua password in questo campo."
        else:
            return "Compila questo campo."
    elif tag == "a":
        return f"Clicca il link \"{text}\" per navigare." if text else "Clicca questo link."
    else:
        return f"Questa sezione mostra: {text}" if text else "Guarda questa sezione."
