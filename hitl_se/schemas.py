"""Small strict JSON-schema subset: no dependency, no coercion or extra fields."""
from .util import WorkflowError

S = {"type": "string", "minLength": 1, "maxLength": 100_000}
B = {"type": "boolean"}
F = {"type": "number", "minimum": 0, "maximum": 1}


def array(item=S, minimum=0):
    return {"type": "array", "items": item, "minItems": minimum, "maxItems": 100}


def obj(**properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


FILES = {"type": "object", "additionalProperties": S}
REQ = obj(id=S, statement=S, acceptance=array(S, 1), priority=S)
COMMON = dict(summary=S, rationale=S, risks=array(), alternatives=array())
FACT = obj(claim=S, evidence=array(S, 1))
OPTION = obj(id=S, description=S, tradeoffs=array(S, 1), evidence=array(S, 1))


def role_schema(**fields):
    return obj(**COMMON, **fields)


SCHEMAS = {
    "collector": role_schema(requirements=array(REQ, 1), questions=array(), assumptions=array()),
    "modeler": role_schema(requirements=array(REQ, 1), entities=array(obj(name=S, attributes=array())), relationships=array(obj(source=S, target=S, description=S)), constraints=array(), assumptions=array()),
    "documenter": role_schema(overview=S, glossary=FILES),
    "design_search": role_schema(queries=array(S, 1), criteria=array(S, 1)),
    "architect": role_schema(options=array(OPTION, 2), recommendation=S),
    "refiner": role_schema(options=array(OPTION, 2), recommendation=S),
    "planner_a": role_schema(approach=S, steps=array(S, 1), test_files=FILES, acceptance_mapping=array(obj(requirement=S, test=S), 1), assumptions=array()),
    "planner_b": role_schema(approach=S, steps=array(S, 1), test_files=FILES, acceptance_mapping=array(obj(requirement=S, test=S), 1), assumptions=array()),
    "implementer_a": role_schema(files=FILES),
    "implementer_b": role_schema(files=FILES),
    "reviewer_a": role_schema(differences=array(FACT, 1), failures=array(FACT), risk_analysis=array(FACT, 1), tradeoffs=array(FACT, 1), recommendation=S),
    "reviewer_b": role_schema(differences=array(FACT, 1), failures=array(FACT), risk_analysis=array(FACT, 1), tradeoffs=array(FACT, 1), recommendation=S),
    "test_planner": role_schema(objective=S, test_files=FILES, success_criteria=array(S, 1), constraints=array(), assumptions=array(), confidence=F),
    "test_proposer": role_schema(tool=S, expected_result=S, side_effects=array(), confidence=F, strategy_changed=B, environment_changed=B),
    "test_summarizer": role_schema(observations=array(S, 1), next={"type": "string", "enum": ["continue", "complete"]}, confidence=F),
    "completion": role_schema(evidence=array(S, 1), remaining_work=array()),
    "deployment_assistant": role_schema(instructions=array(S, 1), rollback=array(S, 1)),
    "review_facilitator": role_schema(demo_steps=array(S, 1), stakeholder_questions=array(S, 1)),
    "explainer": role_schema(answer=S, evidence=array()),
}


def validate(schema, value, path="result"):
    t = schema["type"]
    ok = {"object": isinstance(value, dict), "array": isinstance(value, list),
          "string": isinstance(value, str), "number": type(value) in (int, float),
          "boolean": type(value) is bool}[t]
    if not ok:
        raise WorkflowError(f"{path} must be {t}")
    if "enum" in schema and value not in schema["enum"]:
        raise WorkflowError(f"{path} is not a permitted value")
    if t == "object":
        properties = schema.get("properties", {})
        if set(schema.get("required", [])) - value.keys():
            raise WorkflowError(f"{path} is missing required fields")
        for key, item in value.items():
            child = properties.get(key, schema.get("additionalProperties", False))
            if child is False:
                raise WorkflowError(f"{path} contains unexpected field {key}")
            validate(child, item, f"{path}.{key}")
    if t == "array":
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 100):
            raise WorkflowError(f"{path} has an invalid item count")
        for i, item in enumerate(value):
            validate(schema["items"], item, f"{path}[{i}]")
    if t == "string" and not schema.get("minLength", 0) <= len(value.strip()) <= schema.get("maxLength", 100_000):
        raise WorkflowError(f"{path} has an invalid text length")
    if t == "number" and not schema.get("minimum", 0) <= value <= schema.get("maximum", 1):
        raise WorkflowError(f"{path} is outside the valid range")
    return value
