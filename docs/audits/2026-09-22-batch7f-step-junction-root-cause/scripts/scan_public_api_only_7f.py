"""Batch 7F: static check that every `devsim.<name>` attribute access in this
audit's own scripts is public (no `devsim._*`/private/internal symbol).
Mirrors Batch 7D's own scan_public_api_only.py pattern.
usage: python scan_public_api_only_7f.py <script.py> [<script.py> ...]
"""
import ast
import sys

ALLOWLIST = {
    "node_model", "edge_model", "set_node_values", "set_parameter", "get_parameter", "equation", "contact_equation",
    "interface_equation", "solve", "get_node_model_values", "get_node_model_list", "get_edge_model_values",
    "get_edge_model_list", "get_contact_current", "get_contact_list", "get_device_list", "create_1d_mesh",
    "add_1d_mesh_line", "add_1d_contact", "add_1d_region", "create_2d_mesh", "add_2d_mesh_line", "add_2d_region",
    "add_2d_contact", "create_gmsh_mesh", "add_gmsh_region", "add_gmsh_contact", "add_gmsh_interface",
    "finalize_mesh", "create_device", "delete_device", "delete_mesh", "write_devices", "print_node_values",
    "get_dimension", "element_from_edge_model", "get_element_model_values", "get_element_node_list",
    "vector_element_model", "get_element_model_list", "error",
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
