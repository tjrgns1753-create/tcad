"""Static check: every `devsim.<name>` attribute access in a probe script is one of the names the batch's own
Backend Boundary section explicitly allows (plus the handful of read-only helpers the probe needs -- all
top-level, documented DEVSIM Python API). No AST match on `devsim._*`, `devsim.__internal*`, or any
private/underscore-prefixed attribute is permitted.
usage: python scan_public_api_only.py <script.py> [<script.py> ...]
"""
import ast
import sys

ALLOWLIST = {
    "node_model", "edge_model", "set_node_values", "set_parameter", "get_parameter", "equation", "contact_equation",
    "interface_equation", "solve", "get_node_model_values", "get_node_model_list", "get_edge_model_values",
    "get_edge_model_list", "get_contact_current", "get_contact_list", "get_device_list", "create_1d_mesh",
    "add_1d_mesh_line", "add_1d_contact", "add_1d_region", "finalize_mesh", "create_device", "delete_device",
    "delete_mesh", "write_devices", "print_node_values",
}

failed = False
for path in sys.argv[1:]:
    tree = ast.parse(open(path, encoding="utf-8").read())
    used = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "devsim":
            used.add(n.attr)
    private = {a for a in used if a.startswith("_")}
    disallowed = used - ALLOWLIST - private
    print(f"{path}: devsim.* attributes used: {sorted(used)}")
    if private:
        print(f"  PRIVATE/INTERNAL ACCESS: {sorted(private)}")
        failed = True
    if disallowed:
        print(f"  NOT ON THE ALLOWLIST (review needed): {sorted(disallowed)}")
        failed = True

sys.exit(1 if failed else 0)
