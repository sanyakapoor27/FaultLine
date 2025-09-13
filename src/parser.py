from lark import Lark, Transformer
from src.ast import *

GRAMMAR = r"""
    ?start: program

    program: stmt*

    stmt: scenario
        | if_stmt
        | loop_stmt
        | chaos_stmt

    scenario: "scenario" IDENTIFIER "{" chaos_stmt* "}"

    if_stmt: "if" "(" condition ")" "{" stmt* "}" ("else" "{" stmt* "}")?

    condition: metric_identifier OP value
    
    OP: ">" | "<" | ">=" | "<=" | "==" | "!="

    loop_stmt: "for" "(" IDENTIFIER "in" range ")" "{" stmt* "}"
    
    range: NUMBER ".." NUMBER

    chaos_stmt: node_stmt
              | partition_stmt
              | link_stmt

    node_stmt: "node" service_identifier "{" node_action+ "}"
    
    node_action: delay_action
               | loss_action
               | crash_action
               | restart_action

    delay_action: "delay" duration ("jitter" duration)?
    
    loss_action: "loss" percentage
    
    crash_action: "crash"
    
    restart_action: "restart"

    partition_stmt: "partition" filter "from" filter ("duration" duration)?

    link_stmt: "link" service_identifier "->" service_identifier "{" link_action+ "}"
    
    link_action: (delay_action | loss_action | bandwidth_action) ("duration" duration)?

    bandwidth_action: "bandwidth" rate

    filter: key_value_pair+
    
    key_value_pair: IDENTIFIER "=" IDENTIFIER

    service_identifier: IDENTIFIER
    
    metric_identifier: IDENTIFIER

    TIME_UNIT: "ms" | "s" | "m"
    
    RATE_UNIT: "kbps" | "mbps" | "gbps"

    duration: NUMBER TIME_UNIT
    
    rate: NUMBER RATE_UNIT

    percentage: NUMBER "%"

    value: NUMBER | STRING

    IDENTIFIER: /[a-zA-Z_][a-zA-Z0-9_-]*/
    
    STRING: /"[^"]*"/
    
    NUMBER: /\d+(\.\d+)?/

    %import common.WS
    %ignore WS
    %ignore /\/\/[^\n]*/
"""
class Transformer(Transformer):
    """Transform Lark parse tree into our AST"""
    
    def program(self, items):
        return Program(statements=items if items else [])
    
    def stmt(self, items):
        return items[0] if items else None
    
    def scenario(self, items):
        name = str(items[0])
        statements = [s for s in items[1:] if isinstance(s, ChaosStatement)]
        return Scenario(name=name, statements=statements)
    
    def if_stmt(self, items):
        condition_node = items[0]
        then_branch = []
        else_branch = None

        current_branch = then_branch
        for item in items[1:]:
            # 'else' keyword is handled by Lark as a token/string
            if isinstance(item, str) and item == 'else':
                current_branch = else_branch = []
            else:
                current_branch.append(item)  # <-- append directly, don't expect a list

        return IfStatement(
            condition=condition_node,
            then_branch=then_branch,
            else_branch=else_branch
        )


    def condition(self, items):
        return Condition(
            metric=str(items[0]),
            operator=str(items[1]),
            value=items[2]
        )
    
    def loop_stmt(self, items):
        variable = str(items[0])
        range_obj = items[1]
        body = []

        for stmt in items[2:]:
            if isinstance(stmt, list):
                body.extend(stmt)
            else:
                body.append(stmt)

        return LoopStatement(
            variable=variable,
            start=range_obj[0],
            end=range_obj[1],
            body=body
        )

    
    def range(self, items):
        return (int(items[0]), int(items[1]))
    
    def chaos_stmt(self, items):
        return items[0]
    
    def delay_action(self, items):
        duration = items[0]
        jitter = items[1] if len(items) > 1 else None
        return DelayAction(duration=duration, jitter=jitter)
    
    def loss_action(self, items):
        return LossAction(percentage=items[0])
    
    def crash_action(self, items):
        return CrashAction()
    
    def restart_action(self, items):
        return RestartAction()
    
    def partition_stmt(self, items):
        from_filter = items[0]
        to_filter = items[1]
        duration = items[2] if len(items) > 2 else None
        return PartitionStatement(
            from_filter=from_filter,
            to_filter=to_filter,
            duration=duration
        )
    
    def node_stmt(self, items):
        service = items[0]
        print("service ", service)
        print("items ", items)
        actions = [a for a in flatten(items[1:]) if isinstance(a, (DelayAction, LossAction, CrashAction, RestartAction))]
        print("actions node ", actions)
        return NodeStatement(service=service, actions=actions)

    def link_stmt(self, items):
        from_service = items[0]
        to_service = items[1]
        print("link from service ", from_service)
        print("link to ", to_service)
        print("items ", items)
        actions = [a for a in flatten(items[2:]) if isinstance(a, (DelayAction, LossAction, BandwidthAction))]
        print("actions link ", actions)
        return LinkStatement(from_service=from_service, to_service=to_service, actions=actions)

    def node_action(self, items):
        return items[0] if items else None

    def link_action(self, items):
        action = items[0]

        #for optional duration in case
        if len(items) > 1:
            action.duration = items[1]
        return action

    def bandwidth_action(self, items):
        return BandwidthAction(rate=items[0])
    
    def filter(self, items):
        return Filter(pairs=items)
    
    def key_value_pair(self, items):
        return KeyValuePair(key=str(items[0]), value=str(items[1]))
    
    def service_identifier(self, items):
        return str(items[0])
    
    def metric_identifier(self, items):
        return str(items[0])
    
    def percentage(self, items):
        return float(items[0])
    
    def duration(self, items):
        number = float(items[0])
        unit = str(items[1])
        return Duration(value=number, unit=unit)

    def rate(self, items):
        number = float(items[0])
        unit = str(items[1])
        return Rate(value=number, unit=unit)

    def value(self, items):
        item = items[0]
        if hasattr(item, 'value'):
            item = item.value

        if isinstance(item, str) and item.startswith('"'):
            return item.strip('"')
        try:
            return float(item)
        except:
            return str(item)
    
    def operator(self, items):
        return str(items[0])
    
    def IDENTIFIER(self, token):
        return str(token)
    
    def NUMBER(self, token):
        return float(token)
    
    def STRING(self, token):
        return str(token).strip('"')
    
def flatten(lst):
    for i in lst:
        if isinstance(i, list):
            yield from flatten(i)
        else:
            yield i

class Parser:
    """Parser for DSL"""
    
    def __init__(self):
        self.parser = Lark(GRAMMAR, start='program', parser='lalr')
        self.transformer = Transformer()
    
    def parse(self, text: str) -> Program:
        """Parse DSL text and return AST"""
        try:
            tree = self.parser.parse(text)
            ast = self.transformer.transform(tree)
            return ast
        except Exception as e:
            print(f"[Network Chaos] Parse error: {e}")
            raise