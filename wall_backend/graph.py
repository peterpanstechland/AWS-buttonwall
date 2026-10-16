"""Project teaching workflows from rule state; never infer completion from a lit service.

config/solutions.json defines roles and prerequisites. config/workflows.json defines
illustrative capability handoffs, separate from activation order and AWS topology.
"""
import json
from collections import Counter
from pathlib import Path

from reference.rules import required_done

CONTENT = json.loads((Path(__file__).resolve().parents[1] / "config/workflows.json").read_text(encoding="utf-8"))


def project_graph(mission, done, selected=None, hide_answers=False, failure=None):
    layout = CONTENT["missions"][mission["id"]]
    lit = set(done)
    if selected is not None:
        # Spend each selected instance once, including repeated-service roles (M07).
        available = Counter(selected)
        lit = set()
        for node in mission["nodes"]:
            if available[node["service"]] > 0:
                lit.add(node["node_id"])
                available[node["service"]] -= 1
    connected = set()
    for _ in mission["nodes"]:
        for node in mission["nodes"]:
            if node["node_id"] in lit and set(node["depends_on"]) <= connected:
                connected.add(node["node_id"])
    complete = required_done(mission, connected)
    if selected is not None and Counter(selected) - Counter(n['service'] for n in mission['nodes']):
        complete = False
    nodes = []
    for node in mission["nodes"]:
        nid = node["node_id"]
        state = ("live" if nid in connected else "selected" if nid in lit else
                 "ready" if set(node["depends_on"]) <= connected else "locked")
        nodes.append({**node, "service": None if hide_answers and nid not in lit else node["service"],
                      "state": state, "x": layout["positions"][nid][0], "y": layout["positions"][nid][1]})
    active = connected | {"input"} | ({"output"} if complete else set())
    edges = [{**edge, "state": "live" if {edge["source"], edge["target"], *edge.get('requires', [])} <= active else "waiting"}
             for edge in layout["edges"]]
    if hide_answers:
        for edge in edges:
            if edge['state'] != 'live':
                edge['label'] = {'zh': '待接通', 'en': 'Pending'}
    return {"id": mission["id"], "title": mission["title"], "io": mission["io"], "nodes": nodes,
            "edges": edges, "scope": CONTENT["scope"], "architecture_note": mission.get('scope'), "sources": mission.get('sources', []), "teaching_points": mission["teaching_points"],
            "status": "collapsed" if failure else "complete" if complete else "building",
            "required_count": sum(n["required"] for n in nodes),
            "connected_count": sum(n["required"] and n["node_id"] in connected for n in nodes)}
