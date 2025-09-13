import sys
import argparse
import subprocess
import tempfile
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Any
from lark import Lark, Transformer, Tree

@dataclass
class ASTNode:
    """Base class for all AST nodes"""
    pass

@dataclass
class Program(ASTNode):
    statements: List['Statement']

@dataclass
class Statement(ASTNode):
    pass

@dataclass
class Scenario(Statement):
    name: str
    statements: List['ChaosStatement']

@dataclass
class IfStatement(Statement):
    condition: 'Condition'
    then_branch: List[Statement]
    else_branch: Optional[List[Statement]] = None

@dataclass
class Condition(ASTNode):
    metric: str
    operator: str
    value: Any

@dataclass
class LoopStatement(Statement):
    variable: str
    start: int
    end: int
    body: List[Statement]

@dataclass
class ChaosStatement(Statement):
    pass

@dataclass
class NodeStatement(ChaosStatement):
    service: str
    actions: List['NodeAction']

@dataclass
class NodeAction(ASTNode):
    pass

@dataclass
class DelayAction(NodeAction):
    duration: 'Duration'
    jitter: Optional['Duration'] = None

@dataclass
class LossAction(NodeAction):
    percentage: float

@dataclass
class CrashAction(NodeAction):
    pass

@dataclass
class RestartAction(NodeAction):
    pass

@dataclass
class PartitionStatement(ChaosStatement):
    from_filter: 'Filter'
    to_filter: 'Filter'
    duration: Optional['Duration'] = None

@dataclass
class LinkStatement(ChaosStatement):
    from_service: str
    to_service: str
    actions: List['LinkAction']

@dataclass
class LinkAction(ASTNode):
    pass

@dataclass
class BandwidthAction(LinkAction):
    rate: 'Rate'

@dataclass
class Filter(ASTNode):
    pairs: List['KeyValuePair']

@dataclass
class KeyValuePair(ASTNode):
    key: str
    value: str

@dataclass
class Duration(ASTNode):
    value: float
    unit: str
    
    def to_seconds(self) -> float:
        """Convert duration to seconds"""
        if self.unit == 'ms':
            return self.value / 1000
        elif self.unit == 's':
            return self.value
        elif self.unit == 'm':
            return self.value * 60
        return self.value

@dataclass
class Rate(ASTNode):
    value: float
    unit: str
