import os
import json
import time
import requests
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# Configurazione da variabili d'ambiente
PORT = int(os.environ.get("PORT", 8080))
DEBUG = os.environ.get("DEBUG", "False").lower() == "true"
MODEL_API_URL = os.environ.get("MODEL_API_URL", "https://lordhenry-salesforce-agent.hf.space")
API_KEY = os.environ.get("API_KEY", "")  # Per sicurezza tra frontend e backend

# Inizializza FastAPI
app = FastAPI(title="Salesforce AI Assistant Frontend")

# Configurazione CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup dei template e file statici
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Modelli per le richieste e risposte
class QueryRequest(BaseModel):
    query: str
    type: str = "standard"  # "standard" o "complete"

class QueryResponse(BaseModel):
    query_id: str
    query: str
    response: str
    status: str

class FeedbackRequest(BaseModel):
    query_id: str
    rating: int
    feedback_text: Optional[str] = None

# Archiviazione in-memory per cronologia conversazioni
conversation_store = {}

# Gestione delle connessioni WebSocket
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        
        # Invia la cronologia dei messaggi se esiste
        if client_id in conversation_store:
            for message in conversation_store[client_id]:
                await websocket.send_json(message)

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]

    async def send_message(self, message: dict, client_id: str):
        # Aggiorna la cronologia
        if client_id not in conversation_store:
            conversation_store[client_id] = []
        
        conversation_store[client_id].append(message)
        
        # Limita la cronologia a 50 messaggi
        if len(conversation_store[client_id]) > 50:
            conversation_store[client_id] = conversation_store[client_id][-50:]
        
        # Invia il messaggio se il client è connesso
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_json(message)

manager = ConnectionManager()

# Funzione per chiamare l'API backend
def call_backend_api(endpoint, data=None, method="GET", timeout=60):
    """Chiama l'API backend"""
    # Assicurati che MODEL_API_URL non termini con uno slash
    base_url = MODEL_API_URL.rstrip('/')
    
    # Assicurati che endpoint inizi con uno slash
    endpoint_path = f"/{endpoint.lstrip('/')}"
    
    url = f"{base_url}{endpoint_path}"
    
    headers = {}
    
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    
    try:
        if method == "GET":
            response = requests.get(url, headers=headers, timeout=timeout)
        elif method == "POST":
            headers["Content-Type"] = "application/json"
            response = requests.post(url, headers=headers, json=data, timeout=timeout)
        else:
            raise ValueError(f"Metodo non supportato: {method}")
        
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Errore nella richiesta API: {e}")
        
        # Informazioni più dettagliate per debug
        error_info = {
            "error": str(e),
            "url": url,
            "method": method
        }
        
        if hasattr(e, "response") and e.response is not None:
            error_info["status_code"] = e.response.status_code
            try:
                error_info["response_text"] = e.response.text
            except:
                pass
        
        return {"error": error_info}

# Endpoint principale per la UI
@app.get("/", response_class=HTMLResponse)
async def get_home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# Endpoint per verificare lo stato del servizio
@app.get("/status")
async def get_status():
    try:
        # Verifica lo stato del backend
        backend_status = call_backend_api("status", method="GET", timeout=5)
        
        if "error" in backend_status:
            backend_ready = False
            backend_error = str(backend_status["error"])
        else:
            backend_ready = backend_status.get("ready", False)
            backend_error = backend_status.get("error")
        
        return {
            "frontend": {"status": "online", "active_clients": len(manager.active_connections)},
            "backend": {
                "status": "online" if backend_ready else "offline",
                "ready": backend_ready,
                "error": backend_error,
                "model": backend_status.get("model", "unknown")
            }
        }
    except Exception as e:
        return {
            "frontend": {"status": "online"},
            "backend": {"status": "error", "error": str(e)}
        }

# Endpoint per il controllo salute
@app.get("/health")
async def health_check():
    return {"status": "healthy"}

# Endpoint API per inviare query
@app.post("/api/query")
async def query_agent(request: QueryRequest):
    try:
        # Invia la richiesta al backend
        backend_response = call_backend_api(
            "query",
            data=request.dict(),
            method="POST",
            timeout=60
        )
        
        if "error" in backend_response:
            raise HTTPException(status_code=503, detail=f"Errore backend: {backend_response['error']}")
        
        # Genera un ID per questa query
        import uuid
        query_id = str(uuid.uuid4())
        
        return QueryResponse(
            query_id=query_id,
            query=request.query,
            response=backend_response.get("response", ""),
            status="success"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Modifica questa parte nella gestione WebSocket
@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await manager.connect(websocket, client_id)
    try:
        while True:
            # Ricevi messaggio dal client
            data = await websocket.receive_json()
            
            # Processa la query
            query = data.get("query", "")
            query_type = data.get("type", "standard")
            
            # Aggiungi alla cronologia come messaggio utente
            await manager.send_message(
                {"type": "user", "content": query, "timestamp": time.time()},
                client_id
            )
            
            # Invia notifica di elaborazione
            await manager.send_message(
                {"type": "status", "content": "Elaborazione in corso...", "timestamp": time.time()},
                client_id
            )
            
            try:
                # Invia la richiesta al backend CON IL CLIENT_ID
                backend_response = call_backend_api(
                    "query",
                    data={"query": query, "type": query_type, "client_id": client_id},  # Aggiungi client_id
                    method="POST",
                    timeout=60
                )
                
                if "error" in backend_response:
                    error_msg = str(backend_response["error"])
                    await manager.send_message(
                        {"type": "error", "content": f"Errore backend: {error_msg}", "timestamp": time.time()},
                        client_id
                    )
                    continue
                
                # Invia risposta al client
                await manager.send_message(
                    {"type": "assistant", "content": backend_response.get("response", ""), "timestamp": time.time()},
                    client_id
                )
            except Exception as e:
                await manager.send_message(
                    {"type": "error", "content": f"Errore: {str(e)}", "timestamp": time.time()},
                    client_id
                )
    
    except WebSocketDisconnect:
        manager.disconnect(client_id)

# Avvia il server
if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=PORT, reload=DEBUG)