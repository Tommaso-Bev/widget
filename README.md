prerequisito l'install di docker desktop per creare il container con pgvector
----
librerie:
pip install -r requirements.txt
pip install uvicorn
----
per creare il docker:
docker run -d --name postgres-vector -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=provatesting -e POSTGRES_DB=database -p 5432:5432 ankane/pgvector
nella console in docker desktop del conainer postgres-vector:
psql -U postgres -d database
CREATE EXTENSION vector;
----
nella cartella backend tramite cmd:
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
nella cartella frontend tramite cmd:
python -m http.server 8000
----
nella console del sito in cui iniettiamo il js:
(async () => {
  // CSS e JS statici
  const style = document.createElement('link');
  style.rel = 'stylesheet';
  style.href = 'http://localhost:8000/style.css';
  document.head.appendChild(style);

  const introjs = document.createElement('link');
  introjs.rel = 'stylesheet';
  introjs.href = 'https://unpkg.com/intro.js/minified/introjs.min.css';
  document.head.appendChild(introjs);

  const script = document.createElement('script');
  script.src = 'http://localhost:8000/chatbot-widget.js';
  document.body.appendChild(script);

  const introjsscr = document.createElement('script');
  introjsscr.src = 'https://unpkg.com/intro.js/minified/intro.min.js';
  document.body.appendChild(introjsscr);
})();
