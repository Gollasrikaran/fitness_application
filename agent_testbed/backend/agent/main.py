"""The agent graph.

patient mode:
  load_context → safety_screen ─┬─ emergency (fixed reply, no AI)
                                └─ supervisor ─┬─ chat (also asks one clarifying question)
                                               ├─ plan
                                               ├─ doctor_handoff
                                               └─ emergency
doctor mode:
  load_context → chat (answers the doctor about the patient)
"""
from __future__ import annotations

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from agent import nodes, routing
from agent.nodes import AgentUnavailable
from agent.state import AgentState

__all__ = ["AgentUnavailable", "graph", "run_turn"]


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("load_context", nodes.load_context)
    g.add_node("safety_screen", nodes.safety_screen)
    g.add_node("emergency", nodes.emergency)
    g.add_node("supervisor", nodes.supervisor)
    g.add_node("chat", nodes.chat)
    g.add_node("plan", nodes.plan)
    g.add_node("doctor_handoff", nodes.doctor_handoff)

    g.add_edge(START, "load_context")
    g.add_conditional_edges("load_context", routing.after_load, ["chat", "safety_screen"])
    g.add_conditional_edges("safety_screen", routing.after_safety, ["emergency", "supervisor"])
    g.add_conditional_edges("supervisor", routing.after_supervisor,
                            ["chat", "plan", "doctor_handoff", "emergency"])
    for node in ("chat", "plan", "doctor_handoff", "emergency"):
        g.add_edge(node, END)
    # In memory: conversations last until the backend restarts.
    return g.compile(checkpointer=MemorySaver())


graph = build_graph()


def thread_id(mode: str, patient_id: str, doctor_id: str | None) -> str:
    """One conversation per patient; a doctor's questions are kept separate."""
    return f"doctor:{doctor_id}:{patient_id}" if mode == "doctor" else f"patient:{patient_id}"


def run_turn(mode: str, patient_id: str, doctor_id: str | None, message: str) -> dict:
    config = {"configurable": {"thread_id": thread_id(mode, patient_id, doctor_id)}}
    state = graph.invoke({"messages": [HumanMessage(content=message)], "mode": mode,
                          "patient_id": patient_id, "doctor_id": doctor_id}, config)
    return {
        "reply": state["messages"][-1].content,
        "route": state.get("route"),
        "reason": state.get("reason"),
        "intent": state.get("intent"),
        "condition_severity": state.get("condition_severity"),
        "request_severity": state.get("request_severity"),
        "red_flags": state.get("red_flags", []),
        "forced_reasons": state.get("forced_reasons", []),
        "conditions": state.get("conditions", []),
        "pain_score": state.get("pain_score"),
        "case": state.get("case"),
    }
