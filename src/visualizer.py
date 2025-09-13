from src.ast import *

class Visualizer:
    """
    Traverses the AST to generate a Graphviz DOT file string.
    """
    def __init__(self):
        self.dot_string = ""
        self.nodes = set()
        self.edges = []
        self.counter = 0

    def generate_dot(self, ast: Program) -> str:
        """
        Generates a Graphviz DOT string from the program's AST.
        """
        self.dot_string += "digraph ChaosScenario {\n"
        self.dot_string += "  rankdir=LR;\n"
        self.dot_string += "  node [shape=box];\n"
        
        self.traverse_ast(ast.statements)
        
        for node in self.nodes:
            self.dot_string += f'  "{node}" [label="{node}"];\n'
        
        for edge in self.edges:
            self.dot_string += f'  "{edge["from"]}" -> "{edge["to"]}" [label="{edge["label"]}" color="{edge["color"]}" style="{edge["style"]}"];\n'

        self.dot_string += "}\n"
        return self.dot_string

    def traverse_ast(self, statements: list):
        for stmt in statements:
            if isinstance(stmt, Scenario):
                self.dot_string += f'  subgraph "cluster_{stmt.name}" {{\n'
                self.dot_string += f'    label="{stmt.name}";\n'
                self.traverse_ast(stmt.statements)
                self.dot_string += '  }\n'
            elif isinstance(stmt, ChaosStatement):
                self.map_chaos_statement(stmt)
            # You can add logic for IfStatement and LoopStatement visualization here

    def map_chaos_statement(self, stmt: ChaosStatement):
        if isinstance(stmt, NodeStatement):
            node_name = f"Node_{stmt.service}"
            self.nodes.add(node_name)
            for action in stmt.actions:
                action_label = f"{action.__class__.__name__}"
                self.edges.append({
                    "from": node_name,
                    "to": node_name,
                    "label": action_label,
                    "color": "red",
                    "style": "dashed"
                })
        elif isinstance(stmt, PartitionStatement):
            from_filter = " & ".join([f"{p.key}={p.value}" for p in stmt.from_filter.pairs])
            to_filter = " & ".join([f"{p.key}={p.value}" for p in stmt.to_filter.pairs])
            
            from_node = f"Pods_{from_filter}"
            to_node = f"Pods_{to_filter}"
            self.nodes.add(from_node)
            self.nodes.add(to_node)
            
            label = f"Partition {stmt.duration.value}{stmt.duration.unit}" if stmt.duration else "Partition"
            self.edges.append({
                "from": from_node,
                "to": to_node,
                "label": label,
                "color": "blue",
                "style": "bold"
            })
        elif isinstance(stmt, LinkStatement):
            from_node = f"Pod_{stmt.from_service}"
            to_node = f"Pod_{stmt.to_service}"
            self.nodes.add(from_node)
            self.nodes.add(to_node)
            for action in stmt.actions:
                action_label = f"{action.__class__.__name__}"
                self.edges.append({
                    "from": from_node,
                    "to": to_node,
                    "label": action_label,
                    "color": "green",
                    "style": "solid"
                })
