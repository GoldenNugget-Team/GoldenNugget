import ast
import math
import operator
import xml.etree.ElementTree as tree
from typing import Any

from .patch_session import current_patch_session

tree.register_namespace('', "http://www.apple.com/CoreAnimation/1.0")

def parse_equation(eq: str, val: str):
    """Evaluate numeric template offsets without exposing Python objects."""
    if len(eq) > 4096:
        raise ValueError("Template offset is too long")
    mapped = dict(zip(('x', 'y', 'z', 'a'), map(float, val.split())))
    binary = {ast.Add: operator.add, ast.Sub: operator.sub,
              ast.Mult: operator.mul, ast.Div: operator.truediv,
              ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
              ast.Pow: operator.pow}

    def evaluate(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            result = float(node.value)
        elif isinstance(node, ast.Name) and node.id in mapped:
            result = mapped[node.id]
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operand = evaluate(node.operand)
            result = operand if isinstance(node.op, ast.UAdd) else -operand
        elif isinstance(node, ast.BinOp) and type(node.op) in binary:
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 1024:
                raise ValueError("Template offset exponent is too large")
            result = binary[type(node.op)](left, right)
        else:
            raise ValueError("Template offsets support arithmetic and x/y/z/a only")
        if not isinstance(result, (int, float)) or not math.isfinite(result):
            raise ValueError("Template offset must be a finite number")
        return result

    results = []
    for expression in eq.split(','):
        try:
            parsed = ast.parse(expression.strip(), mode='eval')
        except SyntaxError as e:
            raise ValueError('Invalid template offset arithmetic') from e
        if sum(1 for _ in ast.walk(parsed)) > 128:
            raise ValueError("Template offset is too complex")
        results.append(str(evaluate(parsed.body)))
    return ' '.join(results)

def set_xml_value(file: str, id: str, key: str, val: Any, use_ca_id: bool = False):
    set_xml_values(file=file, id=id, keys=[key], values=[val], use_ca_id=use_ca_id)

def set_xml_values(file: str, id: str, keys: list[str], values: list[Any], use_ca_id: bool = False):
    session = current_patch_session()
    xml = session.xml(file) if session is not None else tree.parse(file)
    root = xml.getroot()
    # Do not mutate the caller's values while normalizing for XML.
    values = [int(value) if isinstance(value, bool) else value for value in values]

    # convert bool to integer
    for i in range(len(values)):
        if isinstance(values[i], bool):
            values[i] = int(values[i])
        # convert value to string
        if not isinstance(values[i], str):
            values[i] = str(values[i])

    # set all values with the nugget id passed by param
    if use_ca_id:
        idKey = "id"
    else:
        idKey = "nuggetId"
    for to_change in root.findall(f".//*[@{idKey}='{id}']"):
        eqn = to_change.get("nuggetOffset")
        # TODO: Allow offsets for more than just the first value
        for i in range(len(keys)):
            offsetVal = values[i]
            if i == 0 and eqn != None:
                offsetVal = parse_equation(eqn, offsetVal)
            to_change.set(keys[i], offsetVal)
    if use_ca_id:
        # also look for target id
        for to_change in root.findall(f".//*[@targetId='{id}']"):
            for i in range(len(keys)):
                # find the value type
                set_val = values[i]
                to_change.set(keys[i], set_val)

    # Batched callers commit only after all ordered edits succeed.
    if session is None:
        xml.write(file, encoding="UTF-8", xml_declaration=True)

def remove_from_root(root, search):
    for parent in root.findall(search + "/.."):
        for prop in parent.findall(search):
            parent.remove(prop)

def delete_xml_value(file: str, id: str, use_ca_id: bool = False):
    xml = tree.parse(file)
    root = xml.getroot()

    # delete all elements with the nugget id passed by param
    if use_ca_id:
        idKey = "id"
    else:
        idKey = "nuggetId"
    remove_from_root(root, search=f".//*[@{idKey}='{id}']")
    if use_ca_id:
        # also remove the target ids
        remove_from_root(root, search=f".//*[@targetId='{id}']")
    
    # write back to file
    xml.write(file, encoding="UTF-8", xml_declaration=True)
