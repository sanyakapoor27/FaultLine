Program       ::= Stmt*

Stmt          ::= Scenario | IfStmt | LoopStmt | ChaosStmt

Scenario      ::= "scenario" Identifier "{" ChaosStmt* "}"

IfStmt        ::= "if" "(" Condition ")" "{" Stmt* "}" ("else" "{" Stmt* "}")?
Condition     ::= MetricIdentifier Operator Value
Operator      ::= ">" | "<" | ">=" | "<=" | "==" | "!="

LoopStmt      ::= "for" "(" Identifier "in" Range ")" "{" Stmt* "}"
Range         ::= Number ".." Number

ChaosStmt     ::= NodeStmt | PartitionStmt | LinkStmt

NodeStmt      ::= "node" ServiceIdentifier "{" NodeAction* "}"
NodeAction    ::= DelayAction | LossAction | CrashAction | RestartAction
DelayAction   ::= "delay" Duration ("jitter" Duration)?
LossAction    ::= "loss" Percentage
CrashAction   ::= "crash"
RestartAction ::= "restart"

PartitionStmt ::= "partition" Filter "from" Filter ("duration" Duration)?
LinkStmt      ::= "link" ServiceIdentifier "->" ServiceIdentifier "{" LinkAction* "}"
LinkAction    ::= DelayAction | LossAction | BandwidthAction
BandwidthAction ::= "bandwidth" Rate

Filter        ::= KeyValuePair+
KeyValuePair  ::= Identifier "=" Identifier

ServiceIdentifier ::= Identifier
MetricIdentifier  ::= Identifier
Duration      ::= Number ("ms"|"s"|"m")
Percentage    ::= Number "%"
Rate          ::= Number ("kbps"|"mbps"|"gbps")