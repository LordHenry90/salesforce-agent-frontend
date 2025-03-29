import os
import json
import time
import uuid
import requests
from datetime import datetime
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
MODEL_API_URL = os.environ.get("MODEL_API_URL", "https://lordhenry-salesforce-agent.hf.space/query")
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
    timestamp: float = time.time()

class FeedbackRequest(BaseModel):
    query_id: str
    rating: int
    feedback_text: Optional[str] = None

class ConversationHistory(BaseModel):
    client_id: str
    messages: List[Dict[str, Any]] = []
    last_updated: str = datetime.now().isoformat()

# Archiviazione in-memory per cronologia (in produzione usare Redis/DB)
conversation_store = {}
feedback_store = []

# Gestione delle connessioni WebSocket
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        
        # Invia la cronologia dei messaggi se esiste
        if client_id in conversation_store:
            for message in conversation_store[client_id].messages:
                await websocket.send_json(message)

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]

    async def send_message(self, message: dict, client_id: str):
        # Aggiorna la cronologia
        if client_id not in conversation_store:
            conversation_store[client_id] = ConversationHistory(client_id=client_id)
        
        conversation_store[client_id].messages.append(message)
        conversation_store[client_id].last_updated = datetime.now().isoformat()
        
        # Limita la cronologia a 50 messaggi
        if len(conversation_store[client_id].messages) > 50:
            conversation_store[client_id].messages = conversation_store[client_id].messages[-50:]
        
        # Invia il messaggio se il client è connesso
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_json(message)

manager = ConnectionManager()

# Endpoint principale per la UI
@app.get("/", response_class=HTMLResponse)
async def get_home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# Endpoint per verificare lo stato del servizio
@app.get("/status")
async def get_status():
    try:
        # Verifica lo stato del servizio di inferenza
        response = requests.get(f"{MODEL_API_URL}/status", 
                               headers={"Authorization": f"Bearer {API_KEY}"},
                               timeout=5)
        
        if response.status_code == 200:
            backend_status = response.json()
        else:
            backend_status = {"ready": False, "error": f"Backend returned status code {response.status_code}"}
    except Exception as e:
        backend_status = {"ready": False, "error": str(e)}
    
    return {
        "frontend": {"status": "online"},
        "backend": backend_status,
        "active_clients": len(manager.active_connections)
    }

# Endpoint per il controllo salute
@app.get("/health")
async def health_check():
    return {"status": "healthy"}

# Endpoint API per inviare query
@app.post("/api/query")
async def query_agent(request: QueryRequest):
    try:
        # Genera un ID univoco per la query
        query_id = str(uuid.uuid4())
        
        # Invia la richiesta al servizio di inferenza
        payload = {
            "query": request.query,
            "type": request.type
        }
        
        response = requests.post(
            f"{MODEL_API_URL}/query",
            json=payload,
            headers={"Authorization": f"Bearer {API_KEY}"},
            timeout=60  # Timeout più lungo per inferenza
        )
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, 
                               detail=f"Backend error: {response.text}")
        
        response_data = response.json()
        
        return QueryResponse(
            query_id=query_id,
            query=request.query,
            response=response_data.get("response", ""),
            status="success"
        )
    except requests.Timeout:
        raise HTTPException(status_code=504, detail="Backend service timeout")
    except requests.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Backend service error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Endpoint per il feedback
@app.post("/api/feedback")
async def provide_feedback(request: FeedbackRequest):
    try:
        # Archivia il feedback
        feedback_data = {
            "query_id": request.query_id,
            "rating": request.rating,
            "feedback_text": request.feedback_text,
            "timestamp": datetime.now().isoformat()
        }
        
        feedback_store.append(feedback_data)
        
        # Opzionale: invia anche al backend
        try:
            requests.post(
                f"{MODEL_API_URL}/feedback",
                json=feedback_data,
                headers={"Authorization": f"Bearer {API_KEY}"},
                timeout=5
            )
        except Exception as e:
            print(f"Errore nell'invio del feedback al backend: {e}")
            # Non fallisce se il backend non riceve il feedback
        
        return {"status": "Feedback ricevuto, grazie!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Endpoint per le metriche
@app.get("/api/metrics")
async def get_metrics():
    try:
        # Metriche locali
        local_metrics = {
            "active_users": len(manager.active_connections),
            "conversation_count": len(conversation_store),
            "feedback_count": len(feedback_store),
            "average_rating": sum(item["rating"] for item in feedback_store) / len(feedback_store) 
                              if feedback_store else 0
        }
        
        # Prova a ottenere metriche dal backend
        try:
            response = requests.get(
                f"{MODEL_API_URL}/metrics",
                headers={"Authorization": f"Bearer {API_KEY}"},
                timeout=5
            )
            
            if response.status_code == 200:
                backend_metrics = response.json()
                # Combina metriche locali e di backend
                return {**local_metrics, "backend": backend_metrics}
        except Exception as e:
            print(f"Errore nel recupero metriche dal backend: {e}")
        
        # Ritorna solo metriche locali se il backend non è disponibile
        return local_metrics
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# WebSocket per comunicazione in tempo reale
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
                # Invia la richiesta al servizio di inferenza
                payload = {
                    "query": query,
                    "type": query_type,
                    "client_id": client_id
                }
                
                response = requests.post(
                    f"{MODEL_API_URL}/query",
                    json=payload,
                    headers={"Authorization": f"Bearer {API_KEY}"},
                    timeout=120  # Timeout più lungo per inferenza
                )
                
                if response.status_code != 200:
                    raise Exception(f"Backend error: {response.text}")
                
                response_data = response.json()
                
                # Invia risposta al client
                await manager.send_message(
                    {"type": "assistant", "content": response_data.get("response", ""), "timestamp": time.time()},
                    client_id
                )
            except requests.Timeout:
                await manager.send_message(
                    {"type": "error", "content": "Il server ha impiegato troppo tempo a rispondere. Riprova più tardi.", "timestamp": time.time()},
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
