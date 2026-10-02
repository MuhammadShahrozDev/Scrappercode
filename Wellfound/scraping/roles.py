import json
from pathlib import Path

# Project root (this file now lives one level down, in
# scraping/ or processing/), so go up an extra level.
BASE_DIR = Path(__file__).resolve().parent.parent

ROLES_FILE = BASE_DIR / "config" / "roles.json"

def load_roles(path = ROLES_FILE):
    """Load all roles from roles.json."""

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_role_lookup(roles):
    """
    Returns:
        {role_id: role}
    """

    return {role["id"]: role for role in roles}


def build_role_tree(roles):
    """
    Returns:
        {
            parent_id: [child1, child2, ...]
        }
    """

    tree = {}

    for role in roles:

        parent = role["parentId"]

        tree.setdefault(parent, []).append(role)

    return tree


def get_parent_roles(tree):
    """
    Returns all top-level roles.
    """

    return tree.get(None, [])


def get_child_roles(tree, parent_id):
    """
    Returns the direct children of a role.
    """

    return tree.get(parent_id, [])


def get_scrape_order(tree):
    """
    Returns every selectable role in depth-first, children-first order.
    """

    order = []

    def walk(parent_id):

        for role in get_child_roles(tree, parent_id):

            # Visit children first
            walk(role["id"])

            # Then this role
            if role["selectable"]:
                order.append(role)

    walk(None)

    return order