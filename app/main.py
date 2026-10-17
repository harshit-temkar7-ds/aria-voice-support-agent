import logging
from pathlib import Path
from typing import Literal
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()
from . import agent, orders, summarizer  # noqa: E402

log = logging.getLogger("aria")
app = FastAPI(title="Aura Skincare Voice Agent")
STATIC = Path(__file__).parent / "static"


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    history: list[Turn] = Field(default_factory=list, max_length=60)


class SummaryRequest(BaseModel):
    transcript: list[Turn] = Field(default_factory=list, max_length=120)
    tool_events: list[dict] = Field(default_factory=list)


@app.get("/api/health")
def health():
    return {"status": "ok", "llm_configured": agent.get_client() is not None, "model": agent.MODEL}


@app.get("/api/orders")
def get_orders():
    return orders.list_orders()


@app.post("/api/reset")
def reset():
    orders.reset_orders()
    return {"status": "reset"}


@app.post("/api/chat")
def chat(req: ChatRequest):
    try:
        reply, events = agent.chat([t.model_dump() for t in req.history], req.message)
        return {"reply": reply, "tool_events": events}
    
    except agent.LLMNotConfigured:
        return JSONResponse(
            status_code=503,
            content={
                "error": "LLM not configured. Set GEMINI_API_KEY on the server."
            },
        )
    except Exception:
        log.exception("chat failed")
        return JSONResponse(status_code=502, content={"error": "The AI service had a problem. Please try again."})


@app.post("/api/summary")
def summary(req: SummaryRequest):
    return summarizer.summarize([t.model_dump() for t in req.transcript], req.tool_events)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
