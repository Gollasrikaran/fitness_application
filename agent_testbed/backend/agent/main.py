"""The agent graph: a doctor asks about one of their patients.

  load_context (clinic record, no AI) → chat (answers from the record)

Patients don't chat with the agent: they only see the plan a doctor approved.
"""
from __future__ import annotations

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from agent import nodes
from agent.nodes import AgentUnavailable
from agent.state import AgentState
from store import messages as message_store
from store.db import SCHEMA, psycopg_url, session

__all__ = ["AgentUnavailable", "close_memory", "graph", "open_memory", "run_turn"]


def _in_our_schema(conn) -> None:
    # The checkpointer's tables live in the temp database's agent_tmp schema,
    # next to ours. (The temp database uses the session pooler, so this holds.)
    conn.execute(f'SET search_path TO "{SCHEMA}"')


# The agent's memory of each conversation, in the temp database: it survives
# restarts. Opened by open_memory() when the app starts.
_memory_pool = ConnectionPool(psycopg_url(), min_size=1, max_size=4, open=False, configure=_in_our_schema,
                              kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": None})
checkpointer = PostgresSaver(_memory_pool)


def open_memory() -> None:
    _memory_pool.open()
    checkpointer.setup()  # creates or migrates its tables; safe on every start


def close_memory() -> None:
    _memory_pool.close(timeout=1)


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("load_context", nodes.load_context)
    g.add_node("chat", nodes.chat)
    g.add_edge(START, "load_context")
    g.add_edge("load_context", "chat")
    g.add_edge("chat", END)
    return g.compile(checkpointer=checkpointer)


graph = build_graph()


def thread_id(patient_id: str, doctor_id: str) -> str:
    """One conversation per doctor and patient."""
    return f"doctor:{doctor_id}:{patient_id}"


def run_turn(patient_id: str, doctor_id: str, message: str) -> dict:
    thread = thread_id(patient_id, doctor_id)
    state = graph.invoke({"messages": [HumanMessage(content=message)], "patient_id": patient_id,
                          "doctor_id": doctor_id}, {"configurable": {"thread_id": thread}})
    reply = state["messages"][-1].content
    decision = {"conditions": state.get("conditions", [])}
    with session() as db:
        message_store.save_turn(db, thread, "doctor", patient_id, doctor_id, message, reply, decision)
    return {"reply": reply, **decision}
